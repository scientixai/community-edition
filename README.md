# Scientix.AI Community Edition

Laptop-runnable Community Edition of the Provenance Neural Engine: an NGSI-LD context broker you can stand up locally and practice the linked-data ideas from the CDISC US Interchange talk.

## Quick start

```bash
PNE_SCORPIO_IMAGE=scorpiobroker/all-in-one-runner:java-6.0.1 \
  docker compose -f docker-compose.yaml up -d --pull never
curl -sS http://127.0.0.1:9090/q/health
```

If port `9090` is already taken on your machine, use the local overlay (Scorpio on `19091`, web on `18080`):

```bash
PNE_SCORPIO_IMAGE=scorpiobroker/all-in-one-runner:java-6.0.1 \
  docker compose -f docker-compose.yaml -f docker-compose.local-run.yaml up -d --pull never
curl -sS http://127.0.0.1:19091/q/health
```

## What to try next

- See `docs/getting-started.md` and `docs/architecture.md`.
- HTTP API contracts (OpenAPI 3.1, version 1): `docs/api/openapi.yaml` and `docs/contracts.md`.
- Prefer full IRIs over bare local type strings when querying (linked data travels with the identifier).

## Contributing and security

- How to run the proof scripts and open a change: `CONTRIBUTING.md`.
- How to report a vulnerability privately: `SECURITY.md`.
- License, attribution, and marks: `LICENSE`, `NOTICE`, `ATTRIBUTION.md`, `TRADEMARKS.md`.
