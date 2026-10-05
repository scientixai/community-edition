#!/usr/bin/env bash
# Proof checklist: every ${VAR} interpolation in docker-compose*.yaml
# appears as a key line in .env.example (VAR= or #VAR=).
#
# Run from the repository root:
#   ./scripts/prove-env-example-compose-parity.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
fail() { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }
ok() { echo -e "${GREEN}[OK]${NC} $*"; }

echo "prove-env-example-compose-parity: compose \${VAR} vs .env.example"
echo

test -f .env.example || fail "missing .env.example"
shopt -s nullglob
COMPOSE_FILES=(docker-compose*.yaml docker-compose*.yml)
[[ ${#COMPOSE_FILES[@]} -gt 0 ]] || fail "no docker-compose*.yaml files found"

# Collect unique VAR names from ${VAR} and ${VAR:-default} forms.
mapfile -t VARS < <(
  grep -hoE '\$\{[A-Za-z_][A-Za-z0-9_]*' "${COMPOSE_FILES[@]}" \
    | sed 's/^\${//' \
    | sort -u
)

[[ ${#VARS[@]} -gt 0 ]] || fail "no \${VAR} interpolations found in compose files"

missing=()
for var in "${VARS[@]}"; do
  # Key line: optional leading #, exact name, then =
  if ! grep -qE "^#?${var}=" .env.example; then
    missing+=("$var")
  fi
done

echo "compose files: ${COMPOSE_FILES[*]}"
echo "vars found (${#VARS[@]}): ${VARS[*]}"
echo

if [[ ${#missing[@]} -gt 0 ]]; then
  printf '%s\n' "${missing[@]}"
  fail "missing from .env.example (need VAR= or #VAR=): ${missing[*]}"
fi

ok "every compose \${VAR} has a key line in .env.example"
echo
ok "all env-example compose parity checks passed"
