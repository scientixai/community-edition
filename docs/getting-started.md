# Getting started

Fifteen minutes from clone to a clinical study flowing end to end.

## 1. Prerequisites (2 minutes)

### All platforms

- **Docker with Compose v2**: Run `docker compose version` to verify. If missing, install Docker:
  - **Linux**: [Docker Engine](https://docs.docker.com/engine/install/) (no Desktop required)
  - **Windows**: [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/) with WSL2 backend enabled
  - **macOS**: [Docker Desktop](https://docs.docker.com/desktop/install/mac-install/)
- **6 GB of free RAM** for the containers; the broker JVM is the big one.
- **No cloud account, no API keys required**. Optionally, an `ANTHROPIC_API_KEY` makes step 7 use a real model instead of the offline stub.

### Platform-specific notes

- **Apple Silicon**: The Scorpio broker image is amd64-only. In Docker Desktop settings, enable "Use Rosetta for x86_64/amd64 emulation" for best performance.
- **Windows**: Ensure WSL2 is enabled and Docker Desktop uses the WSL2 backend (default on recent installs). The stack runs inside WSL2.
- **Linux**: Docker Engine works directly; Desktop is optional.

## 2. Bring the stack up (3 minutes)

Any of these is equivalent:

```sh
# one-liner installer (checks Docker, fetches the release, starts, waits)
curl -fsSL https://raw.githubusercontent.com/scientixai/community-edition/main/install.sh | sh

# npx flavor of the same
npx pne-community-edition

# or from a clone
docker compose up -d
```

### Handling busy ports

The runtime uses ports **9090** (broker), **8080** (web), and **8101–8107** (pipeline services).

**If only ports `9090` or `8080` are busy**, use the local overlay (Scorpio on `19091`, web on `18080`):

```sh
docker compose -f docker-compose.yaml -f docker-compose.local-run.yaml up -d
```

**If the entire range is busy** (including `18080`, `19091`, and `8101–8107`), use a full-port overlay. An example is provided:

```sh
docker compose -f docker-compose.yaml -f docker-compose.busy-ports.example.yaml up -d
```

The example remaps to `19092` (broker), `18081` (web), and `18101–18107` (services). Copy and adjust `docker-compose.busy-ports.example.yaml` for custom mappings.

### Port overlay notes

- Overlays remap **host-side ports only**. Internal container ports and service-to-service URLs remain unchanged.
- When using an overlay, substitute the remapped ports in all `localhost` URLs throughout this guide (e.g., `19091` for `9090`, `18080` for `8080`).
- For concurrent projects on the same machine, use `docker compose -p <unique-name>` to run multiple stacks with the same port mappings.

### Starting and waiting

Releases ship prebuilt images, so nothing compiles on install. Building from a clone instead, the first build downloads the broker image and installs sdtm.oak from CRAN inside the transform image. Wait for the broker:

```sh
curl -s http://localhost:9090/q/health
# or with an overlay: curl -s http://localhost:${SCORPIO_HOST_PORT}/q/health
docker compose logs scorpio | grep "in-memory"
# ... Profile in-memory activated.
```

That log line is the whole point: every broker service in one JVM,
in-process messaging, no external message bus, no cloud.

Behind a TLS-inspecting corporate proxy, builds that need the network
(transform, lake) will fail TLS verification. Drop your proxy's CA
certificates (`*.crt`) into `pipeline/transform/build-support/ca/` and
`lake/build-support/ca/` and rebuild.

## 3. First-run wizard (optional, 1 minute)

`http://localhost:8080/setup.html` (or `http://localhost:18080/setup.html`
with the overlay) checks service health, seeds the demo study or starts
empty, shows whether the AI layer has a key, and configures optional
storage connectors (see `connectors.md`).

## 4. Walk the scenario

Open **http://localhost:8080** (or **http://localhost:18080** with the
overlay) and click through steps 1 to 6, or run `./infra/scripts/demo.sh`
for the terminal version. What follows is the same flow by hand, so you
can see every request.

**Note**: Examples below use the default ports (`9090` for Scorpio, `8080`
for web). If you started with the overlay, substitute `19091` for `9090`
and `18080` for `8080` in all `localhost` URLs.

### Author the study (1 minute)

```sh
curl -X POST http://localhost:8101/load
```

The bundled USDM-style definition of study CARDIO-118 becomes 12
NGSI-LD entities in the broker, typed with the T.O.P. cr-domain
vocabulary. Read one back, compacted with the same context:

```sh
curl -s "http://localhost:9090/ngsi-ld/v1/entities/urn:ngsi-ld:Study:CARDIO-118" \
  -H 'Accept: application/json' \
  -H 'Link: <http://web:8080/context/pne-context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"'
```

(The context URL says `web:8080` because the broker resolves it inside
the compose network.)

**Note**: Fetching a Study entity by its full entity id (as above) works reliably after USDM load. Listing with `?type=Study` may return empty results depending on broker IRI and context handling; prefer direct id-based fetch for verification.

### Project the design (30 seconds)

```sh
curl -X POST http://localhost:8102/project -H 'Content-Type: application/json' -d '{}'
ls lake/data/datasetjson/
# ta.json  ti.json  ts.json  tv.json
```

SDTM trial-design domains as Dataset-JSON v1.1, straight from broker
state. Standards are views, not the stored model.

### Record execution data and watch the pipeline fire (2 minutes)

```sh
curl -X POST "http://localhost:9090/ngsi-ld/v1/entityOperations/upsert?options=update" \
  -H 'Content-Type: application/ld+json' \
  --data-binary @infra/seed/enrollment-batch.json

curl -X POST "http://localhost:9090/ngsi-ld/v1/entityOperations/upsert?options=update" \
  -H 'Content-Type: application/ld+json' \
  --data-binary @infra/seed/visit-batch-baseline.json
```

Nothing here talks to the pipeline. The broker does: the registered
NGSI-LD subscription POSTs a notification to the listener, which runs
the sdtm.oak transform. See it:

```sh
curl -s http://localhost:8103/events
ls lake/data/sdtm/
# dm.csv  dm.json  vs.csv  vs.json
```

Load `infra/seed/visit-batch-week4.json` the same way for a second
timepoint.

### Query the lake (1 minute)

```sh
python3 lake/query.py "SELECT VISIT, VSTESTCD, round(avg(VSSTRESN),1) AS mean_value
  FROM read_csv_auto('/lake/sdtm/vs.csv')
  GROUP BY VISIT, VSTESTCD ORDER BY min(VISITNUM), VSTESTCD"
```

DuckDB over files on disk. The same queries Athena would have run, with
zero infrastructure.

### The sprinkle of AI (1 minute)

The adaptive service demonstrates Engineering Floor Rule 7 (capability ≠
authority): it can construct entities but not unilaterally write them.

**Propose**: construct entities from a natural-language statement:

```sh
curl -X POST http://localhost:8106/construct -H 'Content-Type: application/json' -d '{
  "statement": "Participant P2201 completed the Week 8 visit at the Houston site on June 1st, 2026. Seated systolic blood pressure was 121 mmHg."
}'
```

The service returns a proposal id and the constructed entities. It does
**not** write to the broker. Without `ANTHROPIC_API_KEY` the
deterministic stub parses statements of that shape. With a key, the
service makes one Messages API call and handles free-form statements.

**Execute**: commit the proposal with explicit authority:

```sh
# Save the proposal id and entities from the /construct response
PROPOSAL_ID="<proposalId-from-above>"
ENTITIES='[...]'  # entities array from /construct response

# Attempt commit without the execute flag (will be denied and recorded)
curl -X POST http://localhost:8106/commit -H 'Content-Type: application/json' -d '{
  "proposalId": "'$PROPOSAL_ID'",
  "entities": '$ENTITIES',
  "authority": {"source": "demo", "approver": "user", "reason": "test"}
}'
# Returns 403: execution denied

# Enable execution and commit
docker compose stop adaptive
PNE_ADAPTIVE_EXECUTE=true docker compose up -d adaptive

curl -X POST http://localhost:8106/commit -H 'Content-Type: application/json' -d '{
  "proposalId": "'$PROPOSAL_ID'",
  "entities": '$ENTITIES',
  "authority": {"source": "demo", "approver": "user", "reason": "approved-test"}
}'
```

The statement becomes a VisitOccurrence and a ClinicalObservation,
written through the broker, which fires the subscription, which reruns
the transform. Check `http://localhost:8103/events` and re-run the lake
query: week 8 appears.

**Inspect decisions**: all commit attempts (denied and allowed) are
recorded:

```sh
curl http://localhost:8106/decisions
```

## 4. Reset

```sh
docker compose down -v && rm -rf lake/data/* && docker compose up -d
```

## Troubleshooting

- **Broker never healthy**: `docker compose logs scorpio`. On Apple
  Silicon without Rosetta the JVM can crash-loop under QEMU.
- **Notifications not arriving**: `curl http://localhost:8103/subscription`
  shows the subscription as the broker sees it; `docker compose logs
  subscriptions` shows registration and deliveries.
- **Transform errors**: `curl http://localhost:8104/status` shows the
  last run; `docker compose logs transform` includes the R output.
- **Port conflicts**: Scorpio (9090) and web (8080) must be free. Use
  `docker-compose.local-run.yaml` as shown in step 2 to remap to 19091/18080,
  or `docker-compose.busy-ports.example.yaml` for a full-range overlay if all
  standard ports are busy. Edit or create custom overlay files for other mappings.
- **install.sh with overlays**: The installer health-checks the default broker
  port (9090) unless overridden. For custom port mappings, set
  `SCORPIO_HOST_PORT=19091` (or your chosen port) or
  `BROKER_HEALTH_URL=http://localhost:19091/q/health` when running install.sh.
