#!/usr/bin/env python3
"""Load source-system extracts into the broker through the connectors.

  python3 infra/scripts/load-sources.py examples/cvrm-118/sources

Every fact lands with observedAt (when it became true in its source system)
and sourceSystem (which system said so). Re-running replaces what an earlier
run loaded. Standard library only.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "lib"))
import loader  # noqa: E402
import pnehttp  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    if not pnehttp.wait_for_broker(60):
        print(f"Broker not reachable at {pnehttp.BROKER_URL}. Is the stack up?")
        return 1
    loader.load(pathlib.Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
