# Provenance Properties — Community Edition

**Status:** Implemented  
**Applies to:** Broker entities and lake objects  
**Edition:** Community Edition only

## Overview

The Community Edition attaches structured provenance metadata to entities and lake objects at write time. Provenance answers **where data came from** (source), **what process wrote it** (loader), and **when** (time).

This is provenance-as-data: the properties travel with the entity or object and are queryable alongside domain content.

## Broker Entity Provenance (NGSI-LD Properties)

Write paths that upsert broker entities can supply a provenance context. When provided, `broker_upsert` attaches three NGSI-LD Properties to every entity in the batch:

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `dataSource` | Property (string) | Identifier of the originating system or file | `"usdm-study.json"`, `"adaptive-commit"`, `"seed-enrollment-batch"` |
| `dataLoader` | Property (string) | Name of the service or process that wrote the entity | `"usdm-load"`, `"adaptive-layer"`, `"demo-seed"` |
| `loadedAt` | Property (datetime) | ISO 8601 timestamp when the entity was written | `"2026-09-18T20:30:45Z"` |

### Property Shape (NGSI-LD normalized form)

```json
{
  "dataSource": {
    "type": "Property",
    "value": "usdm-study.json"
  },
  "dataLoader": {
    "type": "Property",
    "value": "usdm-load"
  },
  "loadedAt": {
    "type": "Property",
    "value": "2026-09-18T20:30:45Z"
  }
}
```

These properties are attached at the entity level and appear alongside domain Properties (like `studyTitle`, `visitNumber`) when you query the broker.

### Usage from Write Paths

Services call `broker_upsert` with an optional `provenance` dict:

```python
from pnehttp import broker_upsert

entities = [
    {"id": "urn:ngsi-ld:Study:CARDIO-118", "type": "Study", ...},
]

broker_upsert(
    entities,
    provenance={
        "source": "usdm-study.json",
        "loader": "usdm-load",
        "time": "2026-09-18T20:30:45Z"
    }
)
```

If `provenance` is omitted or `None`, no provenance properties are attached (backward compatible).

## Lake Object Provenance (Metadata Sidecar)

Lake write paths (`POST /objects`) can supply provenance metadata for files written to the lake. The lake service stores provenance alongside the content file as a JSON sidecar:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `source` | string | Origin of the content | `"broker-vitals-raw"`, `"projection-design"` |
| `loader` | string | Service that wrote the object | `"transform-sdtm"`, `"projection-trial-design"` |
| `time` | string (ISO 8601) | When the object was written | `"2026-09-18T20:35:12Z"` |

### Sidecar Location

For an object at `lake/path/to/file.csv`, the provenance sidecar lives at `lake/path/to/.pne-provenance/file.csv.json`.

**Sidecar shape:**

```json
{
  "source": "broker-vitals-raw",
  "loader": "transform-sdtm",
  "time": "2026-09-18T20:35:12Z"
}
```

### Usage from Write Paths

Services call lake `POST /objects` with an optional `provenance` dict in the request body:

```python
status, body = request(
    "POST",
    f"{LAKE_URL}/objects",
    body={
        "path": "sdtm/vs.csv",
        "content": csv_text,
        "provenance": {
            "source": "broker-vitals-raw",
            "loader": "transform-sdtm",
            "time": "2026-09-18T20:35:12Z"
        }
    }
)
```

If `provenance` is omitted, no sidecar is written (backward compatible).

## Design Decisions

1. **Function names over product marks:** Property IRIs use durable vocabulary (`dataSource`, `dataLoader`, `loadedAt`) rather than product-specific naming.

2. **CE-only properties:** These provenance properties are Community Edition features. They do not appear in upstream cr-domain or T.O.P. vocabularies.

3. **Write-time attachment:** Provenance is stamped at the shared write boundary (`broker_upsert` / lake `POST /objects`), so all write paths (USDM, adaptive, transform, projection, seed) inherit one implementation.

4. **Backward compatible:** Existing code that calls `broker_upsert(entities)` or lake `POST /objects` without provenance continues to work unchanged.

5. **Authority ≠ provenance:** Adaptive commit `authority` (who approved the write) is now also captured as provenance. The decision log remains an audit trail; provenance-as-data makes it queryable on entities.

## Write Paths Using Provenance

| Write Path | Component | Provenance Context |
|------------|-----------|-------------------|
| **WP-01** | USDM load | `source`: USDM file or seed name, `loader`: `"usdm-load"` |
| **WP-04** | Transform (raw snapshots) | `source`: `"broker-vitals-raw"` or `"broker-dm-raw"`, `loader`: `"transform-raw-snapshot"` |
| **WP-04** | Transform (SDTM outputs) | `source`: `"broker-{domain}-transformed"`, `loader`: `"transform-sdtm"` |
| **WP-05** | Adaptive commit | `source`: authority source/approver, `loader`: `"adaptive-layer"`, plus authority stamp |
| **WP-08** | Projection (trial design) | `source`: `"broker-study-design"`, `loader`: `"projection-trial-design"` |
| **WP-11** | Demo seed | `source`: `"seed-{batch-name}"`, `loader`: `"demo-seed"` |

All broker entity writes now pass through `broker_upsert` with provenance. All lake writes include provenance sidecars in `.pne-provenance/` directories.

## Not yet covered

- Outbound provenance (bridge publish)
- Provenance IRIs minted in T.O.P.
