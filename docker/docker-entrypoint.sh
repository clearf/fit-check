#!/bin/bash
set -e
exec 2>&1  # redirect stderr to stdout so we can see errors

# ── Validate required environment variables ───────────────────────────────────
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set." >&2
  exit 1
fi

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

# ── Configure Claude Code to skip login and use API key directly ──────────────
# Write ~/.claude.json to tell Claude Code to use the API key directly,
# bypassing the login flow entirely.
cat > "/home/claude/.claude.json" <<EOF
{
  "hasCompletedOnboarding": true,
  "primaryApiKey": "${ANTHROPIC_API_KEY}"
}
EOF

# ── Launch Claude Code ────────────────────────────────────────────────────────
# If a CLAUDE_PROMPT is set, run non-interactively with --print
# Otherwise, drop into interactive mode
if [ -n "$CLAUDE_PROMPT" ]; then
  echo "Running Claude Code non-interactively..."
  exec claude --dangerously-skip-permissions -p "$CLAUDE_PROMPT"
else
  echo "Starting Claude Code in interactive mode..."
  exec claude --dangerously-skip-permissions
fi
