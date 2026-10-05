#!/usr/bin/env bash
# Walks the CDISC scenario end to end against a running stack
# (docker compose up -d --build). Terminal twin of the web walkthrough
# at http://localhost:8080.
set -euo pipefail
cd "$(dirname "$0")/../.."

BROKER=${BROKER:-http://localhost:9090}
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
json() { python3 -m json.tool; }

step "1. Author the study: USDM definition -> NGSI-LD entities in the broker"
curl -sf -X POST http://localhost:8101/load | json

step "   Read the study back from the broker (compacted with the T.O.P. context)"
curl -sf "$BROKER/ngsi-ld/v1/entities/urn:ngsi-ld:Study:CARDIO-118" \
  -H 'Accept: application/json' \
  -H 'Link: <http://web:8080/context/pne-context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"' | json

step "2. Project the design to Dataset-JSON trial-design domains (TS/TA/TI/TV)"
curl -sf -X POST http://localhost:8102/project -H 'Content-Type: application/json' -d '{}' | json

step "3. Enroll participants (writes through the broker; watch the subscription fire)"
python3 pipeline/lib/seed_helper.py infra/seed/enrollment-batch.json | json

step "4. Record baseline visits with vitals (notification -> sdtm.oak transform)"
python3 pipeline/lib/seed_helper.py infra/seed/visit-batch-baseline.json | json

step "5. Record week-4 visits (systolic pressure falling on BX-441)"
python3 pipeline/lib/seed_helper.py infra/seed/visit-batch-week4.json | json

step "   Waiting for the sdtm.oak transform to finish (first run includes R startup)"
tries=0
until curl -sf http://localhost:8105/files | grep -q "sdtm/vs.csv"; do
  tries=$((tries + 1))
  [ "$tries" -gt 30 ] && { echo "transform did not produce SDTM within 60s; check: docker compose logs transform"; exit 1; }
  sleep 2
done

step "   Subscription listener event log (the SQS replacement, working)"
curl -sf http://localhost:8103/events | json

step "6. Query the lake with DuckDB (the Athena replacement)"
python3 lake/query.py "SELECT VISIT, VSTESTCD, round(avg(VSSTRESN),1) AS mean_value, count(*) AS n FROM read_csv_auto('/lake/sdtm/vs.csv') GROUP BY VISIT, VSTESTCD ORDER BY min(VISITNUM), VSTESTCD"

step "7. The sprinkle of AI: natural language -> NGSI-LD entity via the adaptive service"
echo "   Propose: construct entities (does not write to broker)"
ADAPTIVE_RESPONSE=$(curl -sf -X POST http://localhost:8106/construct -H 'Content-Type: application/json' -d '{
  "statement": "Participant P2201 completed the Week 8 visit at the Houston site on June 1st, 2026. Seated systolic blood pressure was 121 mmHg."
}')
echo "$ADAPTIVE_RESPONSE" | json

PROPOSAL_ID=$(echo "$ADAPTIVE_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['proposalId'])")
ENTITIES=$(echo "$ADAPTIVE_RESPONSE" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['entities']))")

echo
echo "   Commit: execute the proposal (requires PNE_ADAPTIVE_EXECUTE=true)"
echo "   Note: demo.sh shows propose path; for full commit see infra/scripts/prove-rule7.sh"

step "   Decision log and Rule 7 enforcement"
curl -sf http://localhost:8106/mode | python3 -c 'import json,sys; m=json.load(sys.stdin); print(f"  Mode: {m[\"mode\"]}, Execute enabled: {m[\"executeEnabled\"]}")'

step "Lake contents"
curl -sf http://localhost:8105/files | json
printf '\nDone. Open http://localhost:8080 for the web walkthrough.\n'
