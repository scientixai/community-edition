#!/usr/bin/env bash
# NR-010 blackhole prove: verify CE runtime egress with external domains blackholed
#
# This script proves that the CE stack can perform seed + load + query operations
# with uri.etsi.org, top.scientix.ai, w3id.org, and schema.org mapped to 127.0.0.1.
#
# Prerequisites:
# - Docker images already present (run with --pull never)
# - No stack currently running
#
# Exit codes:
# - 0: Prove passed (stack worked AND blackhole curls failed as expected)
# - Non-zero: Prove failed
set -euo pipefail
cd "$(dirname "$0")/../.."

BROKER=${BROKER:-http://localhost:9090}
COMPOSE_FILES="-f docker-compose.yaml -f docker-compose.nr010-blackhole.yml"
BLACKHOLED_HOSTS=("uri.etsi.org" "top.scientix.ai" "w3id.org" "schema.org")

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
error() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; }
success() { printf '\033[1;32m%s\033[0m\n' "$*"; }

cleanup() {
  step "Cleanup: stopping stack"
  docker compose $COMPOSE_FILES down -v 2>/dev/null || true
}

trap cleanup EXIT

step "NR-010 Blackhole Prove: Starting"
echo "This proves CE runtime can operate with external domains blackholed."
echo

step "1. Bring up stack with blackhole overlay (--pull never)"
if ! docker compose $COMPOSE_FILES up -d --build --pull never; then
  error "Failed to bring up stack with blackhole overlay"
  exit 1
fi

step "2. Wait for services to become healthy"
echo "Waiting for web service health check..."
tries=0
until curl -sf http://localhost:8080/health >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -gt 60 ]; then
    error "Web service did not become healthy within 120s"
    docker compose $COMPOSE_FILES logs web
    exit 1
  fi
  sleep 2
done
success "Web service is healthy"

echo "Waiting for broker readiness..."
tries=0
until curl -sf "$BROKER/q/health" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -gt 60 ]; then
    error "Broker did not become ready within 120s"
    docker compose $COMPOSE_FILES logs scorpio
    exit 1
  fi
  sleep 2
done
success "Broker is ready"

step "3. Run minimal load path: enrollment batch upsert"
if ! curl -sf -X POST "$BROKER/ngsi-ld/v1/entityOperations/upsert?options=update" \
  -H 'Content-Type: application/ld+json' \
  --data-binary @infra/seed/enrollment-batch.json \
  -o /dev/null -w 'HTTP %{http_code}\n'; then
  error "Enrollment batch upsert failed"
  docker compose $COMPOSE_FILES logs scorpio
  exit 1
fi
success "Enrollment batch upsert succeeded"

step "4. Query entities with Link header pointing to local context"
ENTITY_ID="urn:ngsi-ld:Participant:cardio-118-hou-07-p2201"
if ! curl -sf "$BROKER/ngsi-ld/v1/entities/$ENTITY_ID" \
  -H 'Accept: application/json' \
  -H 'Link: <http://web:8080/context/pne-context.jsonld>; rel="http://www.w3.org/ns/json-ld#context"; type="application/ld+json"' \
  -o /dev/null; then
  error "Entity query failed"
  docker compose $COMPOSE_FILES logs scorpio
  exit 1
fi
success "Entity query succeeded"

step "5. Verify blackhole: curl from inside scorpio container must fail"
SCORPIO_CONTAINER=$(docker compose $COMPOSE_FILES ps -q scorpio)
if [ -z "$SCORPIO_CONTAINER" ]; then
  error "Could not find scorpio container"
  exit 1
fi

BLACKHOLE_PASS=true
for host in "${BLACKHOLED_HOSTS[@]}"; do
  echo -n "Testing $host... "
  if docker exec "$SCORPIO_CONTAINER" curl -sf --max-time 3 "http://$host" >/dev/null 2>&1; then
    error "BLACKHOLE BREACH: $host is reachable (should be blackholed)"
    BLACKHOLE_PASS=false
  else
    success "blocked (as expected)"
  fi
done

if [ "$BLACKHOLE_PASS" != true ]; then
  error "Blackhole verification failed: at least one host was reachable"
  exit 1
fi

step "NR-010 Blackhole Prove: PASS"
success "✓ Stack operated with seed + query using local context"
success "✓ All external domains blocked (uri.etsi.org, top.scientix.ai, w3id.org, schema.org)"
echo
echo "Harness PASS (this run). Stack seed/load/query succeeded with blackholed domains."
exit 0
