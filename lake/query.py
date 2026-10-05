#!/usr/bin/env python3
"""Query the lake from the host: python3 lake/query.py "SELECT ...".

Thin client for the lake service's /sql endpoint (DuckDB). Paths inside
queries are container paths, e.g. read_csv_auto('/lake/sdtm/vs.csv').
"""

import json
import sys
import urllib.request

LAKE_URL = "http://localhost:8105/sql"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    req = urllib.request.Request(
        LAKE_URL,
        data=json.dumps({"sql": sys.argv[1]}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as err:
        result = json.load(err)
    if "error" in result:
        print(result["error"])
        return 1
    widths = [
        max(len(str(c)), *(len(str(r[i])) for r in result["rows"]))
        if result["rows"]
        else len(str(c))
        for i, c in enumerate(result["columns"])
    ]
    print("  ".join(str(c).ljust(w) for c, w in zip(result["columns"], widths)))
    for row in result["rows"]:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
