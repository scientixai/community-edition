"""Tiny shared HTTP helpers for the pipeline services.

Standard library only, deliberately: every pipeline container builds
offline from python:3.12-slim with no package installs, so the stack
comes up on machines with no network access at all.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BROKER_URL = os.environ.get("PNE_BROKER_URL", "http://localhost:9090")
CONTEXT_URL = os.environ.get(
    "PNE_CONTEXT_URL", "http://localhost:8080/context/pne-context.jsonld"
)

LINK_HEADER = (
    f'<{CONTEXT_URL}>; rel="http://www.w3.org/ns/json-ld#context"; '
    'type="application/ld+json"'
)


def request(
    method: str,
    url: str,
    body: dict | list | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
):
    """One-shot JSON HTTP request. Returns (status, parsed-body-or-None)."""
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            parsed = json.loads(raw) if raw.strip() else None
            return resp.status, parsed
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            parsed = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode("utf-8", "replace")}
        return err.code, parsed


def broker_get_entities(entity_type: str, query: str | None = None, limit: int = 1000):
    """Read entities of one type from the broker, compacted with our context."""
    url = f"{BROKER_URL}/ngsi-ld/v1/entities?type={entity_type}&limit={limit}"
    if query:
        url += f"&q={urllib.parse.quote(query, safe='')}"
    status, body = request(
        "GET", url, headers={"Accept": "application/json", "Link": LINK_HEADER}
    )
    if status != 200:
        raise RuntimeError(f"broker GET {entity_type} failed: {status} {body}")
    return body or []


def broker_upsert(entities: list[dict], provenance: dict | None = None):
    """Batch-upsert NGSI-LD entities; @context rides in the payload.
    
    Optional provenance dict stamps source/loader/time on all entities:
      {"source": "origin-identifier", "loader": "service-name", "time": "ISO8601"}
    
    If provenance is provided, dataSource/dataLoader/loadedAt Properties are
    attached to every entity before upsert.
    """
    enriched = []
    for ent in entities:
        ent_copy = {"@context": CONTEXT_URL, **ent}
        if provenance:
            ent_copy["dataSource"] = prop(provenance.get("source", ""))
            ent_copy["dataLoader"] = prop(provenance.get("loader", ""))
            ent_copy["loadedAt"] = prop(provenance.get("time", ""))
        enriched.append(ent_copy)
    
    status, body = request(
        "POST",
        f"{BROKER_URL}/ngsi-ld/v1/entityOperations/upsert?options=update",
        body=enriched,
        headers={"Content-Type": "application/ld+json"},
    )
    if status not in (200, 201, 204):
        raise RuntimeError(f"broker upsert failed: {status} {body}")
    return status


def wait_for_broker(max_wait: float = 300.0) -> bool:
    """Block until the broker health endpoint answers."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            status, _ = request("GET", f"{BROKER_URL}/q/health", timeout=5)
            if status == 200:
                return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(2)
    return False


def prop(value, observed_at: str | None = None) -> dict:
    p = {"type": "Property", "value": value}
    if observed_at:
        p["observedAt"] = observed_at
    return p


def rel(target: str) -> dict:
    return {"type": "Relationship", "object": target}


class JsonHandler(BaseHTTPRequestHandler):
    """Route table driven JSON request handler.

    Subclasses define ROUTES = {("POST", "/load"): method_name, ...} and
    methods receiving (self, body) and returning (status, jsonable).
    """

    ROUTES: dict = {}
    server_version = "pne-ce/1.0"

    def _dispatch(self, method: str):
        handler_name = self.ROUTES.get((method, self.path.split("?")[0]))
        if handler_name is None:
            self._send(404, {"error": f"no route {method} {self.path}"})
            return
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError:
                self._send(400, {"error": "request body is not valid JSON"})
                return
        try:
            status, result = getattr(self, handler_name)(body)
        except Exception as err:  # surface the failure to the caller
            self.log_message("handler error: %r", err)
            status, result = 500, {"error": str(err)}
        self._send(status, result)

    def _send(self, status: int, payload):
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send(200, {"ok": True, "service": type(self).__name__})
            return
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def log_message(self, fmt, *args):
        print(f"[{type(self).__name__}] {fmt % args}", flush=True)


def serve(handler_cls, port: int, startup=None):
    """Run the HTTP server; optionally run a startup callable in a thread."""
    if startup is not None:
        threading.Thread(target=startup, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), handler_cls)
    print(f"[{handler_cls.__name__}] listening on :{port}", flush=True)
    server.serve_forever()
