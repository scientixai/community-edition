"""Walkthrough UI server.

Serves the static walkthrough page, the JSON-LD context the broker
dereferences, and a same-origin /api proxy to every service in the stack
so the browser needs no CORS configuration. Standard library only.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = pathlib.Path(__file__).resolve().parent
for _cand in (_HERE, _HERE / "lib", _HERE.parent / "pipeline" / "lib"):
    if (_cand / "pnehttp.py").is_file():
        sys.path.insert(0, str(_cand))
        break
import pnehttp
import ask_nl
import asof
import loader
import projections

PUBLIC = _HERE / "public"
EXAMPLE_SOURCES = next(
    (c for c in (_HERE / "examples" / "cvrm-118" / "sources",
                 _HERE.parent / "examples" / "cvrm-118" / "sources") if c.is_dir()),
    None,
)
SEED = PUBLIC / "seed"
ALLOWED_SEED_BATCHES = frozenset(
    {
        "enrollment-batch.json",
        "visit-batch-baseline.json",
        "visit-batch-week4.json",
    }
)

UPSTREAMS = {
    "broker": os.environ.get("PNE_BROKER_URL", "http://scorpio:9090"),
    "usdm": os.environ.get("PNE_USDM_URL", "http://usdm:8101"),
    "projection": os.environ.get("PNE_PROJECTION_URL", "http://projection:8102"),
    "subscriptions": os.environ.get("PNE_SUBSCRIPTIONS_URL", "http://subscriptions:8103"),
    "transform": os.environ.get("PNE_TRANSFORM_URL", "http://transform:8104"),
    "lake": os.environ.get("PNE_LAKE_URL", "http://lake:8105"),
    "adaptive": os.environ.get("PNE_ADAPTIVE_URL", "http://adaptive:8106"),
    "bridge": os.environ.get("PNE_BRIDGE_URL", "http://bridge:8107"),
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css",
    ".js": "text/javascript",
    ".jsonld": "application/ld+json",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class WebHandler(BaseHTTPRequestHandler):
    server_version = "pne-ce-web/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self._json(200, {"ok": True, "service": "web"})
        elif path.startswith("/api/"):
            self._proxy(method)
        elif path.startswith("/asof/"):
            self._asof(method, path, urllib.parse.parse_qs(parsed.query))
        elif path.startswith("/seed-with-provenance"):
            if method == "POST":
                self._seed_with_provenance()
            else:
                self._json(405, {"error": "method not allowed"})
        elif method == "GET":
            self._static(path)
        else:
            self._json(405, {"error": "method not allowed"})

    def _static(self, path: str):
        if path == "/":
            path = "/index.html"
        target = (PUBLIC / path.lstrip("/")).resolve()
        if not str(target).startswith(str(PUBLIC.resolve())) or not target.is_file():
            self._json(404, {"error": f"not found: {path}"})
            return
        data = target.read_bytes()
        self.send_response(200)
        ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _asof(self, method: str, path: str, query: dict):
        """As-of walkthrough: load the example source systems, then ask."""
        q = {k: v[0] for k, v in query.items() if v}
        try:
            if path == "/asof/load" and method == "POST":
                if EXAMPLE_SOURCES is None:
                    self._json(404, {"error": "example sources not found"})
                    return
                lines = []
                summary = loader.load(EXAMPLE_SOURCES, say=lines.append)
                self._json(200, {"summary": summary, "log": lines})
            elif path == "/asof/site" and method == "GET":
                self._json(200, asof.ask_site(q.get("site", ""), q.get("protocol") or None))
            elif path == "/asof/participant" and method == "GET":
                who = q.get("participant") or q.get("subject") or q.get("patient") or ""
                self._json(200, asof.ask_participant(who, q.get("site") or None, q.get("protocol") or None))
            elif path == "/asof/project" and method == "GET":
                who = q.get("participant") or q.get("subject") or q.get("patient") or ""
                self._json(200, projections.project_participant(
                    who, q.get("site") or None, q.get("protocol") or None, q.get("format", "")))
            elif path == "/asof/mode" and method == "GET":
                g = asof.Graph()
                self._json(200, dict(ask_nl.mode(), participants=len(g.of_type("Participant")),
                                     sites=len(g.of_type("StudySite"))))
            elif path == "/asof/ask" and method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                question = str(body.get("question", "")).strip()
                if not question:
                    self._json(400, {"error": "ask a question"})
                    return
                if "ndjson" in (self.headers.get("Accept") or ""):
                    self._ask_streaming(question, body)
                    return
                self._json(200, ask_nl.ask(question, body.get("history") or [], body.get("context") or {}))
            elif path == "/asof/history" and method == "GET":
                self._json(200, asof.entity_history(q.get("id", "")))
            else:
                self._json(404, {"error": f"no route {method} {path}"})
        except Exception as exc:  # report, do not drop the connection
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _ask_streaming(self, question: str, body: dict):
        """One JSON line per progress message, then the result; the page shows them live."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(obj):
            try:
                self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        asof.on_progress(lambda msg: emit({"progress": msg}))
        try:
            emit({"result": ask_nl.ask(question, body.get("history") or [], body.get("context") or {})})
        except Exception as exc:
            emit({"error": f"{type(exc).__name__}: {exc}"})
        finally:
            asof.on_progress(None)

    def _seed_with_provenance(self):
        """Load a seed batch with provenance through broker_upsert."""
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            self._json(400, {"error": "expected JSON body with 'batchFile' field"})
            return
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"error": "body must be valid JSON"})
            return
        
        batch_file = pathlib.Path(str(body.get("batchFile", "")).strip()).name
        if not batch_file:
            self._json(400, {"error": "batchFile is required"})
            return
        if batch_file not in ALLOWED_SEED_BATCHES:
            self._json(400, {"error": f"batchFile not allowed: {batch_file}"})
            return

        batch_path = SEED / batch_file
        if not batch_path.is_file():
            self._json(404, {"error": f"seed batch not found: {batch_file}"})
            return
        
        try:
            entities = json.loads(batch_path.read_text())
            if not isinstance(entities, list):
                self._json(400, {"error": "seed batch must be a JSON array"})
                return
            
            for ent in entities:
                ent.pop("@context", None)
            
            batch_name = batch_path.stem
            timestamp = datetime.now(timezone.utc).isoformat()
            
            pnehttp.broker_upsert(
                entities,
                provenance={
                    "source": f"seed-{batch_name}",
                    "loader": "demo-seed",
                    "time": timestamp,
                }
            )
            
            entity_ids = [e["id"] for e in entities if "id" in e]
            self._json(200, {
                "entityIds": entity_ids,
                "count": len(entity_ids),
                "batch": batch_name,
                "provenance": {
                    "dataSource": f"seed-{batch_name}",
                    "dataLoader": "demo-seed",
                    "loadedAt": timestamp,
                }
            })
        except Exception as err:
            self._json(500, {"error": f"seed load failed: {err}"})

    def _proxy(self, method: str):
        # /api/<service>/<rest> -> UPSTREAMS[service]/<rest>
        parts = self.path[len("/api/") :].split("/", 1)
        service = parts[0]
        rest = "/" + (parts[1] if len(parts) > 1 else "")
        base = UPSTREAMS.get(service)
        if base is None:
            self._json(404, {"error": f"unknown service {service}"})
            return
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = self.rfile.read(length)
        headers = {}
        for name in ("Content-Type", "Accept", "Link"):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        req = urllib.request.Request(
            base + rest, data=body, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=310) as resp:
                data = resp.read()
                self.send_response(resp.status)
                self.send_header(
                    "Content-Type", resp.headers.get("Content-Type", "application/json")
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as err:
            data = err.read()
            self.send_response(err.code)
            self.send_header(
                "Content-Type", err.headers.get("Content-Type", "application/json")
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (urllib.error.URLError, OSError) as err:
            self._json(502, {"error": f"{service} unreachable: {err}"})

    def _json(self, status: int, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[web] {fmt % args}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), WebHandler)
    print("[web] listening on :8080", flush=True)
    server.serve_forever()
