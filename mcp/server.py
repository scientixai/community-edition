#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys, urllib.error, urllib.parse, urllib.request

PROTOCOL_VERSION = "2024-11-05"
BROKER = os.environ.get("BROKER", "http://127.0.0.1:19091").rstrip("/")
SERVER_INFO = {"name": "pne-ce-broker", "version": "0.1.1"}
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


HANDLERS = {
    "broker_health": call_broker_health,
    "list_entities": call_list_entities,
    "get_entity": call_get_entity,
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


def main():
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
