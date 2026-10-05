"""Source-system connectors: native extracts in, NGSI-LD facts out.

Each connector reads one system's export in that system's own shape and
emits events: (time the fact became true, source system, NGSI-LD entities).
Every attribute in an event carries observedAt = that time, so the broker's
temporal store can answer "what was true at time T" later.

Systems disagree about identifiers (EDC says 123-204, eConsent says
CVRM118-123-0204, LIMS says SITE123 / 0204). Resolving them to one IRI per
thing is the connector's job; nothing downstream sees the local formats.

Standard library only. The connectors know source formats, not scenarios:
they carry no subject, visit, or outcome.
"""

from __future__ import annotations

import csv
import json
import pathlib
import re
from collections import defaultdict

URN = "urn:ngsi-ld:"


# ------------------------------------------------------------- identity --

def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class Ids:
    """One IRI per real-world thing, whatever the source calls it."""

    def __init__(self, study: str):
        self.study = slug(study)

    def site(self, number: str) -> str:
        return f"{URN}StudySite:{self.study}-site-{int(number):03d}"

    def subject(self, site: str, number: str) -> str:
        return f"{URN}Participant:{self.study}-{int(site):03d}-{int(number)}"

    def consent(self, site: str, number: str) -> str:
        return f"{URN}InformedConsent:{self.study}-{int(site):03d}-{int(number)}"

    def visit(self, site: str, number: str, visit: str) -> str:
        return f"{URN}VisitOccurrence:{self.study}-{int(site):03d}-{int(number)}-{visit.lower()}"

    def person(self, org: str, name: str) -> str:
        return f"{URN}Person:{self.study}-{slug(org)}-{slug(name)}"

    def protocol(self, version: str) -> str:
        return f"{URN}ProtocolVersion:{self.study}-v{version}"

    def specimen(self, kit: str) -> str:
        return f"{URN}Specimen:{self.study}-{slug(kit)}"


def parse_edc_subject(ref: str):
    site, num = ref.split("-")          # EDC: "123-204"
    return site, num


def parse_econsent_subject(ref: str):
    _, site, num = ref.split("-")       # eConsent: "CVRM118-123-0204"
    return site, num


def parse_lims_subject(site: str, num: str):
    return site.upper().replace("SITE", ""), num   # LIMS: "SITE123", "0204"


def ts(s: str) -> str:
    """Source timestamps are site-local wall clock without zone; kept as UTC."""
    s = s.strip().replace(" ", "T")
    if len(s) == 10:
        s += "T00:00"
    if len(s) == 16:
        s += ":00"
    return s + "Z"


def rel(target: str) -> dict:
    return {"rel": target}


def read_csv(path: pathlib.Path) -> list[dict]:
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


# ----------------------------------------------------------- connectors --
# Each returns a list of events: {"at", "system", "entities", "note"}.

def protocol_authoring(src: pathlib.Path, ids: Ids) -> list[dict]:
    doc = json.loads((src / "protocol_versions.json").read_text())
    study = f"{URN}Study:{ids.study}"
    sponsor = f"{URN}Sponsor:{slug(doc['sponsor'])}"
    events = []
    for v in doc["versions"]:
        pv = ids.protocol(v["version"])
        events.append({"at": ts(v["approved"]), "system": "Protocol authoring",
                       "note": f"Protocol v{v['version']} approved", "entities": [
            {"id": sponsor, "type": "Sponsor", "name": doc["sponsor"]},
            {"id": study, "type": "Study", "studyId": doc["study"], "studyPhase": doc["phase"],
             "sponsoredBy": rel(sponsor), "hasProtocolVersion": rel(pv)},
            {"id": pv, "type": "ProtocolVersion", "name": f"{doc['study']} protocol v{v['version']}",
             "effectiveFrom": v["approved"], "pne:icfVersion": v["icfVersion"],
             "pne:pkTubeSpec": v["pkDraw"]["tubes"], "pne:spinSpec": v["pkDraw"]["spin"],
             "pne:shipTempMinC": v["shipping"]["tempMinC"], "pne:shipTempMaxC": v["shipping"]["tempMaxC"]},
        ]})
    return events


def ctms(src: pathlib.Path, ids: Ids) -> list[dict]:
    events = []
    first = {}
    study = f"{URN}Study:{ids.study}"
    for r in read_csv(src / "ctms_site_activations.csv"):
        site = ids.site(r["site_number"])
        first.setdefault(r["site_number"], r["activated_on"])
        act = f"{URN}SiteActivation:{ids.study}-site-{int(r['site_number']):03d}-v{r['protocol_version']}"
        events.append({"at": ts(r["activated_on"]), "system": "CTMS",
                       "note": f"{r['site_name']} activated on protocol v{r['protocol_version']}", "entities": [
            {"id": site, "type": "StudySite", "name": r["site_name"], "forStudy": rel(study)},
            {"id": act, "type": "SiteActivation", "atSite": rel(site),
             "activates": rel(ids.protocol(r["protocol_version"])), "effectiveFrom": r["activated_on"]},
        ]})
    for r in read_csv(src / "ctms_site_staff.csv"):
        events.append({"at": ts(first[r["site_number"]]), "system": "CTMS",
                       "note": f"Staff roster: {r['name']}", "entities": [
            {"id": ids.person(f"site-{r['site_number']}", r["name"]), "type": "Person", "name": r["name"],
             "pne:role": r["role"], "atSite": rel(ids.site(r["site_number"]))}]})
    return events


def _roster(src: pathlib.Path):
    staff = read_csv(src / "ctms_site_staff.csv")
    by_site_name = {(f"Site {r['site_number']}", r["name"]): r for r in staff}
    by_lms = {r["lms_user"]: r for r in staff}
    pi_of = {r["site_number"]: r["name"] for r in staff if r["role"] == "Principal investigator"}
    return by_site_name, by_lms, pi_of


def etmf(src: pathlib.Path, ids: Ids) -> list[dict]:
    by_site_name, _, pi_of = _roster(src)
    events = []
    for r in read_csv(src / "etmf_delegation_log.csv"):
        staff = by_site_name[(r["site"], r["staff_name"])]
        num = staff["site_number"]
        org = f"site-{num}"
        tasks = [t.strip() for t in r["delegated_tasks"].split(";")]
        ent = {"id": f"{URN}Delegation:{ids.study}-{slug(org)}-{slug(r['staff_name'])}", "type": "Delegation",
               "name": r["delegated_tasks"], "pne:tasks": tasks,
               "delegate": rel(ids.person(org, r["staff_name"])),
               "delegator": rel(ids.person(org, pi_of[num])),
               "atSite": rel(ids.site(num)), "effectiveFrom": r["start_date"]}
        if r["end_date"]:
            ent["effectiveTo"] = r["end_date"]
        events.append({"at": ts(r["start_date"]), "system": "eTMF delegation log",
                       "note": f"{r['site']}: {r['staff_name']} delegated {r['delegated_tasks']}",
                       "entities": [ent]})
    return events


def lms(src: pathlib.Path, ids: Ids) -> list[dict]:
    _, by_lms, _ = _roster(src)
    events = []
    for r in read_csv(src / "lms_training_records.csv"):
        staff = by_lms[r["lms_user"]]
        person = ids.person(f"site-{staff['site_number']}", staff["name"])
        ent = {"id": f"{URN}Credential:{ids.study}-{r['lms_user']}-{slug(r['course'])}", "type": "Credential",
               "name": r["course"], "pne:kind": r["kind"], "credentialOf": rel(person),
               "effectiveFrom": r["completed_on"]}
        if r["protocol_version"]:
            ent["ofProtocolVersion"] = rel(ids.protocol(r["protocol_version"]))
        if r["expires_on"]:
            ent["effectiveTo"] = r["expires_on"]
        events.append({"at": ts(r["completed_on"]), "system": "LMS",
                       "note": f"{staff['name']}: {r['course']}", "entities": [ent]})
    return events


def cmms(src: pathlib.Path, ids: Ids) -> list[dict]:
    events = []
    for r in read_csv(src / "cmms_equipment_calibration.csv"):
        dev = f"{URN}pne:Device:{ids.study}-{slug(r['equipment_id'])}"
        events.append({"at": ts(r["calibrated_on"]), "system": "CMMS",
                       "note": f"{r['equipment_id']} calibrated", "entities": [
            {"id": dev, "type": "pne:Device", "name": f"{r['model']}, S/N {r['serial']}",
             "atSite": rel(ids.site(r["site_number"]))},
            {"id": f"{URN}Credential:{ids.study}-{slug(r['equipment_id'])}-cal-{r['calibrated_on']}",
             "type": "Credential", "name": f"Calibration {r['calibrated_on']} (next due {r['next_due']})",
             "pne:kind": "calibration", "credentialOf": rel(dev),
             "effectiveFrom": r["calibrated_on"], "effectiveTo": r["next_due"]},
        ]})
    return events


def econsent(src: pathlib.Path, ids: Ids) -> list[dict]:
    events = []
    for r in read_csv(src / "econsent_signatures.csv"):
        site, num = parse_econsent_subject(r["participant_ref"])
        version = r["document"].split("v")[-1]
        events.append({"at": ts(r["signed_at"]), "system": "eConsent",
                       "note": f"Subject {int(num)} signed {r['document']}", "entities": [
            {"id": ids.consent(site, num), "type": "InformedConsent", "consentVersion": version,
             "consentDate": ts(r["signed_at"])[:10], "consentStatus": r["status"],
             "consentSubject": rel(ids.subject(site, num)),
             "witnessedBy": rel(ids.person(f"site-{int(site):03d}", r["witness"]))},
        ]})
    return events


def edc(src: pathlib.Path, ids: Ids) -> list[dict]:
    """EDC CRF items: one row per item; grouped back into forms per visit."""
    forms = defaultdict(dict)
    for r in read_csv(src / "edc_crf_items.csv"):
        forms[(r["subject"], r["visit"])][r["item"]] = r["value"]
    events = []
    study = f"{URN}Study:{ids.study}"
    for (ref, vis), item in sorted(forms.items()):
        site, num = parse_edc_subject(ref)
        org = f"site-{int(site):03d}"
        pid = ids.subject(site, num)
        if "ENROLLMENT_DATE" in item:
            events.append({"at": ts(item["ENROLLMENT_DATE"]), "system": "EDC",
                           "note": f"Subject {int(num)} enrolled at Site {site}", "entities": [
                {"id": pid, "type": "Participant", "screeningNumber": str(int(num)),
                 "forStudy": rel(study), "forStudySite": rel(ids.site(site)),
                 "hasConsent": rel(ids.consent(site, num)), "participantStatus": "ON_STUDY"}]})
            continue
        visit = ids.visit(site, num, vis)
        kit = item["KIT_ID"]
        spec = ids.specimen(kit)
        step = f"{URN}ActivityOccurrence:{ids.study}-{slug(kit)}-"
        dev = f"{URN}pne:Device:{ids.study}-{slug(item['CENTRIFUGE'])}"
        t_draw, t_proc, t_pack = ts(item["COLLECTED_AT"]), ts(item["PROCESSED_AT"]), ts(item["PACKAGED_AT"])
        events.append({"at": t_draw, "system": "EDC",
                       "note": f"Subject {int(num)} {vis}: PK draw by {item['COLLECTED_BY']}", "entities": [
            {"id": visit, "type": "VisitOccurrence", "visitName": vis, "forParticipant": rel(pid),
             "atStudySite": rel(ids.site(site)), "actualStartDate": t_draw, "visitStatus": "COMPLETED"},
            {"id": spec, "type": "Specimen", "name": f"PK draw, {vis}", "pne:kitId": kit,
             "collectedFrom": rel(pid), "performedInVisit": rel(visit), "specimenCollectedAt": t_draw,
             "pne:tubesCollected": item["TUBES"]},
            {"id": step + "collect", "type": "ActivityOccurrence", "name": "Sample collected",
             "pne:task": "specimen collection", "performedInVisit": rel(visit), "pne:specimen": rel(spec),
             "performedBy": rel(ids.person(org, item["COLLECTED_BY"])), "pne:tubesCollected": item["TUBES"]},
        ]})
        events.append({"at": t_proc, "system": "EDC", "note": f"Subject {int(num)} {vis}: sample processed",
                       "entities": [
            {"id": step + "process", "type": "ActivityOccurrence", "name": "Sample processed",
             "pne:task": "specimen processing", "performedInVisit": rel(visit), "pne:specimen": rel(spec),
             "performedBy": rel(ids.person(org, item["COLLECTED_BY"])), "prov:used": rel(dev),
             "pne:spin": item["SPIN"]}]})
        events.append({"at": t_pack, "system": "EDC", "note": f"Subject {int(num)} {vis}: sample packaged",
                       "entities": [
            {"id": step + "package", "type": "ActivityOccurrence", "name": "Sample packaged",
             "pne:task": "specimen packaging", "performedInVisit": rel(visit), "pne:specimen": rel(spec),
             "performedBy": rel(ids.person(org, item["PACKAGED_BY"]))}]})
    return events


def courier(src: pathlib.Path, ids: Ids) -> list[dict]:
    readings = defaultdict(list)
    for r in read_csv(src / "courier_temperature_log.csv"):
        readings[r["logger_id"]].append((ts(r["reading_at"]), float(r["temp_c"])))
    events = []
    for r in read_csv(src / "courier_shipments.csv"):
        ship = f"{URN}CustodyEvent:{ids.study}-{slug(r['airway_bill'])}"
        spec = ids.specimen(r["kit_id"])
        _, site, num, vis = r["kit_id"].split("-")
        events.append({"at": ts(r["delivered_at"]), "system": "Courier",
                       "note": f"{r['airway_bill']} delivered", "entities": [
            {"id": ship, "type": "CustodyEvent", "name": f"Cold-chain transit {r['airway_bill']}",
             "pne:task": "cold-chain transit", "pne:kitId": r["kit_id"], "pne:logger": r["logger_id"],
             "pne:pickedUpAt": ts(r["picked_up_at"]), "pne:deliveredAt": ts(r["delivered_at"]),
             "pne:custodyTrace": r["custody_trace"], "pne:specimen": rel(spec),
             "performedInVisit": rel(ids.visit(site, num, vis))},
            {"id": spec, "type": "Specimen", "hasCustodyEvent": rel(ship)}],
            "series": {"id": ship, "type": "CustodyEvent", "attr": "pne:temperatureC",
                       "points": readings[r["logger_id"]]}})
    return events


def lims(src: pathlib.Path, ids: Ids) -> list[dict]:
    events = []
    lab = "central-lab"
    for r in read_csv(src / "lims_analyst_certifications.csv"):
        events.append({"at": ts(r["valid_from"]), "system": "LIMS", "note": f"{r['analyst']} certified",
                       "entities": [
            {"id": ids.person(lab, r["analyst"]), "type": "Person", "name": r["analyst"], "pne:role": "Lab analyst"},
            {"id": f"{URN}Credential:{ids.study}-{slug(lab)}-{slug(r['analyst'])}-{slug(r['certification'])}",
             "type": "Credential", "name": r["certification"], "pne:kind": "analyst",
             "credentialOf": rel(ids.person(lab, r["analyst"])),
             "effectiveFrom": r["valid_from"], "effectiveTo": r["valid_to"]}]})
    for r in read_csv(src / "lims_results.csv"):
        site, num = parse_lims_subject(r["site"], r["subject"])
        visit = ids.visit(site, num, r["visit"])
        spec = ids.specimen(r["kit_id"])
        step = f"{URN}ActivityOccurrence:{ids.study}-{slug(r['kit_id'])}-"
        analyst = ids.person(lab, r["analyst"])
        reviewer = ids.person("sponsor", r["reviewed_by"])
        result = f"{URN}AssayResult:{ids.study}-{slug(r['accession'])}"
        events.append({"at": ts(r["received_at"]), "system": "LIMS",
                       "note": f"{r['accession']} received", "entities": [
            {"id": spec, "type": "Specimen", "specimenReceivedAt": ts(r["received_at"])},
            {"id": step + "receive", "type": "ActivityOccurrence", "name": "Lab received",
             "pne:task": "specimen receipt", "performedInVisit": rel(visit), "pne:specimen": rel(spec),
             "performedBy": rel(analyst), "pne:accession": r["accession"],
             "pne:receiptTempC": float(r["receipt_temp_c"]), "pne:vialsReceived": int(r["vials_received"])}]})
        events.append({"at": ts(r["analyzed_at"]), "system": "LIMS",
                       "note": f"{r['accession']} analyzed", "entities": [
            {"id": result, "type": "AssayResult", "name": r["test"], "pne:task": "assay",
             "yieldsResult": rel(spec), "performedInVisit": rel(visit), "performedBy": rel(analyst),
             "analysisMethod": r["method"], "analysisCompletedAt": ts(r["analyzed_at"])}]})
        events.append({"at": ts(r["reported_at"]), "system": "LIMS",
                       "note": f"{r['accession']} reported", "entities": [
            {"id": result, "type": "AssayResult", "pne:result": float(r["result"]), "pne:units": r["units"],
             "referenceRangeLow": float(r["ref_low"]), "referenceRangeHigh": float(r["ref_high"]),
             "reportGeneratedAt": ts(r["reported_at"])}]})
        events.append({"at": ts(r["reviewed_at"]), "system": "LIMS",
                       "note": f"{r['accession']} medically reviewed", "entities": [
            {"id": reviewer, "type": "Person", "name": r["reviewed_by"], "pne:role": "Medical reviewer"},
            {"id": step + "review", "type": "ActivityOccurrence", "name": "Lab results reviewed",
             "pne:task": "medical review", "performedInVisit": rel(visit), "reviewsResult": rel(result),
             "performedBy": rel(reviewer), "reviewStatus": r["review_status"]}]})
    return events


CONNECTORS = [protocol_authoring, ctms, etmf, lms, cmms, econsent, edc, courier, lims]


def read_sources(src: pathlib.Path) -> list[dict]:
    """All events from every connector, oldest first."""
    study = json.loads((src / "protocol_versions.json").read_text())["study"]
    ids = Ids(study)
    events = []
    for connector in CONNECTORS:
        events.extend(connector(src, ids))
    return sorted(events, key=lambda e: e["at"])
