#!/usr/bin/env python3
from __future__ import annotations
import json, os, pathlib, sys, urllib.error, urllib.parse, urllib.request

PROTOCOL_VERSION = "2024-11-05"
BROKER = os.environ.get("BROKER", "http://127.0.0.1:9090").rstrip("/")

# The as-of engine reads the broker through the shared pipeline helpers.
os.environ.setdefault("PNE_BROKER_URL", BROKER)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "pipeline" / "lib"))
import asof  # noqa: E402
import ask_nl  # noqa: E402

INSTRUCTIONS = (
    "Answer questions about the study only from these tools. Every fact the "
    "tools return carries evidence: the entity IRI, the sourceSystem that "
    "asserted it, and observedAt (when it became true). Cite that evidence for "
    "each claim, and say so when the tools return nothing."
)
SERVER_INFO = {"name": "pne-ce-broker", "version": "0.1.2"}
ACCEPT_LD = "application/ld+json"

TOOLS = [
    {
        "name": "broker_health",
        "description": "GET {BROKER}/q/health",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_entities",
        "description": "GET {BROKER}/ngsi-ld/v1/entities?type=...&limit=20 (default type Study)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "NGSI-LD entity type", "default": "Study"}
            },
        },
    },
    {
        "name": "get_entity",
        "description": "GET {BROKER}/ngsi-ld/v1/entities/{id}",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "NGSI-LD entity id"}},
            "required": ["id"],
        },
    },
    {
        "name": "ask_participant_as_of",
        "description": (
            "What did we know about a participant (subject, patient) when a protocol version "
            "was implemented at a site? Returns one object: the implementation date, the participant's "
            "consent and the site team's training at that moment, and every visit with "
            "each step (collection, processing, packaging, cold-chain transit, lab "
            "receipt, assay, medical review) checked against the protocol, consent, "
            "delegation, training, credentials and calibration in effect when that step "
            "happened. possibleIssues lists every failed check, for a person to review. Every fact carries evidence "
            "(entity, sourceSystem, observedAt); cite it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "participant": {"type": "string", "description": "Participant number, e.g. 204"},
                "site": {"type": "string", "description": "Site number or name (optional; defaults to the participant's site)"},
                "protocol": {"type": "string", "description": "Protocol version (optional; defaults to the latest the site implemented)"},
            },
            "required": ["participant"],
        },
    },
    {
        "name": "visits_since_protocol",
        "description": (
            "Which participants and visits happened at a site after it implemented a "
            "protocol version, with the possible issues found on each visit. Cite the "
            "evidence returned."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Site number or name, e.g. 123"},
                "protocol": {"type": "string", "description": "Protocol version (optional; defaults to the latest the site implemented)"},
            },
            "required": ["site"],
        },
    },
    {
        "name": "project_participant",
        "description": next(t["description"] for t in ask_nl.TOOLS if t["name"] == "project_participant"),
        "inputSchema": next(t["input_schema"] for t in ask_nl.TOOLS if t["name"] == "project_participant"),
    },
    {
        "name": "entity_history",
        "description": (
            "Every recorded value of every attribute of one entity, each with "
            "observedAt, from the NGSI-LD temporal API. Use it to show how a fact "
            "changed over time and which source system said so."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "NGSI-LD entity IRI"}},
            "required": ["id"],
        },
    },
]


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def http_get(url, accept=None):
    headers = {}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


def maybe_json(body):
    try:
        return json.loads(body)
    except Exception:
        return body


def tool_result(text, is_error=False):
    out = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["isError"] = True
    return out


def call_broker_health(_args):
    status, body = http_get(BROKER + "/q/health")
    if status is None:
        return tool_result("broker_health failed: " + body, True)
    return tool_result(json.dumps({"status": status, "body": maybe_json(body)}, indent=2))


def call_list_entities(args):
    etype = args.get("type") or "Study"
    qs = urllib.parse.urlencode({"type": etype, "limit": 20})
    url = BROKER + "/ngsi-ld/v1/entities?" + qs
    status, body = http_get(url, ACCEPT_LD)
    if status is None:
        return tool_result("list_entities failed: " + body, True)
    return tool_result(json.dumps({"status": status, "type": etype, "body": maybe_json(body)}, indent=2))


def call_get_entity(args):
    eid = args.get("id")
    if not eid:
        return tool_result("get_entity requires argument id", True)
    url = BROKER + "/ngsi-ld/v1/entities/" + urllib.parse.quote(str(eid), safe="")
    status, body = http_get(url, ACCEPT_LD)
    if status is None:
        return tool_result("get_entity failed: " + body, True)
    return tool_result(json.dumps({"status": status, "id": eid, "body": maybe_json(body)}, indent=2))


def _json_result(obj):
    return tool_result(json.dumps(obj, indent=2), is_error=isinstance(obj, dict) and "error" in obj)


def call_ask_participant_as_of(args):
    who = args.get("participant") or args.get("subject") or args.get("patient") or ""
    return _json_result(asof.ask_participant(str(who), args.get("site") or None, args.get("protocol") or None))


def call_visits_since_protocol(args):
    return _json_result(asof.ask_site(str(args.get("site", "")), args.get("protocol") or None))


def call_entity_history(args):
    hist = asof.entity_history(str(args.get("id", "")))
    return _json_result(hist or {"error": f"no history for {args.get('id')!r}"})


def call_project_participant(args):
    return _json_result(ask_nl.run_tool("project_participant", args))


HANDLERS = {
    "broker_health": call_broker_health,
    "list_entities": call_list_entities,
    "get_entity": call_get_entity,
    "ask_participant_as_of": call_ask_participant_as_of,
    "visits_since_protocol": call_visits_since_protocol,
    "entity_history": call_entity_history,
    "project_participant": call_project_participant,
}


def rpc_error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(msg):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        mid = msg.get("id") if isinstance(msg, dict) else None
        return rpc_error(mid, -32600, "Invalid Request")
    method = msg.get("method")
    id_ = msg.get("id")
    params = msg.get("params") or {}
    note = "id" not in msg
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return None if note else {"jsonrpc": "2.0", "id": id_, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            return rpc_error(id_, -32602, "Unknown tool: " + str(name))
        try:
            result = fn(args if isinstance(args, dict) else {})
        except Exception as e:
            return {"jsonrpc": "2.0", "id": id_, "result": tool_result(str(e), True)}
        return {"jsonrpc": "2.0", "id": id_, "result": result}
    if note:
        return None
    return rpc_error(id_, -32601, "Method not found: " + str(method))


def write_msg(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve_http(port):
    """Streamable HTTP transport (JSON responses) for clients that connect by URL."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, payload=None):
            data = b"" if payload is None else json.dumps(payload).encode("utf-8")
            self.send_response(code)
            if payload is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path.rstrip("/") != "/mcp":
                return self._send(404, {"error": "POST /mcp"})
            try:
                msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            except json.JSONDecodeError as e:
                return self._send(400, rpc_error(None, -32700, "Parse error: " + str(e)))
            batch = msg if isinstance(msg, list) else [msg]
            out = [r for r in (handle(m) for m in batch) if r is not None]
            if not out:
                return self._send(202)
            self._send(200, out if isinstance(msg, list) else out[0])

        def do_GET(self):
            self._send(405, {"error": "this server answers POST /mcp with JSON"})

        def log_message(self, fmt, *a):
            log("http: " + fmt % a)

    log(f"pne-ce-broker MCP on http://127.0.0.1:{port}/mcp; BROKER=" + BROKER)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    if "--http" in sys.argv:
        i = sys.argv.index("--http")
        return serve_http(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 8765)
    log("pne-ce-broker MCP listening; BROKER=" + BROKER)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            write_msg(rpc_error(None, -32700, "Parse error: " + str(e)))
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            mid = msg.get("id") if isinstance(msg, dict) else None
            resp = rpc_error(mid, -32603, str(e))
        if resp is not None:
            write_msg(resp)


if __name__ == "__main__":
    main()
