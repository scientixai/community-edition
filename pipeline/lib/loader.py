"""Load source-system extracts into the broker through the connectors.

Every fact lands with observedAt (when it became true in its source system)
and sourceSystem (which system said so). Loading replaces what an earlier
load wrote for the same things. Standard library only; used by
infra/scripts/load-sources.py and the web walkthrough.
"""

from __future__ import annotations

import pathlib
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone

import connectors
import pnehttp

NGSI = f"{pnehttp.BROKER_URL}/ngsi-ld/v1"


def enc(eid: str) -> str:
    return urllib.parse.quote(eid, safe="")


def to_ngsi(entity: dict, at: str, system: str) -> dict:
    out = {"id": entity["id"], "type": entity["type"]}
    for key, val in entity.items():
        if key in ("id", "type"):
            continue
        if isinstance(val, dict) and "rel" in val:
            out[key] = {"type": "Relationship", "object": val["rel"], "observedAt": at}
        else:
            out[key] = pnehttp.prop(val, at)
    out["sourceSystem"] = pnehttp.prop(system, at)
    return out


def in_history(eid: str) -> bool:
    status, _ = pnehttp.request("GET", f"{NGSI}/temporal/entities/{enc(eid)}?lastN=1",
                                headers={"Accept": "application/json", "Link": pnehttp.LINK_HEADER})
    return status == 200


ADAPTIVE_SOURCE = "Adaptive layer"
ADAPTIVE_TYPES = ("VisitOccurrence", "ClinicalObservation", "Participant", "AdverseEvent")


def clear_adaptive() -> int:
    """Delete what the adaptive layer committed, so a reload is a clean slate."""
    n = 0
    for type_ in ADAPTIVE_TYPES:
        try:
            found = pnehttp.broker_get_entities(type_, f'sourceSystem=="{ADAPTIVE_SOURCE}"')
        except RuntimeError:
            continue
        for e in found:
            pnehttp.request("DELETE", f"{NGSI}/entities/{enc(e['id'])}")
            pnehttp.request("DELETE", f"{NGSI}/temporal/entities/{enc(e['id'])}")
            n += 1
    return n


def load(src: pathlib.Path, say=print) -> dict:
    """Load every connector's events; returns counts per source system."""
    events = connectors.read_sources(src)
    ids = sorted({e["id"] for ev in events for e in ev["entities"]})
    say(f"Read {len(events)} events about {len(ids)} things from {src}")

    for eid in ids:  # replace any earlier load: current state and history
        pnehttp.request("DELETE", f"{NGSI}/entities/{enc(eid)}")
        pnehttp.request("DELETE", f"{NGSI}/temporal/entities/{enc(eid)}")
    removed = clear_adaptive()
    if removed:
        say(f"Removed {removed} entities an earlier walkthrough committed through the adaptive layer")

    # Time series (logger readings) are written straight into history first;
    # the facts loaded below then merge into the same history record.
    series = [ev["series"] for ev in events if ev.get("series")]
    for s in series:
        instances = [{"type": "Property", "value": v, "observedAt": t} for t, v in s["points"]]
        status, body = pnehttp.request(
            "POST", f"{NGSI}/temporal/entities",
            body={"@context": pnehttp.CONTEXT_URL, "id": s["id"], "type": s["type"], s["attr"]: instances},
            headers={"Content-Type": "application/ld+json"})
        if status not in (200, 201, 204):
            say(f"  series for {s['id']} failed: {status} {body}")

    loaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    per_system = Counter()
    by_time: dict[tuple, dict] = {}
    for ev in events:  # one batch per (time, system); same thing twice merges
        batch = by_time.setdefault((ev["at"], ev["system"]), {})
        for e in ev["entities"]:
            merged = batch.setdefault(e["id"], {"id": e["id"], "type": e["type"]})
            merged.update(e)
        per_system[ev["system"]] += 1
    for (at, system), batch in sorted(by_time.items()):
        pnehttp.broker_upsert([to_ngsi(e, at, system) for e in batch.values()],
                              provenance={"source": system, "loader": "load-sources", "time": loaded_at})

    for system, n in sorted(per_system.items()):
        say(f"  {system:<22} {n:>4} events")
    say(f"  {'logger readings':<22} {sum(len(s['points']) for s in series):>4} points")
    deadline = time.time() + 120  # history is recorded asynchronously
    while time.time() < deadline and not all(in_history(e) for e in ids[-5:]):
        time.sleep(1)
    say("Loaded.")
    return {"things": len(ids), "events": dict(per_system),
            "loggerReadings": sum(len(s["points"]) for s in series)}
