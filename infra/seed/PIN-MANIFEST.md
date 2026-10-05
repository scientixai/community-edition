# CE NR-010 Pin Manifest

**Applies to:** release 0.1.2 (see `VERSION`)

## Purpose

This manifest records the construction-time pins for the Community Edition
at release 0.1.2. These files are vendored/built at construction time and
define the semantic foundation for CE runtime operations.

**NR-010 bar:** TOP Core is a construction-time pin; runtime must not require
a live TOP network dependency.

## Pinned Artifacts

Measured on the 0.1.2 tree via `sha256sum`:

| Artifact | Role | SHA-256 |
| --- | --- | --- |
| `infra/seed/top-cr-v1.ngsi-context.jsonld` | Construction-time TOP cr-domain NGSI-LD source (input only) | `ac5c4e6e1c68b2e2a634b5fba482dfec190ecb06bb82d8c31a500e34b178a317` |
| `web/public/context/pne-context.jsonld` | Runtime served context (flat, no remote refs) | `db50c27d1c7d451c11542f426a6e073a1938b52748de023b76e3efb9c856262f` |

## Context Architecture

- **Construction-time:** `top-cr-v1.ngsi-context.jsonld` includes `https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context-v1.8.jsonld` as the first `@context` string. This file is an **input only** to the build process.

- **Runtime:** `pne-context.jsonld` is built from `top-cr-v1` by `infra/scripts/build-context.py`, which drops all remote document references (including the ETSI string). This flattened context is what the broker and services fetch at runtime from `http://web:8080/context/pne-context.jsonld`.

- **Served at runtime:** Only `pne-context.jsonld`. No ETSI remote document strings are present in the runtime-served file.

- **Namespace IRIs in served context (identity only, not dereferenced):**
  - `https://top.scientix.ai/{v1,cr/v1,hcls/v1,crosswalk/v1,pne-ce/v1}#`
  - `http://www.w3.org/ns/prov#`
  - `https://schema.org/name`
  - **No `w3id.org` strings** in the served file.

## Runtime Egress Status

The blackhole prove **harness ships in this tree**, but NR-010
seed/load/query offline prove is still **OPEN** until someone executes
`infra/scripts/nr010-blackhole-prove.sh` and records exit 0.

The prove script:
1. Brings up the stack with `docker-compose.nr010-blackhole.yml` overlay, which maps `uri.etsi.org`, `top.scientix.ai`, `w3id.org`, and `schema.org` to `127.0.0.1` (blackhole).
2. Performs seed upsert + entity query using the local `http://web:8080/context/pne-context.jsonld`.
3. Verifies from inside the `scorpio` container that all blackholed domains are unreachable.
4. Exits 0 only if both the stack operations succeed AND the blackhole curls fail as expected.

**Status:** Harness + pin manifest present. Offline prove pending execution.

## ETSI Core Context

**Status:** Not vendored in the CE tree.

**Rationale:** The `build-context.py` script drops the ETSI remote string from the served context. Scorpio 6.0.1 embeds the NGSI-LD core context implicitly. The blackhole prove confirms that runtime seed/load/query does not attempt to dereference `uri.etsi.org`.

If future testing or Scorpio behavior changes require vendoring the ETSI core document, it should be placed in `web/public/context/` and referenced via the local `http://web:8080/context/` URL (following the CDISC pattern).

## TOP Core Source

**TOP Git Revision:** Not recorded in this manifest (CE vendored files exist as committed snapshots; TOP Core pin with git SHA and observedAt clock is a separate TOP-side freeze record).

**CE treatment:** The `top-cr-v1.ngsi-context.jsonld` file is a construction-time input. Updates to this file from TOP Core would flow via manual vendor + re-pin, not runtime fetch.

## Verification

To run the blackhole prove:

```bash
# Prerequisites: images already built/pulled
sha256sum infra/seed/top-cr-v1.ngsi-context.jsonld web/public/context/pne-context.jsonld
./infra/scripts/nr010-blackhole-prove.sh
```

Expected result: Script exits 0 with message "NR-010 Blackhole Prove: PASS".

---

**Pin is construction-time.** Runtime serves `pne-context.jsonld` only.
