"""Plain-language questions over the as-of engine.

With ANTHROPIC_API_KEY set, Claude answers: it can only reach the data
through the engine's tools (pipeline/lib/asof.py), and every tool call and
its full output are returned alongside the answer, so the reply can be
checked against the data that produced it.

Without a key, a deterministic parser handles the same question shapes
(a participant, a site, a protocol version, follow-ups like "show me 207") and
says so. Either way the answer is computed by the same engine from the
same broker.

Standard library only (HTTPS via urllib), like the adaptive service, so the
image builds offline.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

import asof
import projections

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("PNE_ASK_MODEL", "claude-opus-5-5")
MAX_ROUNDS = 8

SYSTEM = """You answer questions about clinical study CVRM-118 for a live audience.

"Participant", "subject" and "patient" mean the same person; always say "participant".

You can reach the study data only through the tools. Never answer from memory or assumption. If the tools return nothing or an error, say so plainly.

The tools return facts with evidence: the entity IRI, the sourceSystem that asserted the fact, and observedAt (when it became true). When you state a finding, name the source system and the date it came from, for example "eConsent, signed 2026-02-10".

A failed check is a possible issue for a person to review. Call it a possible issue; never call it a deviation, violation or error, and never decide whether it is one.

Lead with the answer in one or two sentences, then the specifics that support it. Name people and dates. When asked to compare participants, call the tool once per participant and say what differed: who did each step, what they were trained on at that moment, which consent was on file. Keep it short; the page shows the full evidence chain under your answer."""

TOOLS = [
    {
        "name": "ask_participant_as_of",
        "description": (
            "What did we know about a participant (subject, patient) when a protocol version was implemented at a site? "
            "Returns the implementation date, the participant's consent and the site team's training at "
            "that moment, and every visit with each step (collection, processing, packaging, "
            "cold-chain transit, lab receipt, assay, medical review) checked against the protocol, "
            "consent, delegation, training, credentials and calibration in effect when it happened. "
            "possibleIssues lists every failed check. Site defaults to the participant's site and protocol to "
            "the latest version that site implemented."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "participant": {"type": "string", "description": "Participant number, e.g. 204"},
                "site": {"type": "string", "description": "Site number, e.g. 123 (optional)"},
                "protocol": {"type": "string", "description": "Protocol version, e.g. 3.0 (optional)"},
            },
            "required": ["participant"],
        },
    },
    {
        "name": "visits_since_protocol",
        "description": (
            "Which participants and visits happened at a site after it implemented a protocol version, "
            "with the possible issues found on each visit. Protocol defaults to the latest version the "
            "site implemented."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site number, e.g. 123"},
                "protocol": {"type": "string", "description": "Protocol version, e.g. 3.0 (optional)"},
            },
            "required": ["site"],
        },
    },
    {
        "name": "project_participant",
        "description": (
            "The same as-of answer for a participant, projected to a standard: 'sdtm' returns "
            "SDTM-shaped domains (DM, DS, SV, BE, PC); 'fhir' "
            "returns a FHIR R4 Bundle with a Provenance resource per fact; 'jsonld' returns the "
            "broker's own NGSI-LD records for everything the answer touched as one JSON-LD graph, "
            "with every link an IRI. Use it when asked to see "
            "a participant as SDTM, FHIR, JSON-LD, linked data, a dataset, domains, or resources."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "participant": {"type": "string", "description": "Participant number, e.g. 204"},
                "format": {"type": "string", "enum": ["sdtm", "fhir", "jsonld"]},
                "site": {"type": "string", "description": "Site number (optional)"},
                "protocol": {"type": "string", "description": "Protocol version (optional)"},
            },
            "required": ["participant", "format"],
        },
    },
    {
        "name": "entity_history",
        "description": (
            "Every recorded value of every attribute of one entity (by IRI), each with observedAt "
            "and the sourceSystem that asserted it. Use it to show how a fact changed over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "NGSI-LD entity IRI"}},
            "required": ["id"],
        },
    },
]


def run_tool(name: str, args: dict) -> dict:
    if name == "ask_participant_as_of":
        who = args.get("participant") or args.get("subject") or args.get("patient") or ""
        return asof.ask_participant(str(who), args.get("site") or None,
                                args.get("protocol") or None)
    if name == "project_participant":
        who = args.get("participant") or args.get("subject") or args.get("patient") or ""
        fmt = str(args.get("format", "")).lower()
        out = projections.project_participant(str(who), args.get("site") or None, args.get("protocol") or None, fmt)
        return dict(out, format=fmt)
    if name == "visits_since_protocol":
        return asof.ask_site(str(args.get("site", "")), args.get("protocol") or None)
    if name == "entity_history":
        return asof.entity_history(str(args.get("id", ""))) or {"error": "no history for that IRI"}
    return {"error": f"unknown tool {name}"}


def mode() -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return {"claude": bool(key), "model": MODEL if key else None}


# --------------------------------------------------------------- Claude --

def _post(body: dict) -> dict:
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"].strip(),
        "anthropic-version": "2023-06-01",
        # Refusal fallback: a declined request is re-run on the model
        # Anthropic recommends for that refusal category.
        "anthropic-beta": "server-side-fallback-2026-07-01",
        "content-type": "application/json",
    }
    # Keys not scoped to a workspace must name the workspace on every request.
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    if workspace:
        headers["anthropic-workspace-id"] = workspace
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        raise RuntimeError(f"Anthropic API {err.code}: {detail[:500]}") from err


def ask_claude(question: str, history: list[dict]) -> dict:
    messages = [{"role": m["role"], "content": m["content"]} for m in history
                if m.get("role") in ("user", "assistant") and m.get("content")]
    messages.append({"role": "user", "content": question})
    calls = []
    for rounds in range(MAX_ROUNDS):
        asof.report("Claude is reading the question" if rounds == 0 else "Claude is reading what the broker returned")
        resp = _post({
            "model": MODEL, "max_tokens": 16000, "system": SYSTEM, "tools": TOOLS,
            "thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"},
            "fallbacks": "default", "messages": messages,
        })
        stop = resp.get("stop_reason")
        content = resp.get("content", [])
        if stop == "refusal":
            return {"answer": "The model declined this question.", "calls": calls}
        if stop != "tool_use":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
            if stop == "max_tokens":
                text += "\n\n(Answer cut off at the length limit.)"
            return {"answer": text or "(no answer)", "calls": calls}
        messages.append({"role": "assistant", "content": content})  # kept verbatim, thinking included
        results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            args = block.get("input") or {}
            asof.report(f"Claude asked for {block['name']}({', '.join(f'{k}={v}' for k, v in args.items() if v)})")
            try:
                out = run_tool(block["name"], args)
            except Exception as exc:  # report to the model, do not crash the turn
                out = {"error": f"{type(exc).__name__}: {exc}"}
            calls.append({"tool": block["name"], "input": args, "output": out})
            results.append({"type": "tool_result", "tool_use_id": block["id"],
                            "content": json.dumps(out), "is_error": "error" in out})
        messages.append({"role": "user", "content": results})
    return {"answer": "Stopped after too many tool rounds.", "calls": calls}


# ------------------------------------------------------- offline parser --

def _grab(pattern: str, text: str):
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else None


def ask_offline(question: str, context: dict) -> dict:
    """Understands: a participant (or subject, or patient) number, 'site N', 'protocol/v X.Y', and 'compare A and B'."""
    q = question.strip()
    asof.report("No API key: the offline parser is reading the question")
    site = _grab(r"\bsite\s*#?\s*(\d{1,3})\b", q)
    protocol = _grab(r"(?:\bprotocol\s*v?|\bv)(\d+\.\d+)\b", q)
    named = re.findall(r"\b(?:participants?|subjects?|patients?|pts?)\s*#?\s*(\d+)\b", q, re.I)
    numbers = list(dict.fromkeys(named + [n for n in re.findall(r"\b(\d{3})\b", q) if n != site]))
    site_q = bool(re.search(r"\b(who|which|what)\b.*\b(participants?|subjects?|patients?|visits?|came in)\b", q, re.I)) and not numbers
    calls = []
    fmt = _grab(r"\b(sdtm|fhir|json-?ld|linked data)\b", q)
    fmt = "jsonld" if fmt and fmt.lower() in ("json-ld", "jsonld", "linked data") else fmt
    if fmt and (numbers or context.get("participant")):
        for n in (numbers or [context["participant"]])[:4]:
            args = {"participant": n, "format": fmt.lower(), "site": site, "protocol": protocol or context.get("protocol")}
            calls.append({"tool": "project_participant", "input": args, "output": run_tool("project_participant", args)})
        return {"answer": summarize(calls), "calls": calls}
    if site_q or (site and not numbers):
        args = {"site": site or context.get("site"), "protocol": protocol or context.get("protocol")}
        if not args["site"]:
            return {"answer": "Which site? For example: who came in at Site 123 after protocol 3.0?", "calls": []}
        out = asof.ask_site(args["site"], args["protocol"])
        calls.append({"tool": "visits_since_protocol", "input": args, "output": out})
    else:
        if not numbers:
            return {"answer": "Name a participant or a site, for example: show me participant 204.", "calls": []}
        for n in numbers[:4]:
            args = {"participant": n, "site": site, "protocol": protocol or context.get("protocol")}
            calls.append({"tool": "ask_participant_as_of", "input": args,
                          "output": asof.ask_participant(n, site, args["protocol"])})
    return {"answer": summarize(calls), "calls": calls}


def summarize(calls: list[dict]) -> str:
    """A plain answer built from the tool outputs, nothing else."""
    lines = []
    for c in calls:
        out = c["output"]
        if "error" in out:
            lines.append(out["error"])
        elif c["tool"] == "visits_since_protocol":
            lines.append(f"{out['site']} implemented protocol {out['protocol']} on {out['implementedAtSite']}.")
            for v in out["visits"]:
                state = f"{len(v['possibleIssues'])} possible issue(s)" if v["possibleIssues"] else "no possible issues"
                lines.append(f"Participant {v['participant']}, {v['visit']} on {v['start'][:10]}: {state}.")
        elif c["tool"] == "project_participant":
            if out.get("domains"):
                counts = ", ".join(f"{d} {len(rows)}" for d, rows in out["domains"].items())
                lines.append(f"{out['usubjid']} as SDTM-shaped domains (rows): {counts}.")
            elif out.get("jsonld"):
                lines.append(f"{out['question']} As JSON-LD: {len(out['jsonld']['@graph'])} linked nodes, "
                             f"{len(out['termsUsed'])} terms, each resolving to a full IRI.")
            elif out.get("entry") is not None:
                lines.append(f"{out['identifier']['value']} as a FHIR R4 Bundle of {len(out['entry'])} resources.")
        elif c["tool"] == "ask_participant_as_of":
            lines.append(f"Participant {out['participant']['number']}: {out['summary']}")
            for t in out["possibleIssues"]:
                lines.append(f"  {t['step']} ({t['at'][:16].replace('T', ' ')}): {t['check']}; "
                             f"expected {t['expected']}, found {t['found']}.")
    return "\n".join(lines)


def ask(question: str, history: list[dict] | None = None, context: dict | None = None) -> dict:
    m = mode()
    if m["claude"]:
        try:
            out = ask_claude(question, history or [])
            out["mode"], out["model"] = "claude", m["model"]
            return out
        except Exception as exc:  # bad key, no network: answer anyway, and say why
            out = ask_offline(question, context or {})
            out["mode"], out["model"] = "offline", None
            out["fallbackReason"] = f"Claude unavailable ({exc}); the offline parser answered."
            return out
    out = ask_offline(question, context or {})
    out["mode"], out["model"] = "offline", None
    return out
