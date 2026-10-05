#!/usr/bin/env bash
# Proof checklist: no secret-shaped values in committed tree examples.
#
# Scans text sources for common secret shapes and for bare Scorpio
# password literals that should be env references instead.
# Run from the repository root:
#   ./scripts/prove-no-secret-shapes.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
fail() { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }
ok() { echo -e "${GREEN}[OK]${NC} $*"; }

echo "prove-no-secret-shapes: scanning committed text files"
echo

# Anthropic key prefix split so this script does not match itself.
ANT_PREFIX='sk-ant'
ANT_SHAPE="${ANT_PREFIX}-"

mapfile -t FILES < <(find . -type f \
  \( -name '*.py' -o -name '*.yaml' -o -name '*.yml' -o -name '*.md' \
     -o -name '*.json' -o -name '*.jsonld' -o -name '*.sh' -o -name '*.example' \
     -o -name '*.toml' -o -name '*.txt' -o -name 'Dockerfile*' -o -name '.env*' \) \
  ! -path './.git/*' ! -path './lake/data/*' ! -path './node_modules/*' \
  ! -path './scripts/prove-no-secret-shapes.sh')

# 1) Anthropic key shape must not appear (even as a fake example)
hits="$(grep -nF "$ANT_SHAPE" "${FILES[@]}" 2>/dev/null || true)"
if [[ -n "$hits" ]]; then
  echo "$hits"
  fail "found ${ANT_PREFIX}- key shape; use empty ANTHROPIC_API_KEY= in examples"
fi
ok "no ${ANT_PREFIX}- key shapes"

# 2) Common cloud/key shapes
hits="$(grep -nEi 'AKIA[0-9A-Z]{16}|BEGIN (RSA |OPENSSH )?PRIVATE KEY' "${FILES[@]}" 2>/dev/null || true)"
if [[ -n "$hits" ]]; then
  echo "$hits"
  fail "found private-key or AWS access-key shape"
fi
ok "no private-key / AKIA shapes"

# 3) Bare compose password literals for Scorpio (must use env reference)
hits="$(grep -nE 'POSTGRES_PASSWORD:[[:space:]]*ngb[[:space:]]*$|DBPASS:[[:space:]]*ngb[[:space:]]*$' \
    docker-compose.yaml docker-compose.local-run.yaml 2>/dev/null || true)"
if [[ -n "$hits" ]]; then
  echo "$hits"
  fail "bare Scorpio password literal in compose; use SCORPIO_PG_PASSWORD env reference"
fi
ok "compose passwords use env references"

# 4) .env.example must expose empty ANTHROPIC_API_KEY=
if ! grep -qE '^ANTHROPIC_API_KEY=$' .env.example; then
  fail ".env.example must contain empty ANTHROPIC_API_KEY="
fi
ok ".env.example has empty ANTHROPIC_API_KEY="

# 5) Allow-list / watch-type config files exist (moved out of hardcode-only)
test -f adaptive/allowed.json || fail "missing adaptive/allowed.json"
test -f pipeline/subscriptions/watched-types.json || fail "missing watched-types.json"
python3 -c 'import json; json.load(open("adaptive/allowed.json")); json.load(open("pipeline/subscriptions/watched-types.json"))'
ok "allow-list and watch-type config files present and valid JSON"

echo
ok "all secret-shape checks passed"
