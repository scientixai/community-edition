"""Standards are views: one as-of answer, projected two ways.

Both projections are pure functions of the object asof.ask_participant
returns; neither reads anything else. The stored model stays the graph.

  to_sdtm(answer)  SDTM-shaped domains: DM, DS, SV, BE, PC
  to_fhir(answer)  a FHIR R4 collection Bundle: Patient, ResearchStudy,
                   ResearchSubject, Consent, Encounter, Specimen,
                   Observation, and a Provenance per fact

No DV domain: the engine reports possible issues for a person to review and
does not decide what is a protocol deviation.

Shaped after the standards for demonstration, not validated against
SDTMIG controlled terminology or FHIR profiles.
"""

from __future__ import annotations

import re
import uuid

SDTM_NS = uuid.UUID("6c6f2d1a-3c1b-4c55-9f5e-2b8d6a1c0e42")


def _num(visit: str) -> int | None:
    m = re.search(r"(\d+)", visit or "")
    return int(m.group(1)) if m else None


def _site_number(site: str) -> str:
    return re.sub(r"\D", "", site or "")


def _date(ts: str | None) -> str:
    return (ts or "")[:16]


BE_DECOD = {
    "specimen collection": "COLLECTED",
    "specimen processing": "CENTRIFUGED",
    "specimen packaging": "PACKAGED",
    "cold-chain transit": "SHIPPED",
    "specimen receipt": "RECEIVED",
}


def to_sdtm(a: dict) -> dict:
    """SDTM-shaped domains for one participant, as rows of ordered columns."""
    if "error" in a:
        return {"error": a["error"]}
    part = a["participant"]
    study = part.get("study") or ""
    siteid = _site_number(part["site"])
    usubjid = f"{study}-{siteid}-{part['number']}"
    base = {"STUDYID": study}
    first_consent = (a.get("consentHistory") or [{}])[0].get("observedAt")

    dm = [dict(base, DOMAIN="DM", USUBJID=usubjid, SUBJID=part["number"], SITEID=siteid,
               RFICDTC=_date(first_consent))]
    ds = [dict(base, DOMAIN="DS", USUBJID=usubjid, DSSEQ=i,
               DSTERM=f"INFORMED CONSENT OBTAINED, ICF V{c['version']}",
               DSDECOD="INFORMED CONSENT OBTAINED", DSCAT="PROTOCOL MILESTONE",
               DSSTDTC=_date(c["observedAt"]))
          for i, c in enumerate(a.get("consentHistory", []), 1)]
    sv, be, pc = [], [], []
    for v in a["visits"]:
        vnum = _num(v["visit"])
        sv.append(dict(base, DOMAIN="SV", USUBJID=usubjid, VISITNUM=vnum, VISIT=v["visit"],
                       SVSTDTC=_date(v["start"])))
        kit = next((s["recorded"].get("pne:kitId") for s in v["steps"] if s["recorded"].get("pne:kitId")), None)
        collected = next((s["at"] for s in v["steps"] if s["task"] == "specimen collection"), None)
        for s in v["steps"]:
            if s["task"] in BE_DECOD:
                term = s["step"] if s["task"] != "specimen collection" else \
                    f"Sample collected ({s['recorded'].get('pne:tubesCollected', '')})"
                be.append(dict(base, DOMAIN="BE", USUBJID=usubjid, BESEQ=len(be) + 1, BEREFID=kit,
                               BETERM=term, BEDECOD=BE_DECOD[s["task"]], VISITNUM=vnum, VISIT=v["visit"],
                               BESTDTC=_date(s["recorded"].get("pne:pickedUpAt") or s["at"]),
                               BEENDTC=_date(s["recorded"].get("pne:deliveredAt"))))
            if s["type"] == "AssayResult":
                r = s["recorded"]
                pc.append(dict(base, DOMAIN="PC", USUBJID=usubjid, PCSEQ=len(pc) + 1, PCREFID=kit,
                               PCTESTCD="PKCONC", PCTEST="PK concentration",
                               PCORRES=str(r.get("pne:result", "")), PCORRESU=r.get("pne:units"),
                               PCSTRESN=r.get("pne:result"), PCSTRESU=r.get("pne:units"),
                               PCSPEC="PLASMA", PCMETHOD=r.get("analysisMethod"),
                               VISITNUM=vnum, VISIT=v["visit"], PCDTC=_date(collected)))
    for i, row in enumerate(be, 1):
        row["BESEQ"] = i
    return {"usubjid": usubjid, "domains": {"DM": dm, "DS": ds, "SV": sv, "BE": be, "PC": pc}}


# ------------------------------------------------------------------ FHIR --

def _uuid(*parts) -> str:
    return f"urn:uuid:{uuid.uuid5(SDTM_NS, '|'.join(str(p) for p in parts))}"


def _prov(target: str, when: str | None, who: str | None, system: str | None, source_iri: str | None) -> dict:
    res = {"resourceType": "Provenance", "target": [{"reference": target}], "recorded": when,
           "agent": [{"who": {"display": who or system or "unknown"}}]}
    if system or source_iri:
        res["entity"] = [{"role": "source", "what": {"display": f"{system or ''} {source_iri or ''}".strip()}}]
    return res


def to_fhir(a: dict) -> dict:
    """A FHIR R4 collection Bundle for one participant, Provenance on every fact."""
    if "error" in a:
        return {"error": a["error"]}
    part = a["participant"]
    study = part.get("study") or ""
    usubjid = f"{study}-{_site_number(part['site'])}-{part['number']}"
    entries = []

    def add(res: dict, key: str) -> str:
        full = _uuid(res["resourceType"], key)
        entries.append({"fullUrl": full, "resource": res})
        return full

    patient = add({"resourceType": "Patient", "identifier": [{"system": f"urn:{study}:usubjid", "value": usubjid}]},
                  usubjid)
    rstudy = add({"resourceType": "ResearchStudy", "identifier": [{"value": study}], "status": "active",
                  "title": study}, study)
    add({"resourceType": "ResearchSubject", "status": "on-study", "study": {"reference": rstudy},
         "individual": {"reference": patient}, "identifier": [{"value": usubjid}]}, usubjid + "subject")

    history = a.get("consentHistory", [])
    for i, c in enumerate(history):
        consent = add({"resourceType": "Consent", "status": "active" if i == len(history) - 1 else "inactive",
                       "scope": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                                             "code": "research"}]},
                       "category": [{"text": "Informed consent to participate in research"}],
                       "patient": {"reference": patient}, "dateTime": c["observedAt"],
                       "policy": [{"uri": f"urn:{study}:icf:v{c['version']}"}],
                       "verification": [{"verified": True, "verifiedWith": {"display": c.get("witness")},
                                         "verificationDate": c["observedAt"]}]},
                      f"{usubjid}consent{c['version']}")
        add(_prov(consent, c["observedAt"], c.get("witness"), c.get("sourceSystem"), None),
            f"prov{consent}")

    for v in a["visits"]:
        enc = add({"resourceType": "Encounter", "status": "finished",
                   "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
                   "type": [{"text": v["visit"]}], "subject": {"reference": patient},
                   "period": {"start": v["start"]}}, f"{usubjid}{v['visit']}")
        steps = {s["task"]: s for s in v["steps"]}
        col, proc, rec = steps.get("specimen collection"), steps.get("specimen processing"), steps.get("specimen receipt")
        transit = steps.get("cold-chain transit")
        specimen = None
        if col:
            kit = transit["recorded"].get("pne:kitId") if transit else None
            res = {"resourceType": "Specimen", "identifier": [{"value": kit}] if kit else [],
                   "type": {"text": "Plasma (PK)"}, "subject": {"reference": patient},
                   "collection": {"collector": {"display": col.get("by")}, "collectedDateTime": col["at"]},
                   "note": [{"text": col["recorded"].get("pne:tubesCollected", "")}]}
            if proc:
                res["processing"] = [{"description": f"Centrifuged {proc['recorded'].get('pne:spin', '')}",
                                      "timeDateTime": proc["at"]}]
            if rec:
                res["receivedTime"] = rec["at"]
                res["container"] = [{"specimenQuantity": {"value": rec["recorded"].get("pne:vialsReceived"),
                                                          "unit": "vial"}}]
            specimen = add(res, f"{usubjid}{v['visit']}specimen")
            add(_prov(specimen, col["at"], col.get("by"), col.get("sourceSystem"), col.get("entity")),
                f"prov{specimen}")
        for s in v["steps"]:
            if s["type"] != "AssayResult":
                continue
            r = s["recorded"]
            obs = add({"resourceType": "Observation", "status": "final", "code": {"text": "PK concentration"},
                       "subject": {"reference": patient}, "encounter": {"reference": enc},
                       **({"specimen": {"reference": specimen}} if specimen else {}),
                       "effectiveDateTime": col["at"] if col else s["at"],
                       "issued": r.get("reportGeneratedAt"),
                       "valueQuantity": {"value": r.get("pne:result"), "unit": r.get("pne:units")},
                       "referenceRange": [{"low": {"value": r.get("referenceRangeLow"), "unit": r.get("pne:units")},
                                           "high": {"value": r.get("referenceRangeHigh"), "unit": r.get("pne:units")}}],
                       "method": {"text": r.get("analysisMethod")}}, f"{usubjid}{v['visit']}pk")
            add(_prov(obs, s["at"], s.get("by"), s.get("sourceSystem"), s.get("entity")), f"prov{obs}")

    return {"resourceType": "Bundle", "type": "collection", "identifier": {"value": usubjid},
            "entry": entries}


def project_participant(participant: str, site: str | None, protocol: str | None, fmt: str) -> dict:
    """SDTM and FHIR are views of the answer; JSON-LD is the broker's own records."""
    import asof
    fmt = (fmt or "").lower().replace("-", "")
    if fmt == "jsonld":
        return asof.as_jsonld(participant, site, protocol)
    return project(asof.ask_participant(participant, site, protocol), fmt)


def project(answer: dict, fmt: str) -> dict:
    fmt = (fmt or "").lower()
    if fmt == "sdtm":
        return to_sdtm(answer)
    if fmt == "fhir":
        return to_fhir(answer)
    return {"error": f"unknown format {fmt!r}; use sdtm, fhir or jsonld"}
