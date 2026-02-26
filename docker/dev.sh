#!/bin/bash
# Usage:
#   ./dev.sh        — start (if needed) and attach to screen session
#   ./dev.sh stop   — stop the container

set -e

CONTAINER="claude-fitness"
SCREEN_SESSION="dev"

# ── Detect docker compose command ─────────────────────────────────────────────
if docker compose version &>/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE="docker-compose"
else
  echo "ERROR: Neither 'docker compose' nor 'docker-compose' found." >&2
  exit 1
fi

# ── Subcommands ───────────────────────────────────────────────────────────────
case "${1:-}" in
  stop)
    echo "Stopping $CONTAINER..."
    $COMPOSE down
    exit 0
    ;;
  "")
    ;;
  *)
    echo "Usage: $0 [stop]" >&2
    exit 1
    ;;
esac

# ── Start container if not already running ────────────────────────────────────
STATUS=$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || echo "false")
if [ "$STATUS" != "true" ]; then
  echo "Starting container..."
  $COMPOSE up -d
fi

# ── Wait briefly for entrypoint to create the screen session (fresh start) ────
for i in $(seq 1 5); do
  if docker exec "$CONTAINER" screen -list 2>/dev/null | grep -q "$SCREEN_SESSION"; then
    break
  fi
  sleep 1
done

# ── Attach (or create a new session if it doesn't exist) ──────────────────────
echo "Tip: use Ctrl+A d to detach (keeps session alive), not ^D"
if docker exec "$CONTAINER" screen -list 2>/dev/null | grep -q "$SCREEN_SESSION"; then
  exec docker exec -it "$CONTAINER" screen -rd "$SCREEN_SESSION"
else
  echo "No existing session — creating new screen session '$SCREEN_SESSION'..."
  exec docker exec -it "$CONTAINER" screen -S "$SCREEN_SESSION"
fi
