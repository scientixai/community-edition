"""HTTP wrapper around the sdtm.oak (R) transformation.

On POST /run it snapshots execution state from the broker (participants,
visit occurrences, clinical observations), flattens it to raw EDC-style
CSV extracts, runs the sdtm.oak mapping (oak_transform.R), and writes the
resulting SDTM domains to the lake as CSV and Dataset-JSON. Runs are
idempotent: each run regenerates the SDTM view of current broker state.
"""

from __future__ import annotations

import csv
import os
import pathlib
import subprocess
import tempfile
from datetime import datetime, timezone

import pnehttp
from dataset_json import build_dataset_json

LAKE_URL = os.environ.get("PNE_LAKE_URL", "http://lake:8105")
STUDY_ID_DEFAULT = os.environ.get("PNE_STUDY_ID", "CARDIO-118")

VS_COLUMNS = [
    ("STUDYID", "Study Identifier", "string"),
    ("DOMAIN", "Domain Abbreviation", "string"),
    ("USUBJID", "Unique Subject Identifier", "string"),
    ("VSSEQ", "Sequence Number", "integer"),
    ("VSTESTCD", "Vital Signs Test Short Name", "string"),
    ("VSTEST", "Vital Signs Test Name", "string"),
    ("VSORRES", "Result or Finding in Original Units", "string"),
    ("VSORRESU", "Original Units", "string"),
    ("VSSTRESC", "Character Result/Finding in Std Format", "string"),
    ("VSSTRESN", "Numeric Result/Finding in Standard Units", "float"),
    ("VSSTRESU", "Standard Units", "string"),
    ("VISITNUM", "Visit Number", "float"),
    ("VISIT", "Visit Name", "string"),
    ("VSDTC", "Date/Time of Measurements", "datetime"),
]
DM_COLUMNS = [
    ("STUDYID", "Study Identifier", "string"),
    ("DOMAIN", "Domain Abbreviation", "string"),
    ("USUBJID", "Unique Subject Identifier", "string"),
    ("SUBJID", "Subject Identifier for the Study", "string"),
    ("RFSTDTC", "Subject Reference Start Date/Time", "date"),
    ("SEX", "Sex", "string"),
    ("COUNTRY", "Country", "string"),
    ("ARMCD", "Planned Arm Code", "string"),
    ("ARM", "Description of Planned Arm", "string"),
]


def attr_value(entity: dict, name: str):
    attr = entity.get(name)
    if isinstance(attr, dict):
        return attr.get("value", attr.get("object"))
    return attr


def attr_observed_at(entity: dict, name: str):
    attr = entity.get(name)
    if isinstance(attr, dict):
        return attr.get("observedAt")
    return None


def lake_write(rel_path: str, content, provenance: dict | None = None) -> dict:
    """Write content to the lake via the lake service write API."""
    write_body = {"path": rel_path, "content": content}
    if provenance:
        write_body["provenance"] = provenance
    status, body = pnehttp.request(
        "POST",
        f"{LAKE_URL}/objects",
        body=write_body,
    )
    if status != 200:
        raise RuntimeError(f"lake write failed: {status} {body}")
    return body or {}


def snapshot_raw(study_id: str, raw_dir: pathlib.Path, timestamp: str) -> dict:
    """Flatten broker state into raw EDC-style extracts for sdtm.oak."""
    # One broker can hold several studies; keep only this study's participants
    # (participants that name no study are kept for older seed data).
    study_urn = f"urn:ngsi-ld:Study:{study_id}"
    participants = [
        p for p in pnehttp.broker_get_entities("Participant")
        if attr_value(p, "forStudy") in (None, study_urn)
    ]
    visits = pnehttp.broker_get_entities("VisitOccurrence")
    visit_defs = {
        v["id"]: v for v in pnehttp.broker_get_entities("VisitDefinition")
    }
    observations = pnehttp.broker_get_entities("ClinicalObservation")
    arms = {a["id"]: a for a in pnehttp.broker_get_entities("Arm")}
    by_id = {p["id"]: p for p in participants}
    visits_by_id = {v["id"]: v for v in visits}

    def patnum(participant_id):
        part = by_id.get(participant_id)
        return attr_value(part, "screeningNumber") if part else None

    vitals_rows = []
    for obs in observations:
        part_ref = attr_value(obs, "forParticipant")
        if part_ref not in by_id:
            continue
        visit_ref = attr_value(obs, "atVisit")
        visit = visits_by_id.get(visit_ref) if visit_ref else None
        vdef = None
        if visit is not None:
            vdef = visit_defs.get(attr_value(visit, "perVisitDefinition"))
        collected_at = attr_observed_at(obs, "numericValue")
        if not collected_at and visit is not None:
            collected_at = attr_value(visit, "actualStartDate")
        vitals_rows.append(
            {
                "PATNUM": patnum(part_ref) or "",
                "PARAMCD": attr_value(obs, "parameterCode") or "",
                "VALUE": attr_value(obs, "numericValue") or "",
                "UNIT": attr_value(obs, "unit") or "",
                "COLLECTED_AT": collected_at or "",
                "VISIT": attr_value(vdef, "visitName") if vdef else "",
                "VISITNUM": attr_value(vdef, "visitNumber") if vdef else "",
            }
        )

    dm_rows = []
    for part in participants:
        arm = arms.get(attr_value(part, "assignedToArm") or "")
        dm_rows.append(
            {
                "PATNUM": attr_value(part, "screeningNumber") or "",
                "SEX": attr_value(part, "sex") or "",
                "COUNTRY": attr_value(part, "country") or "",
                "ENROLLDT": attr_value(part, "enrollmentDate") or "",
                "ARMCD": attr_value(arm, "armCode") if arm else "",
                "ARM": attr_value(arm, "armName") if arm else "",
            }
        )

    for name, rows, fields in (
        ("raw_vitals.csv", vitals_rows, ["PATNUM", "PARAMCD", "VALUE", "UNIT", "COLLECTED_AT", "VISIT", "VISITNUM"]),
        ("raw_dm.csv", dm_rows, ["PATNUM", "SEX", "COUNTRY", "ENROLLDT", "ARMCD", "ARM"]),
    ):
        local_path = raw_dir / name
        with open(local_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        source = "broker-vitals-raw" if "vitals" in name else "broker-dm-raw"
        lake_write(
            f"raw/{name}",
            local_path.read_text(),
            provenance={
                "source": source,
                "loader": "transform-raw-snapshot",
                "time": timestamp,
            }
        )

    return {"vitals": len(vitals_rows), "participants": len(dm_rows)}


def csv_to_dataset_json(csv_path: pathlib.Path, name: str, label: str, columns, timestamp: str):
    """Convert CSV to Dataset-JSON and write to lake via the write API."""
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        typed_rows = []
        for row in reader:
            out = []
            for col_name, _, dtype in columns:
                val = row.get(col_name, "")
                if val == "":
                    out.append(None)
                elif dtype == "integer":
                    out.append(int(float(val)))
                elif dtype == "float":
                    out.append(float(val))
                else:
                    out.append(val)
            typed_rows.append(out)
    doc = build_dataset_json(name, label, columns, typed_rows)
    result = lake_write(
        f"sdtm/{name.lower()}.json",
        doc,
        provenance={
            "source": f"broker-{name.lower()}-transformed",
            "loader": "transform-sdtm",
            "time": timestamp,
        }
    )
    return {"name": name, "records": len(typed_rows), **result}


class TransformHandler(pnehttp.JsonHandler):
    ROUTES = {("POST", "/run"): "run", ("GET", "/status"): "status"}

    LAST = {"runs": 0, "last": None}

    def status(self, _body):
        return 200, self.LAST

    def run(self, body):
        study_id = (body or {}).get("studyId") or STUDY_ID_DEFAULT
        timestamp = datetime.now(timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = pathlib.Path(tmp) / "raw"
            out_dir = pathlib.Path(tmp) / "out"
            raw_dir.mkdir()
            counts = snapshot_raw(study_id, raw_dir, timestamp)
            proc = subprocess.run(
                ["Rscript", "/app/oak_transform.R", str(raw_dir), str(out_dir), study_id],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0:
                return 500, {
                    "error": "sdtm.oak transform failed",
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-4000:],
                }
            outputs = []
            for domain, label, columns in (
                ("VS", "Vital Signs", VS_COLUMNS),
                ("DM", "Demographics", DM_COLUMNS),
            ):
                src = out_dir / f"{domain.lower()}.csv"
                if src.exists():
                    lake_write(
                        f"sdtm/{domain.lower()}.csv",
                        src.read_text(),
                        provenance={
                            "source": f"broker-{domain.lower()}-transformed",
                            "loader": "transform-sdtm",
                            "time": timestamp,
                        }
                    )
                    outputs.append(csv_to_dataset_json(src, domain, label, columns, timestamp))
            result = {
                "engine": "sdtm.oak",
                "studyId": study_id,
                "raw": counts,
                "oakLog": proc.stdout.strip().splitlines()[-6:],
                "outputs": outputs,
            }
            TransformHandler.LAST = {
                "runs": TransformHandler.LAST["runs"] + 1,
                "last": result,
            }
            return 200, result


if __name__ == "__main__":
    pnehttp.serve(TransformHandler, 8104, startup=pnehttp.wait_for_broker)
