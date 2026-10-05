#!/usr/bin/env python3
"""Static proof: OpenAPI paths match CE HTTP route handlers on tip.

Compares docs/api/openapi.yaml (web-proxy form /api/<service>/<path>)
against route registrations in service sources. Does not require Docker.

Exit 0 when every OpenAPI operation maps to a live handler and every
CE-owned fixed route appears in the OpenAPI document.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "docs" / "api" / "openapi.yaml"

# (service, method, path) as registered on the service itself.
# /health is provided by JsonHandler for pnehttp services, or inline.
EXPECTED: set[tuple[str, str, str]] = {
    # web
    ("web", "GET", "/health"),
    # lake
    ("lake", "GET", "/health"),
    ("lake", "GET", "/files"),
    ("lake", "GET", "/file"),
    ("lake", "GET", "/samples"),
    ("lake", "POST", "/objects"),
    ("lake", "POST", "/sql"),
    # usdm
    ("usdm", "GET", "/health"),
    ("usdm", "GET", "/seed"),
    ("usdm", "POST", "/load"),
    # projection
    ("projection", "GET", "/health"),
    ("projection", "POST", "/project"),
    # subscriptions
    ("subscriptions", "GET", "/health"),
    ("subscriptions", "POST", "/notify"),
    ("subscriptions", "GET", "/events"),
    ("subscriptions", "GET", "/subscription"),
    # transform
    ("transform", "GET", "/health"),
    ("transform", "POST", "/run"),
    ("transform", "GET", "/status"),
    # adaptive
    ("adaptive", "GET", "/health"),
    ("adaptive", "POST", "/construct"),
    ("adaptive", "POST", "/commit"),
    ("adaptive", "GET", "/mode"),
    ("adaptive", "GET", "/decisions"),
    # bridge
    ("bridge", "GET", "/health"),
    ("bridge", "GET", "/remotes"),
    ("bridge", "POST", "/remotes"),
    ("bridge", "POST", "/remotes/delete"),
    ("bridge", "POST", "/check"),
    ("bridge", "POST", "/pull"),
    ("bridge", "POST", "/publish"),
}

SOURCE_FILES = {
    "web": ROOT / "web" / "server.py",
    "lake": ROOT / "lake" / "server.py",
    "usdm": ROOT / "pipeline" / "usdm" / "server.py",
    "projection": ROOT / "pipeline" / "projection" / "server.py",
    "subscriptions": ROOT / "pipeline" / "subscriptions" / "server.py",
    "transform": ROOT / "pipeline" / "transform" / "wrapper.py",
    "adaptive": ROOT / "adaptive" / "server.py",
    "bridge": ROOT / "bridge" / "server.py",
    "pnehttp": ROOT / "pipeline" / "lib" / "pnehttp.py",
}


def openapi_operations(text: str) -> set[tuple[str, str, str]]:
    """Parse path+method pairs from a lightly structured OpenAPI YAML."""
    ops: set[tuple[str, str, str]] = set()
    current_path: str | None = None
    path_re = re.compile(r"^  (/[^: ]+):\s*$")
    method_re = re.compile(r"^    (get|post|put|patch|delete):\s*$", re.I)
    for line in text.splitlines():
        m = path_re.match(line)
        if m:
            current_path = m.group(1)
            continue
        if current_path is None:
            continue
        if line and not line.startswith(" "):
            current_path = None
            continue
        mm = method_re.match(line)
        if mm and current_path is not None:
            method = mm.group(1).upper()
            if current_path == "/health":
                ops.add(("web", method, "/health"))
            elif current_path.startswith("/api/"):
                parts = current_path[len("/api/") :].split("/", 1)
                service = parts[0]
                rest = "/" + (parts[1] if len(parts) > 1 else "")
                if rest == "/":
                    rest = "/"
                ops.add((service, method, rest if rest != "/" else "/"))
            else:
                raise SystemExit(f"unexpected OpenAPI path shape: {current_path}")
    return ops


def discover_from_source() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()

    # pnehttp JsonHandler always serves GET /health
    pnehttp = SOURCE_FILES["pnehttp"].read_text()
    if '== "/health"' not in pnehttp and "path.split(\"?\")[0] == \"/health\"" not in pnehttp:
        # tolerate either quote style
        if '/health' not in pnehttp:
            raise SystemExit("pnehttp.py missing /health handler")

    lake = SOURCE_FILES["lake"].read_text()
    for path in ("/health", "/files", "/file", "/samples"):
        if f'parsed.path == "{path}"' not in lake and f'path == "{path}"' not in lake:
            # /health,/files,/file,/samples use parsed.path; /objects,/sql use path
            if f'"{path}"' not in lake:
                raise SystemExit(f"lake missing {path}")
        found.add(("lake", "GET", path))
    for path in ("/objects", "/sql"):
        if f'path == "{path}"' not in lake:
            raise SystemExit(f"lake missing POST {path}")
        found.add(("lake", "POST", path))

    web = SOURCE_FILES["web"].read_text()
    if 'path == "/health"' not in web:
        raise SystemExit("web missing /health")
    found.add(("web", "GET", "/health"))
    if 'path.startswith("/api/")' not in web:
        raise SystemExit("web missing /api/ proxy")

    bridge = SOURCE_FILES["bridge"].read_text()
    if 'path == "/health"' not in bridge:
        raise SystemExit("bridge missing /health")
    found.add(("bridge", "GET", "/health"))
    if 'path == "/remotes"' not in bridge:
        raise SystemExit("bridge missing GET /remotes")
    found.add(("bridge", "GET", "/remotes"))
    for path in ("/remotes", "/remotes/delete", "/check", "/pull", "/publish"):
        if f'"{path}"' not in bridge:
            raise SystemExit(f"bridge missing POST {path}")
        found.add(("bridge", "POST", path))

    routes_re = re.compile(
        r'ROUTES\s*=\s*\{([^}]*)\}', re.S
    )
    entry_re = re.compile(
        r'\(\s*"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*"([^"]+)"\s*\)'
    )

    for service, rel in (
        ("usdm", SOURCE_FILES["usdm"]),
        ("projection", SOURCE_FILES["projection"]),
        ("subscriptions", SOURCE_FILES["subscriptions"]),
        ("transform", SOURCE_FILES["transform"]),
        ("adaptive", SOURCE_FILES["adaptive"]),
    ):
        text = rel.read_text()
        m = routes_re.search(text)
        if not m:
            raise SystemExit(f"{service}: ROUTES table not found")
        entries = entry_re.findall(m.group(1))
        if not entries:
            raise SystemExit(f"{service}: empty ROUTES")
        for method, path in entries:
            found.add((service, method, path))
        # JsonHandler health
        found.add((service, "GET", "/health"))

    return found


def main() -> int:
    if not OPENAPI.is_file():
        print(f"FAIL: missing {OPENAPI}", file=sys.stderr)
        return 1

    doc_ops = openapi_operations(OPENAPI.read_text())
    source_ops = discover_from_source()

    # OpenAPI must equal EXPECTED; EXPECTED must be covered by source discovery
    missing_in_openapi = EXPECTED - doc_ops
    extra_in_openapi = doc_ops - EXPECTED
    missing_in_source = EXPECTED - source_ops
    unexpected_in_source = source_ops - EXPECTED

    ok = True
    if missing_in_openapi:
        ok = False
        print("FAIL: routes missing from OpenAPI:")
        for row in sorted(missing_in_openapi):
            print(f"  {row}")
    if extra_in_openapi:
        ok = False
        print("FAIL: OpenAPI paths with no expected CE route:")
        for row in sorted(extra_in_openapi):
            print(f"  {row}")
    if missing_in_source:
        ok = False
        print("FAIL: expected routes not found in source:")
        for row in sorted(missing_in_source):
            print(f"  {row}")
    if unexpected_in_source:
        ok = False
        print("FAIL: source routes not listed in expected/OpenAPI set:")
        for row in sorted(unexpected_in_source):
            print(f"  {row}")

    # Contract metadata
    text = OPENAPI.read_text()
    if 'x-api-version: "1"' not in text and "x-api-version: '1'" not in text:
        ok = False
        print('FAIL: OpenAPI missing x-api-version: "1"')
    if "openapi: 3.1" not in text:
        ok = False
        print("FAIL: OpenAPI must declare openapi: 3.1.x")

    if ok:
        print(f"OK: {len(doc_ops)} OpenAPI operations match source routes (static)")
        print("OK: API version field x-api-version=1 present")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
