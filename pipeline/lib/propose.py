"""Graph-aware proposals: a statement in, NGSI-LD entities out, resolved first.

The model cannot see the graph, so on its own it invents identifiers: its
Participant 204 is not the Participant 204 the connectors loaded. Here Claude
looks the graph up before it proposes (find_participant, find_site,
participant_visits), and the server then checks the proposal rather than
trusting it:

  - every entity is existing (already in the broker) or new;
  - existing entities are referenced, never rewritten;
  - every relationship must point at an existing entity or at a new one in
    the same proposal, otherwise it is unresolved and the proposal is blocked;
  - a new participant or site whose number already exists in the graph is a
    duplicate and blocks the proposal.

Committing stamps every attribute with observedAt (when the fact became
true) and sourceSystem, as the connectors do, so the as-of engine reads the
new facts like any other.

Standard library only.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse

import asof
import ask_nl
import pnehttp

MAX_ROUNDS = 8
SOURCE_SYSTEM = "Adaptive layer"

SYSTEM = """You turn one clinical research statement into NGSI-LD entities for a knowledge graph.

The graph already holds participants, sites and visits loaded from source systems. Before you
propose anything, look up every participant and site the statement mentions:
- find_participant with the participant number (and the site, if the statement names one);
- find_site for any site the statement names;
- participant_visits for the participant, to see existing visits and the identifier conventions.

Rules:
- Refer to things that already exist by the IRI the tools returned. Never invent an IRI for a
  participant or site that exists. Do not repeat existing entities in your output; only link to them.
- If a lookup returns several candidates, or none, do not guess. Return no entities and explain in
  "notes" what is ambiguous or missing.
- New entities follow the conventions participant_visits returns.
- Use only the allowed types and attribute names given below.
- observedAt is when the facts became true (the date and time in the statement, ISO 8601, UTC "Z").
  If the statement gives only a date, use 09:00 that day.

Answer with one JSON object and nothing else:
{"observedAt": "...", "entities": [ ...normalized NGSI-LD entities: {"id", "type",
 attr: {"type": "Property", "value": ...} or {"type": "Relationship", "object": "<IRI>"}} ... ],
 "notes": "one or two sentences: what you resolved and what you created"}
"""

TOOLS = [
    {
        "name": "find_participant",
        "description": "Find participants in the graph by participant number (subject and patient mean the "
                       "same), optionally at one site. Returns every candidate with its IRI, site and study.",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "string", "description": "Participant number, e.g. 204"},
                "site": {"type": "string", "description": "Optional site number or name, e.g. 123"},
            },
            "required": ["number"],
        },
    },
    {
        "name": "find_site",
        "description": "Find a study site in the graph by number or name. Returns its IRI and name, or null.",
        "input_schema": {
            "type": "object",
            "properties": {"site": {"type": "string", "description": "Site number or name, e.g. 123"}},
            "required": ["site"],
        },
    },
    {
        "name": "participant_visits",
        "description": "The visits a participant already has, and the identifier conventions for new visits "
                       "and observations for that participant.",
        "input_schema": {
            "type": "object",
            "properties": {"participant": {"type": "string", "description": "Participant IRI from find_participant"}},
            "required": ["participant"],
        },
    },
]


# ----------------------------------------------------------------- tools --

def _site_info(g: asof.Graph, sid: str | None) -> dict | None:
    return {"iri": sid, "name": g.name(sid)} if sid else None


def _participant_info(g: asof.Graph, pid: str) -> dict:
    study = g.cur(pid, "forStudy")
    return {"iri": pid, "number": g.cur(pid, "screeningNumber"),
            "site": _site_info(g, g.cur(pid, "forStudySite")),
            "study": g.cur(study, "studyId") if study else None}


def _visit_label(g: asof.Graph, vid: str) -> str | None:
    return g.cur(vid, "visitName")


def conventions(pid: str) -> dict:
    """Identifier patterns for new things about one participant, from the participant's own IRI."""
    stem = pid.rsplit(":", 1)[-1]
    return {
        "visit": f"urn:ngsi-ld:VisitOccurrence:{stem}-v<NN>  (visitName \"V<NN>\", two digits, e.g. V05)",
        "observation": f"urn:ngsi-ld:ClinicalObservation:{stem}-v<NN>-<parametercode lowercase>",
        "parameterCodes": "CDISC VSTESTCD, e.g. SYSBP, DIABP, PULSE, TEMP, WEIGHT",
        "visitStatus": "COMPLETED",
        "position": "body position goes in an attribute named position (SITTING, STANDING, SUPINE)",
    }


def run_tool(g: asof.Graph, name: str, args: dict) -> dict:
    if name == "find_site":
        sid = asof.find_site(g, str(args.get("site", "")))
        return {"site": _site_info(g, sid)}
    if name == "find_participant":
        site_ref = args.get("site")
        sid = asof.find_site(g, str(site_ref)) if site_ref else None
        if site_ref and not sid:
            return {"candidates": [], "note": f"no site {site_ref!r} in the graph"}
        found = asof.find_participant(g, str(args.get("number", "")), sid)
        return {"candidates": [_participant_info(g, p) for p in found]}
    if name == "participant_visits":
        pid = str(args.get("participant", ""))
        if not g.get(pid):
            return {"error": f"no entity {pid!r} in the graph"}
        visits = [{"iri": v["id"], "visitName": _visit_label(g, v["id"]),
                   "actualStartDate": g.cur(v["id"], "actualStartDate"),
                   "visitStatus": g.cur(v["id"], "visitStatus")}
                  for v in g.pointing_at("VisitOccurrence", "forParticipant", pid)]
        visits.sort(key=lambda v: v["actualStartDate"] or "")
        return {"participant": pid, "visits": visits, "conventions": conventions(pid)}
    return {"error": f"unknown tool {name}"}


# ----------------------------------------------------------- the model --

def _parse(text: str) -> dict:
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("the model did not return a JSON object")
    out = json.loads(text[start:end + 1])
    if not isinstance(out.get("entities", []), list):
        raise ValueError("entities must be a list")
    return out


def construct(statement: str, allowed: dict, model: str) -> dict:
    """Claude resolves against the graph, then proposes; returns the raw proposal and the calls."""
    g = asof.Graph()
    structure = json.dumps({"allowedTypes": allowed["types"], "attributeVocabulary": allowed["vocabulary"]})
    messages = [{"role": "user", "content": f"Allowed structure: {structure}\n\nStatement: {statement}"}]
    calls = []
    asof.report(f"Proposing from: {statement}")
    for rounds in range(MAX_ROUNDS):
        asof.report("Claude is reading the statement" if rounds == 0 else "Claude is reading what the graph returned")
        resp = ask_nl._post({
            "model": model, "max_tokens": 16000, "system": SYSTEM, "tools": TOOLS,
            "thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"},
            "fallbacks": "default", "messages": messages,
        })
        stop = resp.get("stop_reason")
        content = resp.get("content", [])
        if stop == "refusal":
            raise RuntimeError("the model declined the request (stop_reason=refusal)")
        if stop != "tool_use":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            return dict(_parse(text), calls=calls)
        messages.append({"role": "assistant", "content": content})  # verbatim, thinking included
        results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            args = block.get("input") or {}
            asof.report(f"Claude asked the graph: {block['name']}({', '.join(str(v) for v in args.values())})")
            try:
                out = run_tool(g, block["name"], args)
            except Exception as exc:  # report to the model, do not crash the turn
                out = {"error": f"{type(exc).__name__}: {exc}"}
            calls.append({"tool": block["name"], "input": args, "output": out})
            results.append({"type": "tool_result", "tool_use_id": block["id"],
                            "content": json.dumps(out), "is_error": "error" in out})
        messages.append({"role": "user", "content": results})
    raise RuntimeError("stopped after too many tool rounds")


# ------------------------------------------------------------ the check --

def _label(g: asof.Graph, ent: dict) -> str:
    t = ent.get("type")
    val = lambda a: (ent.get(a) or {}).get("value")  # noqa: E731
    if t == "Participant":
        return f"Participant {val('screeningNumber') or g.cur(ent['id'], 'screeningNumber') or ''}".strip()
    if t == "StudySite":
        return g.name(ent["id"]) or "Study site"
    if t == "VisitOccurrence":
        return f"Visit {val('visitName') or g.cur(ent['id'], 'visitName') or ''}".strip()
    if t == "ClinicalObservation":
        v, u = val("numericValue"), val("unit")
        return f"{val('parameterCode') or 'Observation'} {'' if v is None else v} {u or ''}".strip()
    return t or "Entity"


def check(entities: list[dict], allowed: dict) -> dict:
    """Classify every entity and link against the graph as it stands now."""
    g = asof.Graph()
    proposed = {e.get("id"): e for e in entities if isinstance(e, dict) and e.get("id")}
    rows, links, reasons, write = [], [], [], []
    for eid, ent in proposed.items():
        etype = ent.get("type")
        exists = bool(g.get(eid))
        row = {"id": eid, "type": etype, "label": _label(g, ent),
               "status": "existing" if exists else "new"}
        if exists:
            pass  # referenced, never rewritten, whatever its type
        elif etype not in allowed["types"]:
            row["status"] = "rejected"
            reasons.append(f"{eid}: type {etype!r} is not allowed")
        else:
            bad = [a for a in ent if a not in ("id", "type", "@context") and a not in allowed["vocabulary"].get(etype, [])]
            if bad:  # outside the vocabulary: left out of the write, and said so
                row["dropped"] = bad
                ent = {k: v for k, v in ent.items() if k not in bad}
            number = (ent.get("screeningNumber") or {}).get("value")
            if etype == "Participant" and number is not None:
                site = (ent.get("forStudySite") or {}).get("object")
                dupes = asof.find_participant(g, str(number), site if site and g.get(site) else None)
                if dupes:
                    row["status"] = "duplicate"
                    row["existing"] = dupes
                    reasons.append(f"{eid}: Participant {number} already exists as {', '.join(dupes)}")
        if row["status"] == "new":
            write.append(ent)
        elif row["status"] == "existing":
            row["note"] = "already in the graph: referenced, not rewritten"
        rows.append(row)
        for attr, val in ent.items():
            if not (isinstance(val, dict) and val.get("type") == "Relationship"):
                continue
            target = val.get("object")
            if target in proposed and target != eid:
                status = "existing" if g.get(target) else "new"
            elif g.get(target):
                status = "existing"
            else:
                status = "unresolved"
                if row["status"] == "new":
                    reasons.append(f"{eid}.{attr} points at {target}, which is not in the graph")
            to_label = _label(g, proposed[target]) if target in proposed else _label(g, g.get(target) or {"type": None})
            links.append({"from": eid, "attribute": attr, "to": target, "status": status,
                          "toLabel": to_label if g.get(target) or target in proposed else None})
    if not write and not reasons:
        reasons.append("nothing new to write")
    for r in rows:
        asof.report(f"Check: {r['label']} {r['id']} -> {r['status']}")
    unresolved = [link for link in links if link["status"] == "unresolved"]
    asof.report(f"Check: {len(links) - len(unresolved)} of {len(links)} links resolve"
                + ("; blocked: " + "; ".join(reasons) if reasons else "; ready to commit"))
    return {"resolution": rows, "links": links, "write": write,
            "blocked": bool(reasons), "reasons": reasons}


# ------------------------------------------------------------ the write --

def stamp(entities: list[dict], observed_at: str) -> list[dict]:
    """observedAt and sourceSystem on every attribute, as the connectors write them."""
    out = []
    for ent in entities:
        new = {"id": ent["id"], "type": ent["type"]}
        for attr, val in ent.items():
            if attr in ("id", "type", "@context"):
                continue
            if isinstance(val, dict) and val.get("type") == "Relationship":
                new[attr] = {"type": "Relationship", "object": val.get("object"), "observedAt": observed_at}
            else:
                value = val.get("value") if isinstance(val, dict) and "value" in val else val
                new[attr] = pnehttp.prop(value, observed_at)
        new["sourceSystem"] = pnehttp.prop(SOURCE_SYSTEM, observed_at)
        out.append(new)
    return out


def wait_for_history(ids: list[str], timeout: float = 20.0) -> bool:
    """History is recorded asynchronously; wait so the next question sees the new facts with their source."""
    deadline = time.time() + timeout
    pending = list(ids)
    while pending and time.time() < deadline:
        eid = pending[0]
        status, body = pnehttp.request(
            "GET", f"{asof.NGSI}/temporal/entities/{urllib.parse.quote(eid, safe='')}?lastN=1",
            headers=asof.HEADERS)
        if status == 200 and body and body.get("sourceSystem"):
            pending.pop(0)
        else:
            time.sleep(0.5)
    return not pending
