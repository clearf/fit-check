#!/bin/bash
set -e
exec 2>&1  # redirect stderr to stdout so we can see errors

# ── Validate required environment variables ───────────────────────────────────
if [ -z "$GIT_REPO_URL" ]; then
  echo "ERROR: GIT_REPO_URL is not set (e.g. git@github.com:user/repo.git)" >&2
  exit 1
fi

# ── Configure git identity ────────────────────────────────────────────────────
git config --global user.email "${GIT_USER_EMAIL:-claude-docker@localhost}"
git config --global user.name "${GIT_USER_NAME:-Claude Docker}"

# ── Set up SSH key for git (if provided) ─────────────────────────────────────
# GIT_SSH_PRIVATE_KEY must be base64-encoded (to avoid env_file newline issues)
if [ -n "$GIT_SSH_PRIVATE_KEY" ]; then
  echo "$GIT_SSH_PRIVATE_KEY" | base64 -d > /home/claude/.ssh/id_ed25519
  chmod 600 /home/claude/.ssh/id_ed25519
  eval "$(ssh-agent -s)" > /dev/null
  ssh-add /home/claude/.ssh/id_ed25519 2>/dev/null
  echo "SSH key loaded."
fi

# ── Clone or update the repository ───────────────────────────────────────────
REPO_DIR="/home/claude/repo"

if [ -d "$REPO_DIR/.git" ]; then
  echo "Repository already exists — pulling latest..."
  git -C "$REPO_DIR" pull
else
  echo "Cloning $GIT_REPO_URL..."
  git clone "$GIT_REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"

# ── Write project .env file (if env vars are provided) ───────────────────────
# Any env var prefixed with PROJECT_ will be written to .env (prefix stripped)
ENV_FILE="$REPO_DIR/.env"
if env | grep -q '^PROJECT_'; then
  echo "Writing project .env from PROJECT_* environment variables..."
  > "$ENV_FILE"
  env | grep '^PROJECT_' | while IFS='=' read -r key value; do
    stripped_key="${key#PROJECT_}"
    echo "${stripped_key}=${value}" >> "$ENV_FILE"
  done
  echo ".env written."
fi

# ── Configure Claude Code for permissive / auto-accept operation ──────────────
CLAUDE_CONFIG_DIR="/home/claude/.claude"
mkdir -p "$CLAUDE_CONFIG_DIR"

cat > "$CLAUDE_CONFIG_DIR/settings.json" <<'EOF'
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Glob(*)",
      "Grep(*)"
    ],
    "deny": []
  }
}
EOF

# ── Configure Claude Code authentication ──────────────────────────────────────
# API key mode: if ANTHROPIC_API_KEY is set, write it to ~/.claude.json directly.
# Account login mode: omit ANTHROPIC_API_KEY and mount your host ~/.claude.json
#   as a volume (see docker-compose.yml). Claude Code will use your OAuth session.
if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "Using API key authentication."
  cat > "/home/claude/.claude.json" <<EOF
{
  "hasCompletedOnboarding": true,
  "primaryApiKey": "${ANTHROPIC_API_KEY}"
}
EOF
elif [ -f "/home/claude/.claude.json" ]; then
  echo "Using account login credentials from mounted ~/.claude.json."
else
  echo "WARNING: No ANTHROPIC_API_KEY set and no ~/.claude.json found." >&2
  echo "         Set ANTHROPIC_API_KEY in .env.docker, or mount your host" >&2
  echo "         ~/.claude.json into the container (see docker-compose.yml)." >&2
fi

# ── Launch ───────────────────────────────────────────────────────────────────
# Non-interactive: run Claude directly with a prompt and exit.
# Interactive: start a screen session — open new windows with Ctrl+A c and
#   run `claude --dangerously-skip-permissions` in each one.
if [ -n "$CLAUDE_PROMPT" ]; then
  echo "Running Claude Code non-interactively..."
  exec claude --dangerously-skip-permissions -p "$CLAUDE_PROMPT"
else
  echo "Starting detached screen session 'dev'..."
  screen -dmS dev
  echo "Attach with: docker exec -it claude-fitness screen -r dev"
  exec tail -f /dev/null
fi
