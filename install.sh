#!/bin/sh
# Community Edition runtime installer.
#
#   curl -fsSL https://raw.githubusercontent.com/scientixai/community-edition/main/install.sh | sh
#
# Checks Docker, fetches a pinned release, brings the stack up, and
# waits for the broker. No cloud account, no other dependencies.
#
# Environment overrides:
#   PNE_VERSION        release to install (default: the version this script shipped with)
#   PNE_REPO           GitHub repo slug (default: scientixai/community-edition)
#   PNE_DIR            install directory (default: ./pne-community-edition)
#   PNE_SOURCE         "release" (default) downloads a tagged tarball;
#                      "local" installs from the directory containing this script
#   SCORPIO_HOST_PORT  host port for broker health check (default: 9090)
#   BROKER_HEALTH_URL  full URL override for broker health check
set -eu

PNE_VERSION="${PNE_VERSION:-0.1.2}"
PNE_REPO="${PNE_REPO:-scientixai/community-edition}"
PNE_DIR="${PNE_DIR:-./pne-community-edition}"
PNE_SOURCE="${PNE_SOURCE:-release}"
SCORPIO_HOST_PORT="${SCORPIO_HOST_PORT:-9090}"
BROKER_HEALTH_URL="${BROKER_HEALTH_URL:-http://localhost:${SCORPIO_HOST_PORT}/q/health}"

say()  { printf '\033[1m[pne]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[pne]\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Prerequisites -----------------------------------------------------------
command -v docker >/dev/null 2>&1 \
  || fail "Docker is required. Install it from https://docs.docker.com/get-docker/ and re-run."
docker info >/dev/null 2>&1 \
  || fail "Docker is installed but the daemon is not reachable. Start Docker and re-run."
docker compose version >/dev/null 2>&1 \
  || fail "Docker Compose v2 is required (the 'docker compose' subcommand). Update Docker and re-run."

case "$(uname -m)" in
  arm64|aarch64)
    say "Apple Silicon / arm64 detected: the Scorpio broker image is amd64-only."
    say "Enable 'Use Rosetta for x86_64/amd64 emulation' in Docker Desktop if the broker is slow to start."
    ;;
esac

# 2. Fetch -------------------------------------------------------------------
if [ "$PNE_SOURCE" = "local" ]; then
  PNE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
  say "Installing from local checkout: $PNE_DIR"
else
  [ -e "$PNE_DIR/docker-compose.yaml" ] && fail "$PNE_DIR already contains an install. Run 'docker compose up -d' there, or remove it first."
  command -v curl >/dev/null 2>&1 || fail "curl is required to download the release."
  url="https://github.com/$PNE_REPO/archive/refs/tags/v$PNE_VERSION.tar.gz"
  say "Downloading $url"
  mkdir -p "$PNE_DIR"
  curl -fsSL "$url" | tar -xz -C "$PNE_DIR" --strip-components=1 \
    || fail "Download failed. Check the version tag (v$PNE_VERSION) exists on github.com/$PNE_REPO."
fi

cd "$PNE_DIR"

# 3. Bring the stack up ------------------------------------------------------
say "Pulling prebuilt images where available..."
docker compose pull --ignore-buildable 2>/dev/null || docker compose pull 2>/dev/null || true

say "Starting the stack (compose builds any image that could not be pulled)..."
docker compose up -d

# 4. Wait for the broker -----------------------------------------------------
say "Waiting for the broker (this is the JVM, give it a moment)..."
tries=0
until curl -fs "$BROKER_HEALTH_URL" >/dev/null 2>&1; do
  tries=$((tries + 1))
  [ "$tries" -gt 60 ] && fail "Broker did not become healthy in 5 minutes. Inspect: docker compose logs scorpio"
  sleep 5
done

say "Broker is up: 'Profile in-memory activated', no message bus, no cloud."
say ""
say "Open the walkthrough:   http://localhost:8080"
say "Or run the terminal demo: cd $PNE_DIR && ./infra/scripts/demo.sh"
say "First-run setup wizard:  http://localhost:8080/setup.html"
