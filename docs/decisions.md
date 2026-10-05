# Decisions

The founding constraints of this edition, and the calls made on the
questions they left open.

## Founding constraints

- **Laptop-first, no Garnet dependency, inspired-by only.** No Garnet
  images, no CDK, no SQS/SNS/S3/Athena. Garnet is credited as
  architectural inspiration in prose only; see `architecture.md`.
- **Broker = upstream NEC Scorpio, in-memory profile**
  (`scorpiobroker/all-in-one-runner:java-6.0.1`). Kafka only if
  multi-node scale is ever needed, still cloud-agnostic. There is no
  upstream "6.0.10" to chase; that is a re-packager's own image
  version. [Certain: checked upstream tags]
- **License Apache-2.0**, matching T.O.P.; no proprietary code, ever.
  The Community Edition lives in its own public repository. Reaffirmed
  against GPLv3/AGPLv3 with the tradeoffs documented publicly in
  `licensing.md`; project-identity protection comes from trademark
  law (`TRADEMARKS.md`), not copyleft.
- **Naming**: "Provenance Neural Engine - Community Edition" for this
  repository. Keep naming durable and public-safe; do not encode internal
  product planning in this tree.
- **T.O.P. is the vocabulary source**: cr-domain ontology, examples,
  and the generated NGSI-LD context artifact. [Certain]
- **The engine is domain-agnostic; clinical research is the first
  anchored domain, not the boundary.** Domains are pluggable T.O.P.
  vocabularies over the same architecture. The applicability spans the
  healthcare and life sciences value chain (healthcare delivery, drug
  development, commercialization, claims) and the adjacent territory
  CMC crosses (manufacturing, quality, supply chain). Public materials
  must not describe this edition as solely a clinical-research product.

## Resolved here

1. **Lake persistence: filesystem for objects, DuckDB for query.**
   Dataset-JSON and SDTM outputs are plain files under `lake/data`;
   the lake service runs DuckDB over them read-only. Postgres would
   have been one fewer container but a worse Athena analogy and a
   worse "just ls the lake" demo. [Decided; the data shapes are small
   files, exactly DuckDB's sweet spot] The full rationale, the reopen
   conditions, and swap recipes (Postgres, Athena, Trino, ClickHouse,
   MinIO) live in `lake-alternatives.md`.

2. **Transform runtime: R.** sdtm.oak is an R package (CRAN,
   pharmaverse); no Python variant exists as a released library.
   [Certain: checked pharmaverse/sdtm.oak, Imports are all R packages] The service is rocker/r-ver + sdtm.oak
   plus a standard-library Python HTTP wrapper that handles broker I/O
   and shells out to Rscript. This keeps sdtm.oak as the genuine
   transform engine (assign_ct, assign_no_ct, derive_seq over oak id
   variables) without pulling plumber's dependency tree.

3. **Scenario scope: vertical slice.** One study (CARDIO-118), two
   arms, two participants, three visit timepoints, vitals only. The
   pipeline produces TS/TA/TI/TV design domains plus VS and DM. The
   full USDM-to-SDTM breadth is a widening exercise, not an
   architecture change. [Likely the right cut; widen after v1]

4. **Adaptive layer: both modes.** Anthropic API (direct HTTPS,
   Messages API, default model `claude-opus-4-8`, no SDK so the
   container builds offline) when `ANTHROPIC_API_KEY` is set; a
   deterministic stub parser otherwise, so the full loop demos with no
   key on conference wifi. The stub only understands the demo statement
   shapes, and says so in its error message. [Decided]
   Update (0.1.3): with a key, the model looks the graph up before it
   proposes and the service checks every entity and link; the default
   model is `claude-opus-5-5`.

5. **Broker: published image for v1.** `broker/build/` documents the
   from-source recipe (Tier B) but nothing depends on it. [Decided;
   revisit only if branding demands a Scientix-built image]

6. **Context serving.** The T.O.P. NGSI-LD context artifact is vendored
   and merged (by `infra/scripts/build-context.py`) with a supplement
   layer: cr: instance-level terms that T.O.P.'s own worked examples and
   SDTM projections use but that the generated context omits, plus a
   small pne: namespace for demo-only display terms. The remote ETSI
   core-context reference is dropped because NGSI-LD brokers append the
   core context implicitly; the merged file is fully self-contained and
   served by the web service, so the whole stack runs with no internet
   access. [Certain for Scorpio 6.0.1: verified by round-trip]

7. **Packaging: prebuilt images first, two installer skins.** Releases
   push multi-arch images to GHCR so install day pulls instead of
   builds; the curl-able `install.sh` and the `npx pne-community-edition`
   wrapper are thin skins over the same flow (check Docker, fetch the
   pinned release, compose up, wait for broker health). The npx package
   has zero npm dependencies. [Decided]

8. **Connectors: one rclone bridge, off by default.** Remote storage
   in and out (Google Drive, OneDrive, WebDAV, S3, SFTP, and everything
   else rclone speaks) goes through a single optional service under the
   compose profile `connectors`, with two flows: inbox (pull files,
   ingest USDM definitions into the broker) and publish (lake outputs
   to a remote folder). Keyed backends configure through the setup
   wizard; OAuth backends use rclone's own guided flow once. Hand-built
   per-provider clients were rejected as pure maintenance surface.
   [Decided]

9. **Notification coalescing, not queuing.** The listener sets a dirty
   flag and a single worker reruns the transform; each run regenerates
   SDTM from current broker state, so runs are idempotent and bursts of
   notifications collapse into one transform. At community scale a
   queue is unnecessary; this is the moral replacement for SQS.
   [Decided]
