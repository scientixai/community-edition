"""USDM study definition ingest.

POST /load takes a USDM-style study definition (or falls back to the
bundled seed study) and loads it into the NGSI-LD broker as cr-domain
entities: Study, Sponsor, Arm, EligibilityCriterion, Endpoint,
VisitDefinition, StudySite. The mapping follows the T.O.P. usdm-to-cr
crosswalk (USDM design constructs to their cr-core counterparts).
"""

from __future__ import annotations

import datetime
import json
import pathlib

import pnehttp
from pnehttp import prop, rel

SEED = pathlib.Path(__file__).parent / "usdm-study.json"


def urn(kind: str, suffix: str) -> str:
    return f"urn:ngsi-ld:{kind}:{suffix}"


def multi_rel(targets: list[str]) -> list[dict]:
    """A multi-instance NGSI-LD relationship (one instance per target)."""
    return [
        {"type": "Relationship", "object": t, "datasetId": f"{t}:rel"}
        for t in targets
    ]


def usdm_to_entities(usdm: dict) -> list[dict]:
    study = usdm["study"]
    study_id = study["id"]
    version = study["versions"][0]
    design = version["studyDesigns"][0]
    study_urn = urn("Study", study_id)

    entities: list[dict] = []

    arm_urns, criterion_urns, endpoint_urns, visit_urns = [], [], [], []

    sponsor = next(
        (o for o in version.get("organizations", []) if o.get("type") == "SPONSOR"),
        None,
    )
    sponsor_urn = None
    if sponsor:
        sponsor_urn = urn("Sponsor", sponsor["id"])
        entities.append(
            {"id": sponsor_urn, "type": "Sponsor", "name": prop(sponsor["name"])}
        )

    for arm in design.get("arms", []):
        arm_urn = urn("Arm", f"{study_id}-{arm['id']}")
        arm_urns.append(arm_urn)
        entities.append(
            {
                "id": arm_urn,
                "type": "Arm",
                "armCode": prop(arm["name"]),
                "armName": prop(arm.get("label", arm["name"])),
                "forStudy": rel(study_urn),
            }
        )

    for crit in design.get("population", {}).get("criteria", []):
        crit_urn = urn("EligibilityCriterion", f"{study_id}-{crit['id']}")
        criterion_urns.append(crit_urn)
        entities.append(
            {
                "id": crit_urn,
                "type": "EligibilityCriterion",
                "criterionType": prop(crit.get("category", "INCLUSION")),
                "criterionText": prop(crit["text"]),
                "forStudy": rel(study_urn),
            }
        )

    for objective in design.get("objectives", []):
        for endpoint in objective.get("endpoints", []):
            ep_urn = urn("Endpoint", f"{study_id}-{endpoint['id']}")
            endpoint_urns.append(ep_urn)
            entities.append(
                {
                    "id": ep_urn,
                    "type": "Endpoint",
                    "endpointType": prop(endpoint.get("level", "PRIMARY")),
                    "endpointText": prop(endpoint["text"]),
                    "forStudy": rel(study_urn),
                }
            )

    for enc in design.get("encounters", []):
        v_urn = urn("VisitDefinition", f"{study_id}-v{enc['visitNumber']}")
        visit_urns.append(v_urn)
        entities.append(
            {
                "id": v_urn,
                "type": "VisitDefinition",
                "visitNumber": prop(enc["visitNumber"]),
                "visitName": prop(enc["name"]),
                "plannedStudyDay": prop(enc["plannedDay"]),
                "forStudy": rel(study_urn),
            }
        )

    for site in design.get("studySites", []):
        entities.append(
            {
                "id": urn("StudySite", site["id"]),
                "type": "StudySite",
                "name": prop(site["name"]),
                "forStudy": rel(study_urn),
            }
        )

    title = next(iter(version.get("titles", [])), {}).get("text", study_id)
    study_entity = {
        "id": study_urn,
        "type": "Study",
        "studyId": prop(study_id),
        "studyTitle": prop(title),
        "studyPhase": prop(version.get("studyPhase", "")),
        "hasArm": multi_rel(arm_urns),
        "hasEligibilityCriterion": multi_rel(criterion_urns),
        "hasEndpoint": multi_rel(endpoint_urns),
        "hasVisitDefinition": multi_rel(visit_urns),
    }
    if sponsor_urn:
        study_entity["sponsoredBy"] = rel(sponsor_urn)
    entities.append(study_entity)
    return entities


class UsdmHandler(pnehttp.JsonHandler):
    ROUTES = {("POST", "/load"): "load", ("GET", "/seed"): "seed"}

    def seed(self, _body):
        return 200, json.loads(SEED.read_text())

    def load(self, body):
        usdm = body if body else json.loads(SEED.read_text())
        entities = usdm_to_entities(usdm)
        
        source_name = "usdm-study.json" if body else "usdm-study.json (seed)"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        
        status = pnehttp.broker_upsert(
            entities,
            provenance={
                "source": source_name,
                "loader": "usdm-load",
                "time": now
            }
        )
        
        return 200, {
            "loaded": len(entities),
            "brokerStatus": status,
            "entityIds": [e["id"] for e in entities],
        }


if __name__ == "__main__":
    pnehttp.serve(UsdmHandler, 8101, startup=pnehttp.wait_for_broker)
