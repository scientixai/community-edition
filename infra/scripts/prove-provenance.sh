#!/usr/bin/env bash
# Prove provenance tracking across write paths WP-01, WP-11, WP-04, and WP-08.
#
# Verifies:
# - WP-01: USDM load attaches provenance to broker entities
# - WP-11: Seed batches attach provenance to broker entities
# - WP-04: Transform writes lake objects with provenance sidecars
# - WP-08: Projection writes lake objects with provenance sidecars
#
# Run: ./infra/scripts/prove-provenance.sh
# Prerequisites: stack must be up (docker compose up -d)

set -euo pipefail

BROKER_URL="${PNE_BROKER_URL:-http://localhost:9090}"
USDM_URL="${PNE_USDM_URL:-http://localhost:8101}"
PROJECTION_URL="${PNE_PROJECTION_URL:-http://localhost:8102}"
LAKE_URL="${PNE_LAKE_URL:-http://localhost:8105}"
# Broker resolves the Link context from inside the compose network; use web:8080 not localhost.
CONTEXT_URL="${PNE_CONTEXT_URL:-http://web:8080/context/pne-context.jsonld}"
LAKE_DIR="${PNE_LAKE_DIR:-./lake/data}"

echo "[prove-provenance] Waiting for services..."
until curl -sf "${BROKER_URL}/q/health" > /dev/null 2>&1; do sleep 1; done
until curl -sf "${USDM_URL}/health" > /dev/null 2>&1; do sleep 1; done
until curl -sf "${PROJECTION_URL}/health" > /dev/null 2>&1; do sleep 1; done
until curl -sf "${LAKE_URL}/health" > /dev/null 2>&1; do sleep 1; done

echo ""
echo "============================================================"
echo "WP-01: USDM load attaches provenance to broker entities"
echo "============================================================"

LOAD_RESPONSE=$(curl -sf -X POST "${USDM_URL}/load" -H "Content-Type: application/json" -d '{}')
STUDY_ID=$(echo "$LOAD_RESPONSE" | python3 -c "import sys, json; ids = json.load(sys.stdin)['entityIds']; print(next((i for i in ids if 'Study:' in i), ''))")

if [ -z "$STUDY_ID" ]; then
  echo "[prove-provenance] ERROR: No Study entity ID found in load response"
  exit 1
fi

STUDY_ENTITY=$(curl -sf -X GET "${BROKER_URL}/ngsi-ld/v1/entities/${STUDY_ID}" \
  -H "Accept: application/json" \
  -H "Link: <${CONTEXT_URL}>; rel=\"http://www.w3.org/ns/json-ld#context\"; type=\"application/ld+json\"")

WP01_SOURCE=$(echo "$STUDY_ENTITY" | python3 -c "import sys, json; e = json.load(sys.stdin); print(e.get('dataSource', {}).get('value', ''))")
WP01_LOADER=$(echo "$STUDY_ENTITY" | python3 -c "import sys, json; e = json.load(sys.stdin); print(e.get('dataLoader', {}).get('value', ''))")
WP01_TIME=$(echo "$STUDY_ENTITY" | python3 -c "import sys, json; e = json.load(sys.stdin); print(e.get('loadedAt', {}).get('value', ''))")

echo "  dataSource: ${WP01_SOURCE:-[MISSING]}"
echo "  dataLoader: ${WP01_LOADER:-[MISSING]}"
echo "  loadedAt:   ${WP01_TIME:-[MISSING]}"

if [ -z "$WP01_SOURCE" ] || [ -z "$WP01_LOADER" ] || [ -z "$WP01_TIME" ]; then
  echo "[prove-provenance] FAIL: WP-01 provenance properties missing"
  exit 1
fi
echo "[prove-provenance] ✓ WP-01 PASS"

echo ""
echo "============================================================"
echo "WP-11: Seed batches attach provenance to broker entities"
echo "============================================================"

python3 pipeline/lib/seed_helper.py infra/seed/enrollment-batch.json > /dev/null
PARTICIPANT_ENTITY=$(curl -sf -X GET "${BROKER_URL}/ngsi-ld/v1/entities/urn:ngsi-ld:Participant:cardio-118-hou-07-p2201" \
  -H "Accept: application/json" \
  -H "Link: <${CONTEXT_URL}>; rel=\"http://www.w3.org/ns/json-ld#context\"; type=\"application/ld+json\"")

WP11_SOURCE=$(echo "$PARTICIPANT_ENTITY" | python3 -c "import sys, json; e = json.load(sys.stdin); print(e.get('dataSource', {}).get('value', ''))")
WP11_LOADER=$(echo "$PARTICIPANT_ENTITY" | python3 -c "import sys, json; e = json.load(sys.stdin); print(e.get('dataLoader', {}).get('value', ''))")
WP11_TIME=$(echo "$PARTICIPANT_ENTITY" | python3 -c "import sys, json; e = json.load(sys.stdin); print(e.get('loadedAt', {}).get('value', ''))")

echo "  dataSource: ${WP11_SOURCE:-[MISSING]}"
echo "  dataLoader: ${WP11_LOADER:-[MISSING]}"
echo "  loadedAt:   ${WP11_TIME:-[MISSING]}"

if [ -z "$WP11_SOURCE" ] || [ -z "$WP11_LOADER" ] || [ -z "$WP11_TIME" ]; then
  echo "[prove-provenance] FAIL: WP-11 provenance properties missing"
  exit 1
fi

if [[ "$WP11_SOURCE" != seed-* ]] || [ "$WP11_LOADER" != "demo-seed" ]; then
  echo "[prove-provenance] FAIL: WP-11 provenance values incorrect"
  exit 1
fi
echo "[prove-provenance] ✓ WP-11 PASS"

echo ""
echo "============================================================"
echo "WP-08: Projection writes lake objects with provenance sidecars"
echo "============================================================"

curl -sf -X POST "${PROJECTION_URL}/project" -H "Content-Type: application/json" -d '{}' > /dev/null

SIDECAR_TS="${LAKE_DIR}/datasetjson/.pne-provenance/ts.json.json"
if [ ! -f "$SIDECAR_TS" ]; then
  echo "[prove-provenance] FAIL: WP-08 sidecar not found at $SIDECAR_TS"
  exit 1
fi

WP08_SOURCE=$(python3 -c "import json; s = json.load(open('$SIDECAR_TS')); print(s.get('source', ''))")
WP08_LOADER=$(python3 -c "import json; s = json.load(open('$SIDECAR_TS')); print(s.get('loader', ''))")
WP08_TIME=$(python3 -c "import json; s = json.load(open('$SIDECAR_TS')); print(s.get('time', ''))")

echo "  source: ${WP08_SOURCE:-[MISSING]}"
echo "  loader: ${WP08_LOADER:-[MISSING]}"
echo "  time:   ${WP08_TIME:-[MISSING]}"

if [ -z "$WP08_SOURCE" ] || [ -z "$WP08_LOADER" ] || [ -z "$WP08_TIME" ]; then
  echo "[prove-provenance] FAIL: WP-08 provenance sidecar incomplete"
  exit 1
fi
echo "[prove-provenance] ✓ WP-08 PASS"

echo ""
echo "============================================================"
echo "WP-04: Transform writes lake objects with provenance sidecars"
echo "============================================================"

python3 pipeline/lib/seed_helper.py infra/seed/visit-batch-baseline.json > /dev/null
sleep 3

tries=0
until curl -sf "${LAKE_URL}/files" | grep -q "sdtm/vs.csv"; do
  tries=$((tries + 1))
  [ "$tries" -gt 20 ] && { echo "[prove-provenance] FAIL: Transform did not produce SDTM within 40s"; exit 1; }
  sleep 2
done

SIDECAR_VS="${LAKE_DIR}/sdtm/.pne-provenance/vs.csv.json"
if [ ! -f "$SIDECAR_VS" ]; then
  echo "[prove-provenance] FAIL: WP-04 sidecar not found at $SIDECAR_VS"
  exit 1
fi

WP04_SOURCE=$(python3 -c "import json; s = json.load(open('$SIDECAR_VS')); print(s.get('source', ''))")
WP04_LOADER=$(python3 -c "import json; s = json.load(open('$SIDECAR_VS')); print(s.get('loader', ''))")
WP04_TIME=$(python3 -c "import json; s = json.load(open('$SIDECAR_VS')); print(s.get('time', ''))")

echo "  source: ${WP04_SOURCE:-[MISSING]}"
echo "  loader: ${WP04_LOADER:-[MISSING]}"
echo "  time:   ${WP04_TIME:-[MISSING]}"

if [ -z "$WP04_SOURCE" ] || [ -z "$WP04_LOADER" ] || [ -z "$WP04_TIME" ]; then
  echo "[prove-provenance] FAIL: WP-04 provenance sidecar incomplete"
  exit 1
fi
echo "[prove-provenance] ✓ WP-04 PASS"

echo ""
echo "============================================================"
echo "✓ ALL PROVENANCE CHECKS PASSED"
echo "============================================================"
echo "  WP-01: USDM load → broker entities with provenance"
echo "  WP-11: Seed batches → broker entities with provenance"
echo "  WP-08: Projection → lake objects with provenance sidecars"
echo "  WP-04: Transform → lake objects with provenance sidecars"
echo ""

exit 0
