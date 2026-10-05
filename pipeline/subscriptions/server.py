"""NGSI-LD subscription listener: the SQS/SNS replacement.

On startup it registers a subscription on the broker for execution-side
entity types (Participant, VisitOccurrence, ClinicalObservation). The
broker then POSTs notifications straight to this listener's /notify
endpoint over plain HTTP; each notification triggers the sdtm.oak
transform. Garnet needed SNS+SQS+Lambda plumbing for the same hop; the
NGSI-LD subscription API does it natively.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
from pathlib import Path

import pnehttp

NOTIFY_URL = os.environ.get("PNE_NOTIFY_URL", "http://subscriptions:8103/notify")
TRANSFORM_URL = os.environ.get("PNE_TRANSFORM_URL", "http://transform:8104")
SUBSCRIPTION_ID = "urn:ngsi-ld:Subscription:pne-ce-pipeline"


def _load_watched_types() -> list[str]:
    """Load subscription watch types from env JSON or adjacent config file."""
    raw = os.environ.get("PNE_WATCHED_TYPES", "").strip()
    if raw:
        return list(json.loads(raw))
    cfg_path = Path(
        os.environ.get(
            "PNE_WATCHED_TYPES_PATH",
            str(Path(__file__).with_name("watched-types.json")),
        )
    )
    return list(json.loads(cfg_path.read_text()))


WATCHED_TYPES = _load_watched_types()

EVENTS: list[dict] = []
EVENTS_LOCK = threading.Lock()
TRANSFORM_PENDING = threading.Event()


def register_subscription():
    """Create (or replace) the pipeline subscription once the broker is up."""
    if not pnehttp.wait_for_broker():
        print("[subscriptions] broker never became healthy", flush=True)
        return
    subscription = {
        "@context": pnehttp.CONTEXT_URL,
        "id": SUBSCRIPTION_ID,
        "type": "Subscription",
        "description": "PNE CE: execution-data changes trigger the sdtm.oak transform",
        "entities": [{"type": t} for t in WATCHED_TYPES],
        "notification": {
            "endpoint": {"uri": NOTIFY_URL, "accept": "application/json"},
            "format": "normalized",
        },
    }
    # Delete a leftover subscription from a previous run, then create.
    pnehttp.request(
        "DELETE", f"{pnehttp.BROKER_URL}/ngsi-ld/v1/subscriptions/{SUBSCRIPTION_ID}"
    )
    status, body = pnehttp.request(
        "POST",
        f"{pnehttp.BROKER_URL}/ngsi-ld/v1/subscriptions",
        body=subscription,
        headers={"Content-Type": "application/ld+json"},
    )
    print(f"[subscriptions] registered {SUBSCRIPTION_ID}: {status} {body}", flush=True)


def transform_worker():
    """Coalesce bursts of notifications into sequential transform runs."""
    while True:
        TRANSFORM_PENDING.wait()
        TRANSFORM_PENDING.clear()
        try:
            status, body = pnehttp.request(
                "POST", f"{TRANSFORM_URL}/run", body={}, timeout=310
            )
            outputs = (body or {}).get("outputs", [])
            record_event(
                "transform-run",
                {"status": status, "outputs": [o.get("path") for o in outputs]},
            )
        except Exception as err:
            record_event("transform-error", {"error": str(err)})


def record_event(kind: str, detail: dict):
    with EVENTS_LOCK:
        EVENTS.append(
            {
                "at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "kind": kind,
                **detail,
            }
        )
        del EVENTS[:-100]
    print(f"[subscriptions] {kind}: {detail}", flush=True)


class SubscriptionsHandler(pnehttp.JsonHandler):
    ROUTES = {
        ("POST", "/notify"): "notify",
        ("GET", "/events"): "events",
        ("GET", "/subscription"): "subscription",
    }

    def notify(self, body):
        entities = (body or {}).get("data", [])
        record_event(
            "notification",
            {
                "subscriptionId": (body or {}).get("subscriptionId"),
                "entities": [
                    {"id": e.get("id"), "type": e.get("type")} for e in entities
                ],
            },
        )
        TRANSFORM_PENDING.set()
        return 200, {"ok": True}

    def events(self, _body):
        with EVENTS_LOCK:
            return 200, {"events": list(reversed(EVENTS))}

    def subscription(self, _body):
        status, body = pnehttp.request(
            "GET",
            f"{pnehttp.BROKER_URL}/ngsi-ld/v1/subscriptions/{SUBSCRIPTION_ID}",
            headers={"Accept": "application/json"},
        )
        return status, body


def startup():
    threading.Thread(target=transform_worker, daemon=True).start()
    register_subscription()


if __name__ == "__main__":
    pnehttp.serve(SubscriptionsHandler, 8103, startup=startup)
