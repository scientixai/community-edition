# Architecture

```
                 ┌─────────────────────────────────────────────────┐
                 │                web  :8080                       │
                 │  walkthrough UI · JSON-LD context host ·        │
                 │  same-origin /api proxy to every service        │
                 └───────┬─────────────────────────────────────────┘
                         │ serves /context/pne-context.jsonld
                         ▼
┌──────────┐   NGSI-LD  ┌──────────────────┐   notification   ┌───────────────┐
│  usdm    │──entities─▶│  Scorpio :9090   │─────POST────────▶│ subscriptions │
│  :8101   │            │  in-memory       │                  │ :8103         │
└──────────┘            │  all-in-one      │                  └──────┬────────┘
                        │  + PostGIS       │                         │ POST /run
┌──────────┐   reads    └──────────────────┘   reads                 ▼
│projection│◀───────────────────┘  └─────────────────────▶┌───────────────┐
│  :8102   │                                              │  transform    │
└────┬─────┘            ┌──────────────────┐              │  :8104        │
     │ Dataset-JSON     │  adaptive :8106  │              │  sdtm.oak (R) │
     ▼                  │  NL -> entity    │──entities──▶ └──────┬────────┘
┌─────────────────┐     │  API or stub     │   (broker)          │ SDTM CSV +
│  lake/data      │     └──────────────────┘                     │ Dataset-JSON
│  (filesystem)   │◀─────────────────────────────────────────────┘
│      ▲          │
│      │ DuckDB   │
│  lake :8105     │
└─────────────────┘
```

## Why this stack runs on a laptop

This Community Edition was inspired by the [AWS Garnet Framework](https://github.com/awslabs/garnet-framework) — an open NGSI-LD context broker on commodity cloud infrastructure. Garnet is a strong path if you want to explore that deployment model. We chose a different release shape on purpose.

We wanted something that did **not** require a full cloud account and all of its complexity, so the novelty of NGSI-LD in this still-unproven clinical domain could be demonstrated on a laptop: self-contained, inspectable, and something an audience can run after the talk. That decision is about how we teach and grow the Community Edition with contributors. It is not an argument against Garnet or against cloud deployments.

If you want to explore with Garnet, do. This repo is our free Community Edition of that idea for local practice, and we intend to grow it collaboratively toward something that can change how this industry moves meaning across boundaries.

### Three local replacements (relative to a typical Garnet/cloud layout)

**Subscriptions instead of SQS/SNS.** The `subscriptions` service
registers one NGSI-LD subscription on the broker for the execution
entity types (Participant, VisitOccurrence, ClinicalObservation). The
broker POSTs notifications directly to the listener's `/notify`
endpoint. A Garnet-style cloud path often uses SNS, SQS, and Lambda for
this hop; the NGSI-LD subscription API does it natively. Bursts of
notifications coalesce into one transform run (a dirty flag and a
single worker), and runs regenerate SDTM from current broker state, so
they are idempotent.

**A directory instead of S3, DuckDB instead of Athena.** Everything the
pipeline produces lands as files under `lake/data`: Dataset-JSON design
domains, raw EDC-style extracts, SDTM CSVs. The lake service owns all
writes to this directory through its `POST /objects` API and exposes
DuckDB SQL over the stored files. Pipeline services (projection,
transform, bridge) write through the lake HTTP contract, not by direct
filesystem access. This enforces clear ownership: the lake is the only
component with write authority to its data. It is simpler for a laptop,
and you can `ls` the lake. The lake is also the most swappable
component: `lake-alternatives.md` records the DuckDB-vs-Postgres
rationale and gives recipes for Postgres, Athena, and other engines
behind the same small API contract.

**Compose instead of Fargate.** Single-node is the point for this
edition. Every pipeline service except `transform` and `lake` is
standard-library Python on `python:3.12-slim` and builds with no
network at all.

## Data flow, end to end

1. `usdm` maps a USDM-style study definition to cr-domain entities and
   batch-upserts them with the payload `@context` pointing at the file
   the web service hosts. The broker dereferences it once and caches.
2. `projection` reads the design entities back (compacted via the same
   context) and writes TS/TA/TI/TV Dataset-JSON to the lake via `POST
   /objects`.
3. Execution writes (from seed batches, from the adaptive service, or
   from anything else that speaks NGSI-LD) hit the broker and fire the
   subscription.
4. `transform` snapshots broker state into raw EDC-style CSVs, runs the
   sdtm.oak mapping in R (controlled-terminology assignment, direct
   assignment, sequence derivation), and writes SDTM VS and DM to the
   lake as CSV and Dataset-JSON via `POST /objects`.
5. `lake` serves DuckDB SQL over whatever is on disk and owns all write
   operations through its HTTP contract.

## Vocabulary and context

Entity types and properties come from the T.O.P. cr-domain: the same
classes and instance-level properties its worked examples use
(`cr:Participant`, `cr:screeningNumber`, `cr:VisitOccurrence`,
`cr:parameterCode`, ...). The NGSI-LD `@context` is generated by
`infra/scripts/build-context.py` from the vendored T.O.P. context
artifact plus a supplement layer, and served self-contained (no remote
ETSI reference), so the stack runs with no internet access.

## The adaptive service: propose-execute split (Rule 7)

The adaptive service (`adaptive :8106`) constructs NGSI-LD entities from
natural-language clinical statements using either an LLM (Anthropic
Claude) or an offline deterministic stub parser. It demonstrates
**Engineering Floor Rule 7: capability ≠ authority**.

The service can construct entities (capability) but cannot unilaterally
write them to the broker (authority). This edition implements:

- **Propose-only construction**: `POST /construct` builds entities and
  returns them with a unique proposal identifier. It never calls the
  broker upsert operation.
- **Explicit authority gate**: `POST /commit` accepts the proposal,
  entities, and an `authority` object (containing explicit decision
  fields like source, approver, reason). Execution is gated by the
  `PNE_ADAPTIVE_EXECUTE` environment variable (default deny).
- **Durable decision record**: Every commit attempt (allowed or denied)
  is logged to an append-only JSONL file at
  `/adaptive-decisions/decisions.jsonl`, recording the proposal id,
  decision, authority fields, timestamp, and affected entity ids.

This is the honest Community Edition floor: stub authority checks and
local component-owned decision records. The adaptive path proposes entities
and only writes when the explicit execute gate is enabled; the decision log
is a local append-only JSONL file.
