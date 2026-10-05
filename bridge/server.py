"""Connector bridge: remote storage in and out of the lake, via rclone.

One optional service instead of hand-built Google Drive, OneDrive,
WebDAV, and S3 clients. rclone supports those four and dozens more
backends; this wrapper exposes the few operations the Community Edition
needs and keeps everything else out of scope:

  GET  /remotes                     configured remotes
  POST /remotes {name,type,params}  create one (non-interactive backends)
  DELETE-style: POST /remotes/delete {name}
  POST /check   {remote}            can we list it?
  POST /pull    {remote,path}       inbox flow: copy remote files in,
                                    ingest anything that looks like a
                                    USDM study definition
  POST /publish {remote,path,what}  publish flow: copy lake outputs out

Secrets note: rclone obscures credentials in its config file, which
lives in the bridge-config volume and never leaves this container.
OAuth backends (Google Drive, OneDrive) need a browser step that a
headless container cannot do; create those with
  docker compose --profile connectors exec bridge rclone config
or paste a token from 'rclone authorize' on your workstation. Keyed
backends (S3, WebDAV, SFTP) configure straight through the API.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LAKE_URL = os.environ.get("PNE_LAKE_URL", "http://lake:8105")
USDM_URL = os.environ.get("PNE_USDM_URL", "http://usdm:8101")

# Non-interactive backends the wizard offers. OAuth backends work too,
# but their tokens must come from 'rclone config'/'rclone authorize'.
WIZARD_BACKENDS = {
    "s3": ["provider", "access_key_id", "secret_access_key", "endpoint", "region"],
    "webdav": ["url", "vendor", "user", "pass"],
    "sftp": ["host", "user", "pass", "port"],
    "ftp": ["host", "user", "pass", "port"],
}


def rclone(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["rclone", "--config", os.environ.get("RCLONE_CONFIG", "/config/rclone.conf"),
         *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def rclone_or_error(*args: str, timeout: int = 120):
    proc = rclone(*args, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[-1000:] or f"rclone exited {proc.returncode}")
    return proc.stdout


def lake_write(rel_path: str, content) -> dict:
    """Write content to the lake via the lake service write API."""
    req = urllib.request.Request(
        f"{LAKE_URL}/objects",
        data=json.dumps({"path": rel_path, "content": content}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def lake_list_files() -> list[dict]:
    """List files in the lake via the lake service."""
    req = urllib.request.Request(f"{LAKE_URL}/files", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
        return data.get("files", [])


def ingest_usdm_files(directory: pathlib.Path) -> list[dict]:
    """POST every USDM-looking JSON file in the inbox to the usdm service."""
    results = []
    for path in sorted(directory.rglob("*.json")):
        try:
            body = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            results.append({"file": path.name, "status": "skipped: not JSON"})
            continue
        if not (isinstance(body, dict) and "study" in body):
            results.append({"file": path.name, "status": "skipped: no top-level 'study'"})
            continue
        req = urllib.request.Request(
            f"{USDM_URL}/load",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                loaded = json.load(resp)
            results.append({"file": path.name, "status": "ingested", "loaded": loaded.get("loaded")})
        except urllib.error.URLError as err:
            results.append({"file": path.name, "status": f"ingest failed: {err}"})
    return results


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "pne-ce-bridge/1.0"

    def _json(self, status: int, payload):
        data = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/health":
            probe = rclone("version", timeout=10)
            version = probe.stdout.splitlines()[0] if probe.returncode == 0 else None
            self._json(200, {"ok": probe.returncode == 0, "service": "bridge", "rclone": version})
        elif path == "/remotes":
            out = rclone("listremotes")
            remotes = [r.rstrip(":") for r in out.stdout.split() if r.strip()]
            self._json(200, {"remotes": remotes, "wizardBackends": WIZARD_BACKENDS})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._body()
        except (json.JSONDecodeError, ValueError):
            self._json(400, {"error": "body must be JSON"})
            return
        try:
            handler = {
                "/remotes": self.create_remote,
                "/remotes/delete": self.delete_remote,
                "/check": self.check,
                "/pull": self.pull,
                "/publish": self.publish,
            }.get(path)
            if handler is None:
                self._json(404, {"error": "not found"})
                return
            status, payload = handler(body)
            self._json(status, payload)
        except RuntimeError as err:
            self._json(502, {"error": str(err)})
        except subprocess.TimeoutExpired:
            self._json(504, {"error": "rclone timed out; check connectivity and credentials"})
        except Exception as err:
            self._json(500, {"error": str(err)})

    def create_remote(self, body):
        name = (body.get("name") or "").strip()
        backend = (body.get("type") or "").strip()
        params = body.get("params") or {}
        if not name.isidentifier():
            return 400, {"error": "remote name must be a simple identifier"}
        if backend not in WIZARD_BACKENDS:
            return 400, {
                "error": f"backend '{backend}' is not wizard-configurable; "
                "use 'docker compose --profile connectors exec bridge rclone config' "
                "for OAuth backends like drive or onedrive",
                "wizardBackends": list(WIZARD_BACKENDS),
            }
        args = ["config", "create", name, backend, "--non-interactive"]
        for key, value in params.items():
            if value not in (None, ""):
                args.append(f"{key}={value}")
        rclone_or_error(*args)
        return 200, {"created": name, "type": backend}

    def delete_remote(self, body):
        name = (body.get("name") or "").strip()
        if not name.isidentifier():
            return 400, {"error": "remote name must be a simple identifier"}
        rclone_or_error("config", "delete", name)
        return 200, {"deleted": name}

    def check(self, body):
        remote = (body.get("remote") or "").strip().rstrip(":")
        out = rclone("lsd", f"{remote}:", "--max-depth", "1", timeout=30)
        if out.returncode != 0:
            return 502, {"ok": False, "error": out.stderr.strip()[-500:]}
        return 200, {"ok": True, "directories": out.stdout.strip().splitlines()[:20]}

    def pull(self, body):
        remote = (body.get("remote") or "").strip().rstrip(":")
        remote_path = (body.get("path") or "").strip().strip("/")
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / remote
            target.mkdir(parents=True, exist_ok=True)
            source = f"{remote}:{remote_path}" if remote_path else f"{remote}:"
            rclone_or_error("copy", source, str(target), "--max-depth", "3")
            pulled = []
            for p in target.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(target)
                    lake_path = f"inbox/{remote}/{rel}"
                    lake_write(lake_path, p.read_text())
                    pulled.append(str(rel))
            ingested = ingest_usdm_files(target)
            return 200, {"pulled": pulled, "ingested": ingested, "inbox": f"inbox/{remote}"}

    def publish(self, body):
        remote = (body.get("remote") or "").strip().rstrip(":")
        remote_path = (body.get("path") or "pne-lake").strip().strip("/")
        what = body.get("what") or ["sdtm", "datasetjson"]
        
        all_files = lake_list_files()
        published = []
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_base = pathlib.Path(tmpdir)
            for sub in what:
                matching = [f for f in all_files if f["path"].startswith(f"{sub}/")]
                if not matching:
                    continue
                sub_dir = tmp_base / sub
                sub_dir.mkdir(parents=True, exist_ok=True)
                for file_info in matching:
                    file_path = file_info["path"]
                    req = urllib.request.Request(
                        f"{LAKE_URL}/file?path={urllib.parse.quote(file_path)}",
                        method="GET",
                    )
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        content = resp.read()
                    local_file = tmp_base / file_path
                    local_file.parent.mkdir(parents=True, exist_ok=True)
                    local_file.write_bytes(content)
                rclone_or_error("copy", str(sub_dir), f"{remote}:{remote_path}/{sub}")
                published.append(sub)
        
        if not published:
            return 400, {"error": "nothing to publish yet; run the pipeline first"}
        return 200, {"published": published, "destination": f"{remote}:{remote_path}"}

    def log_message(self, fmt, *args):
        print(f"[bridge] {fmt % args}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8107), BridgeHandler)
    print("[bridge] rclone connector bridge listening on :8107", flush=True)
    server.serve_forever()
