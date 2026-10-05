"""Lake storage and query service: DuckDB over the files in the lake.

The lake is the local filesystem replacement for S3. This service owns all
writes to the lake directory and provides query capabilities over the stored
files (Dataset-JSON, CSV, raw extracts) with zero infrastructure.

Write surface:
  POST /objects {"path", "content"}  write one file to the lake

Query surface:
  GET  /files          list lake contents
  GET  /file?path=...  fetch one file's content
  POST /sql {"sql"}    run a DuckDB query, rows come back as JSON
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import duckdb

LAKE_DIR = pathlib.Path(os.environ.get("PNE_LAKE_DIR", "/lake")).resolve()

SAMPLE_QUERIES = [
    {
        "label": "SDTM vital signs, wide",
        "sql": "SELECT USUBJID, VISIT, VSTESTCD, VSSTRESN, VSSTRESU FROM read_csv_auto('/lake/sdtm/vs.csv') ORDER BY USUBJID, VISIT, VSTESTCD",
    },
    {
        "label": "Mean systolic BP by visit",
        "sql": "SELECT VISIT, round(avg(VSSTRESN), 1) AS mean_sysbp FROM read_csv_auto('/lake/sdtm/vs.csv') WHERE VSTESTCD = 'SYSBP' GROUP BY VISIT ORDER BY min(VISITNUM)",
    },
    {
        "label": "Trial arms (Dataset-JSON)",
        "sql": "SELECT r->>0 AS studyid, r->>1 AS armcd, r->>2 AS arm FROM (SELECT unnest(rows) AS r FROM read_json_auto('/lake/datasetjson/ta.json'))",
    },
    {
        "label": "Demographics joined to vitals",
        "sql": "SELECT d.USUBJID, d.ARM, v.VSTESTCD, v.VSSTRESN FROM read_csv_auto('/lake/sdtm/dm.csv') d JOIN read_csv_auto('/lake/sdtm/vs.csv') v USING (USUBJID) ORDER BY d.USUBJID",
    },
]


class LakeHandler(BaseHTTPRequestHandler):
    server_version = "pne-ce-lake/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True, "service": "lake"})
        elif parsed.path == "/files":
            files = [
                {
                    "path": str(p.relative_to(LAKE_DIR)),
                    "bytes": p.stat().st_size,
                }
                for p in sorted(LAKE_DIR.rglob("*"))
                if p.is_file() and p.name != ".gitkeep"
            ]
            self._json(200, {"lake": str(LAKE_DIR), "files": files})
        elif parsed.path == "/file":
            rel = urllib.parse.parse_qs(parsed.query).get("path", [""])[0]
            target = (LAKE_DIR / rel).resolve()
            if not str(target).startswith(str(LAKE_DIR)) or not target.is_file():
                self._json(404, {"error": f"no such lake file: {rel}"})
                return
            data = target.read_bytes()
            self.send_response(200)
            ctype = "application/json" if target.suffix == ".json" else "text/plain"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path == "/samples":
            self._json(200, {"samples": SAMPLE_QUERIES})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except json.JSONDecodeError:
            self._json(400, {"error": "body must be JSON"})
            return
        
        if path == "/objects":
            self._write_object(body)
        elif path == "/sql":
            self._run_sql(body)
        else:
            self._json(404, {"error": "not found"})

    def _write_object(self, body):
        """Write one file to the lake. Path must be relative, no traversal.
        
        Optional provenance dict is stored as a JSON sidecar in .pne-provenance/:
          {"source": "origin", "loader": "service", "time": "ISO8601"}
        """
        rel_path = (body or {}).get("path", "").strip()
        content = body.get("content")
        provenance = body.get("provenance")
        
        if not rel_path:
            self._json(400, {"error": 'expected {"path": "...", "content": ...}'})
            return
        if content is None:
            self._json(400, {"error": "content is required"})
            return
        target = (LAKE_DIR / rel_path).resolve()
        if not str(target).startswith(str(LAKE_DIR) + os.sep):
            self._json(400, {"error": "path must be within the lake directory"})
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, (dict, list)):
                target.write_text(json.dumps(content, indent=2) + "\n")
            elif isinstance(content, str):
                target.write_text(content)
            else:
                self._json(400, {"error": "content must be string, dict, or list"})
                return
            
            if provenance and isinstance(provenance, dict):
                sidecar_dir = target.parent / ".pne-provenance"
                sidecar_dir.mkdir(parents=True, exist_ok=True)
                sidecar_path = sidecar_dir / f"{target.name}.json"
                sidecar_path.write_text(json.dumps(provenance, indent=2) + "\n")
            
            self._json(200, {
                "path": str(target.relative_to(LAKE_DIR)),
                "bytes": target.stat().st_size,
            })
        except Exception as err:
            self._json(500, {"error": f"write failed: {err}"})

    def _run_sql(self, body):
        """Execute a DuckDB SQL query over lake files."""
        sql = (body or {}).get("sql", "").strip()
        if not sql:
            self._json(400, {"error": 'expected {"sql": "SELECT ..."}'})
            return
        try:
            con = duckdb.connect(":memory:")
            cur = con.execute(sql)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(1000)
            self._json(
                200,
                {
                    "columns": columns,
                    "rows": [list(r) for r in rows],
                    "truncatedAt": 1000 if len(rows) == 1000 else None,
                },
            )
        except Exception as err:
            self._json(400, {"error": str(err)})

    def _json(self, status: int, payload):
        data = json.dumps(payload, default=str, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[lake] {fmt % args}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8105), LakeHandler)
    print(f"[lake] DuckDB {duckdb.__version__} over {LAKE_DIR}, listening on :8105", flush=True)
    server.serve_forever()
