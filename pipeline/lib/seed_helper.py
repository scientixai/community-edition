"""Seed data loader with provenance tracking.

Loads seed batch files (enrollment, visit batches) through broker_upsert with
provenance stamps, ensuring demo and walkthrough data is traceable.
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone

import pnehttp

BROKER_URL = os.environ.get("PNE_BROKER_URL", "http://localhost:9090")


def load_seed_batch(batch_file: str | pathlib.Path) -> dict:
    """Load a seed batch file and upsert entities with provenance.
    
    Args:
        batch_file: Path to seed JSON file (relative to workspace root or absolute)
    
    Returns:
        dict with entityIds and provenance info
    """
    batch_path = pathlib.Path(batch_file)
    if not batch_path.is_absolute():
        batch_path = pathlib.Path.cwd() / batch_path
    
    if not batch_path.exists():
        raise FileNotFoundError(f"seed batch not found: {batch_file}")
    
    entities = json.loads(batch_path.read_text())
    if not isinstance(entities, list):
        raise ValueError(f"seed batch must be a JSON array: {batch_file}")
    
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
    return {
        "entityIds": entity_ids,
        "count": len(entity_ids),
        "batch": batch_name,
        "provenance": {
            "dataSource": f"seed-{batch_name}",
            "dataLoader": "demo-seed",
            "loadedAt": timestamp,
        }
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 seed_helper.py <batch-file>")
        sys.exit(1)
    result = load_seed_batch(sys.argv[1])
    print(json.dumps(result, indent=2))
