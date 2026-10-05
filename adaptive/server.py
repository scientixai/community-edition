"""The adaptive layer: natural language in, NGSI-LD entity out.

This is deliberately the commodity version of an AI layer, and it is the
honest floor of the architecture: one model call (or an offline stub)
that constructs a cr-domain NGSI-LD entity from a clinical statement.

Engineering Floor Rule 7: capability ≠ authority. The adaptive service
can construct entities (capability) but cannot unilaterally write them
to the broker (authority). This edition's adaptive path proposes entities
and only writes when an explicit execute gate is enabled; the decision log
is a local append-only record.

Modes:
- anthropic: when ANTHROPIC_API_KEY is set, calls the Claude Messages API
  directly over HTTPS (standard library only, no SDK, so the container
  still builds offline).
- stub: no key needed; a deterministic parser that handles the demo
  statements (visit completion with vitals). Good for conference wifi.

POST /construct {"statement": "..."} -> proposal with entities (never writes)
POST /commit {"proposalId": "...", "entities": [...], "authority": {...}}
  -> upsert (gated by PNE_ADAPTIVE_EXECUTE env var)
"""

from __future__ import annotations

import datetime
import json
import os
import re
import secrets
import urllib.request
from pathlib import Path

import pnehttp
from pnehttp import prop, rel

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
# Demo default model — override with PNE_ADAPTIVE_MODEL (config, not a secret).
ANTHROPIC_MODEL = os.environ.get("PNE_ADAPTIVE_MODEL", "claude-opus-4-8")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
# Demo study id used in stub/id examples — override with PNE_STUDY_ID.
STUDY_ID = os.environ.get("PNE_STUDY_ID", "CARDIO-118")
ADAPTIVE_EXECUTE = os.environ.get("PNE_ADAPTIVE_EXECUTE", "").strip().lower() in ("1", "true", "yes")

DECISION_LOG_DIR = Path(os.environ.get("PNE_ADAPTIVE_DECISIONS", "/adaptive-decisions"))
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
DECISION_LOG_PATH = DECISION_LOG_DIR / "decisions.jsonl"

def _load_allowed_config() -> tuple[list[str], dict]:
    """Load type/attribute allow-lists from env JSON or adjacent config file."""
    raw = os.environ.get("PNE_ADAPTIVE_ALLOWED_JSON", "").strip()
    if raw:
        data = json.loads(raw)
    else:
        cfg_path = Path(
            os.environ.get(
                "PNE_ADAPTIVE_ALLOWED_PATH",
                str(Path(__file__).with_name("allowed.json")),
            )
        )
        data = json.loads(cfg_path.read_text())
    return list(data["allowedTypes"]), dict(data["attributeVocabulary"])


ALLOWED_TYPES, ATTRIBUTE_VOCABULARY = _load_allowed_config()

SYSTEM_PROMPT = """\
You convert clinical research statements into NGSI-LD entities using the
T.O.P. cr-domain vocabulary. Respond with a single JSON array of NGSI-LD
entities in normalized form: each entity has an id (urn:ngsi-ld:<Type>:<slug>
URN), a type from the allowed list, and attributes as
{"type": "Property", "value": ...} or {"type": "Relationship", "object": ...}
objects. Use only allowed entity types and the attribute vocabulary given.
Follow the id conventions in the examples. Dates are ISO 8601. Respond with
JSON only, no prose.
"""

ID_EXAMPLES = {
    "study": f"urn:ngsi-ld:Study:{STUDY_ID}",
    "site": "urn:ngsi-ld:StudySite:HOU-07",
    "participant": f"urn:ngsi-ld:Participant:{STUDY_ID.lower()}-hou-07-p2201",
    "visit": f"urn:ngsi-ld:VisitOccurrence:{STUDY_ID.lower()}-p2201-v4",
    "visitDefinition": f"urn:ngsi-ld:VisitDefinition:{STUDY_ID}-v4",
    "observation": f"urn:ngsi-ld:ClinicalObservation:{STUDY_ID.lower()}-p2201-v4-sysbp",
}


def call_anthropic(statement: str) -> list[dict]:
    """One Messages API call over plain HTTPS; returns parsed entities."""
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Allowed structure: "
                    + json.dumps(
                        {
                            "allowedTypes": ALLOWED_TYPES,
                            "attributeVocabulary": ATTRIBUTE_VOCABULARY,
                            "idExamples": ID_EXAMPLES,
                            "visitNumbers": {
                                "Screening": 1, "Baseline": 2,
                                "Week 4": 3, "Week 8": 4,
                            },
                        }
                    )
                    + f"\n\nStatement: {statement}"
                ),
            }
        ],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.load(resp)
    if body.get("stop_reason") == "refusal":
        raise RuntimeError("model declined the request (stop_reason=refusal)")
    text = next(
        (b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"),
        "",
    )
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    entities = json.loads(text)
    return entities if isinstance(entities, list) else [entities]


STUB_VISIT_RE = re.compile(
    r"[Pp]articipant\s+(?P<pat>P\d+).*?"
    r"(?P<visit>[Ss]creening|[Bb]aseline|[Ww]eek\s*\d+)\s+visit.*?"
    r"on\s+(?P<date>\w+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.DOTALL,
)
STUB_SYSBP_RE = re.compile(
    r"[Ss]ystolic(?:\s+blood)?\s+pressure\s+was\s+(?P<value>\d+)\s*(?P<unit>mmHg)?"
)
VISIT_NUMBERS = {"screening": 1, "baseline": 2, "week 4": 3, "week 8": 4}


def parse_date(raw: str) -> str:
    raw = re.sub(r"(\d)(st|nd|rd|th)", r"\1", raw.replace(",", ""))
    for fmt in ("%Y-%m-%d", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return raw


def stub_construct(statement: str) -> list[dict]:
    """Deterministic offline parser for the demo statement shapes."""
    match = STUB_VISIT_RE.search(statement)
    if not match:
        raise ValueError(
            "stub mode only understands statements like: 'Participant P2201 "
            "completed the Week 8 visit at the Houston site on June 1st, 2026. "
            "Seated systolic blood pressure was 121 mmHg.' Set "
            "ANTHROPIC_API_KEY for free-form statements."
        )
    pat = match.group("pat")
    visit_name = re.sub(r"\s+", " ", match.group("visit")).strip()
    vnum = VISIT_NUMBERS.get(visit_name.lower())
    date = parse_date(match.group("date"))
    slug = pat.lower()
    participant_urn = f"urn:ngsi-ld:Participant:{STUDY_ID.lower()}-hou-07-{slug}"
    visit_urn = f"urn:ngsi-ld:VisitOccurrence:{STUDY_ID.lower()}-{slug}-v{vnum}"

    entities = [
        {
            "id": visit_urn,
            "type": "VisitOccurrence",
            "forParticipant": rel(participant_urn),
            "atStudySite": rel("urn:ngsi-ld:StudySite:HOU-07"),
            "perVisitDefinition": rel(
                f"urn:ngsi-ld:VisitDefinition:{STUDY_ID}-v{vnum}"
            ),
            "visitType": prop("SCHEDULED"),
            "visitMode": prop("IN_PERSON"),
            "visitStatus": prop("COMPLETED"),
            "actualStartDate": prop(f"{date}T09:00:00Z"),
        }
    ]
    bp = STUB_SYSBP_RE.search(statement)
    if bp:
        entities.append(
            {
                "id": f"urn:ngsi-ld:ClinicalObservation:{STUDY_ID.lower()}-{slug}-v{vnum}-sysbp",
                "type": "ClinicalObservation",
                "forParticipant": rel(participant_urn),
                "atVisit": rel(visit_urn),
                "observationForSubject": rel(
                    f"urn:ngsi-ld:StudySubject:{STUDY_ID.lower()}-s{slug[1:]}"
                ),
                "parameterCode": prop("SYSBP"),
                "numericValue": prop(
                    int(bp.group("value")), observed_at=f"{date}T09:15:00Z"
                ),
                "unit": prop(bp.group("unit") or "mmHg"),
            }
        )
    return entities


def record_decision(proposal_id: str, decision: str, entities: list[dict], authority: dict):
    """Append-only decision log: every commit attempt (allow or deny)."""
    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "proposalId": proposal_id,
        "decision": decision,
        "authority": authority,
        "entityIds": [e.get("id") for e in entities if e.get("id")],
    }
    with DECISION_LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


class AdaptiveHandler(pnehttp.JsonHandler):
    ROUTES = {
        ("POST", "/construct"): "construct",
        ("POST", "/commit"): "commit",
        ("GET", "/mode"): "mode",
        ("GET", "/decisions"): "decisions",
    }

    def mode(self, _body):
        return 200, {
            "mode": "anthropic" if ANTHROPIC_API_KEY else "stub",
            "model": ANTHROPIC_MODEL if ANTHROPIC_API_KEY else None,
            "executeEnabled": ADAPTIVE_EXECUTE,
        }

    def construct(self, body):
        """Propose-only: builds entities, returns them with a proposal id. Never writes."""
        statement = (body or {}).get("statement", "").strip()
        if not statement:
            return 400, {"error": 'expected {"statement": "..."}'}
        
        write_arg = (body or {}).get("write")
        if write_arg is not None:
            return 400, {
                "error": (
                    "The 'write' parameter is no longer supported. /construct is "
                    "propose-only. Use POST /commit with explicit authority to execute."
                )
            }
        
        if ANTHROPIC_API_KEY:
            mode = "anthropic"
            entities = call_anthropic(statement)
        else:
            mode = "stub"
            try:
                entities = stub_construct(statement)
            except ValueError as err:
                return 422, {"mode": mode, "error": str(err)}
        
        proposal_id = secrets.token_urlsafe(16)
        return 200, {
            "mode": mode,
            "proposalId": proposal_id,
            "entities": entities,
        }

    def commit(self, body):
        """Execute: accepts proposal + entities, requires authority, gates on PNE_ADAPTIVE_EXECUTE."""
        proposal_id = (body or {}).get("proposalId", "").strip()
        entities = (body or {}).get("entities", [])
        authority = (body or {}).get("authority", {})
        
        if not proposal_id:
            return 400, {"error": 'expected {"proposalId": "...", "entities": [...], "authority": {...}}'}
        if not entities:
            return 400, {"error": "entities array is empty or missing"}
        if not isinstance(authority, dict) or not authority:
            return 400, {
                "error": (
                    "authority field is required and must contain explicit decision "
                    "fields (e.g. source, approver, reason)"
                )
            }
        
        if not ADAPTIVE_EXECUTE:
            record_decision(proposal_id, "denied", entities, authority)
            return 403, {
                "error": (
                    "Execution denied: PNE_ADAPTIVE_EXECUTE is not enabled. "
                    "Set PNE_ADAPTIVE_EXECUTE=true to allow adaptive writes."
                ),
                "proposalId": proposal_id,
                "executed": False,
                "recorded": True,
            }
        
        now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        authority_source = authority.get("source") or authority.get("approver") or "adaptive-commit"
        
        pnehttp.broker_upsert(
            entities,
            provenance={
                "source": authority_source,
                "loader": "adaptive-layer",
                "time": now
            }
        )
        record_decision(proposal_id, "allowed", entities, authority)
        
        return 200, {
            "proposalId": proposal_id,
            "executed": True,
            "recorded": True,
            "entityIds": [e.get("id") for e in entities if e.get("id")],
        }

    def decisions(self, _body):
        """Read the decision log."""
        if not DECISION_LOG_PATH.exists():
            return 200, {"decisions": []}
        
        decisions = []
        with DECISION_LOG_PATH.open("r") as f:
            for line in f:
                if line.strip():
                    decisions.append(json.loads(line))
        
        return 200, {"decisions": decisions}


if __name__ == "__main__":
    pnehttp.serve(AdaptiveHandler, 8106, startup=pnehttp.wait_for_broker)
