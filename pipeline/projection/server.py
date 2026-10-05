"""USDM -> Dataset-JSON projection.

POST /project reads the study design back from the broker (the entities
the usdm service authored) and projects it into the SDTM trial-design
domains as Dataset-JSON files in the lake:

  TS  trial summary        (title, phase, sponsor)
  TA  trial arms
  TI  trial inclusion/exclusion criteria
  TV  trial visits

Standards are views, not the stored model: the broker keeps the cr-domain
graph; SDTM comes out as a projection. This is the same posture as the
T.O.P. cr-domain SPARQL projections, done here over NGSI-LD instead.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pnehttp
from dataset_json import build_dataset_json

LAKE_URL = os.environ.get("PNE_LAKE_URL", "http://lake:8105")
STUDY_ID_DEFAULT = os.environ.get("PNE_STUDY_ID", "CARDIO-118")


def value(entity: dict | None, attr: str, default=""):
    if not entity:
        return default
    node = entity.get(attr)
    if isinstance(node, dict):
        return node.get("value", node.get("object", default))
    return default


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


class ProjectionHandler(pnehttp.JsonHandler):
    ROUTES = {("POST", "/project"): "project"}

    def project(self, body):
        study_id = (body or {}).get("studyId") or STUDY_ID_DEFAULT
        timestamp = datetime.now(timezone.utc).isoformat()
        studies = pnehttp.broker_get_entities(
            "Study", query=f'studyId=="{study_id}"'
        )
        if not studies:
            return 404, {"error": f"study {study_id} not found in broker"}
        study = studies[0]
        sponsor_ref = value(study, "sponsoredBy", None)
        sponsor = None
        if sponsor_ref:
            sponsors = [
                s
                for s in pnehttp.broker_get_entities("Sponsor")
                if s["id"] == sponsor_ref
            ]
            sponsor = sponsors[0] if sponsors else None

        arms = pnehttp.broker_get_entities("Arm")
        criteria = pnehttp.broker_get_entities("EligibilityCriterion")
        visits = pnehttp.broker_get_entities("VisitDefinition")

        outputs = []

        ts_rows = [
            [study_id, 1, "STITLE", "Study Title", value(study, "studyTitle")],
            [study_id, 2, "TPHASE", "Trial Phase", value(study, "studyPhase")],
        ]
        if sponsor is not None:
            ts_rows.append(
                [study_id, 3, "SPONSOR", "Clinical Study Sponsor", value(sponsor, "name")]
            )
        ts_doc = build_dataset_json(
            "TS",
            "Trial Summary",
            [
                ("STUDYID", "Study Identifier", "string"),
                ("TSSEQ", "Sequence Number", "integer"),
                ("TSPARMCD", "Trial Summary Parameter Short Name", "string"),
                ("TSPARM", "Trial Summary Parameter", "string"),
                ("TSVAL", "Parameter Value", "string"),
            ],
            ts_rows,
        )
        result = lake_write(
            "datasetjson/ts.json",
            ts_doc,
            provenance={
                "source": "broker-study-design",
                "loader": "projection-trial-design",
                "time": timestamp,
            }
        )
        outputs.append({"name": "TS", "records": len(ts_rows), **result})

        ta_rows = [
            [study_id, value(a, "armCode"), value(a, "armName"), 1, "TRT", "Treatment"]
            for a in sorted(arms, key=lambda a: value(a, "armCode"))
        ]
        ta_doc = build_dataset_json(
            "TA",
            "Trial Arms",
            [
                ("STUDYID", "Study Identifier", "string"),
                ("ARMCD", "Planned Arm Code", "string"),
                ("ARM", "Description of Planned Arm", "string"),
                ("TAETORD", "Planned Order of Element within Arm", "integer"),
                ("ETCD", "Element Code", "string"),
                ("ELEMENT", "Description of Element", "string"),
            ],
            ta_rows,
        )
        result = lake_write(
            "datasetjson/ta.json",
            ta_doc,
            provenance={
                "source": "broker-study-design",
                "loader": "projection-trial-design",
                "time": timestamp,
            }
        )
        outputs.append({"name": "TA", "records": len(ta_rows), **result})

        ti_rows = []
        for idx, crit in enumerate(
            sorted(criteria, key=lambda c: value(c, "criterionType")), start=1
        ):
            ctype = value(crit, "criterionType")
            ti_rows.append(
                [
                    study_id,
                    f"{'INCL' if ctype == 'INCLUSION' else 'EXCL'}{idx:02d}",
                    value(crit, "criterionText"),
                    ctype,
                ]
            )
        ti_doc = build_dataset_json(
            "TI",
            "Trial Inclusion/Exclusion Criteria",
            [
                ("STUDYID", "Study Identifier", "string"),
                ("IETESTCD", "Incl/Excl Criterion Short Name", "string"),
                ("IETEST", "Incl/Excl Criterion", "string"),
                ("IECAT", "Inclusion/Exclusion Category", "string"),
            ],
            ti_rows,
        )
        result = lake_write(
            "datasetjson/ti.json",
            ti_doc,
            provenance={
                "source": "broker-study-design",
                "loader": "projection-trial-design",
                "time": timestamp,
            }
        )
        outputs.append({"name": "TI", "records": len(ti_rows), **result})

        tv_rows = [
            [
                study_id,
                value(v, "visitNumber"),
                value(v, "visitName"),
                value(v, "plannedStudyDay"),
            ]
            for v in sorted(visits, key=lambda v: value(v, "visitNumber") or 0)
        ]
        tv_doc = build_dataset_json(
            "TV",
            "Trial Visits",
            [
                ("STUDYID", "Study Identifier", "string"),
                ("VISITNUM", "Visit Number", "integer"),
                ("VISIT", "Visit Name", "string"),
                ("VISITDY", "Planned Study Day of Visit", "integer"),
            ],
            tv_rows,
        )
        result = lake_write(
            "datasetjson/tv.json",
            tv_doc,
            provenance={
                "source": "broker-study-design",
                "loader": "projection-trial-design",
                "time": timestamp,
            }
        )
        outputs.append({"name": "TV", "records": len(tv_rows), **result})

        return 200, {"studyId": study_id, "outputs": outputs}


if __name__ == "__main__":
    pnehttp.serve(ProjectionHandler, 8102, startup=pnehttp.wait_for_broker)
