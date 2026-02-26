# Claude Code Docker Sandbox

A self-contained Docker environment that runs Claude Code against a GitHub repository with full permissions (no approval prompts). Claude clones the repo on startup, works autonomously, and pushes changes back via git.

## Prerequisites

- Docker + Docker Compose installed on the host
- A GitHub deploy key with **write** access to the target repo

## First-time setup

### 1. Create a GitHub deploy key

```bash
ssh-keygen -t ed25519 -C "claude-docker" -f ~/.ssh/claude_docker -N ""
cat ~/.ssh/claude_docker.pub
```

Go to your GitHub repo → **Settings → Deploy keys → Add deploy key**.
Paste the public key and check **Allow write access**.

### 2. Create your `.env.docker`

```bash
cp .env.docker.example .env.docker
```

Edit `.env.docker` and fill in:
- `GIT_REPO_URL` — SSH URL of the repo (e.g. `git@github.com:user/fitness.git`)
- `GIT_SSH_PRIVATE_KEY` — contents of `~/.ssh/claude_docker` (the private key)
- `PROJECT_*` — all variables your project's `.env` needs

For `GIT_SSH_PRIVATE_KEY`, paste the private key with literal newlines — the entrypoint handles it correctly.

### 3. Choose an authentication method

**Option A — API key** (direct Anthropic billing):

Set `ANTHROPIC_API_KEY=sk-ant-...` in `.env.docker`. No other changes needed.

**Option B — Claude account login** (uses your Claude.ai subscription):

1. Log in on the host machine: `claude login`
2. Leave `ANTHROPIC_API_KEY` commented out in `.env.docker`
3. In `docker-compose.yml`, replace `volumes: []` with:
   ```yaml
   volumes:
     - ~/.claude.json:/home/claude/.claude.json:ro
   ```

The container will use the OAuth session from your host `~/.claude.json`.

### 4. Build the image

```bash
docker compose build
```

## Usage

### Start the container

```bash
docker compose up -d
```

This starts the container in the background. It clones the repo, writes the project `.env`, and creates a detached screen session named `dev`. The container keeps running until you explicitly stop it — you can disconnect from SSH and reconnect later.

### Attach to the screen session

```bash
docker exec -it claude-fitness screen -r dev
```

From inside screen, run Claude in any window:

```bash
claude --dangerously-skip-permissions
```

Use normal screen shortcuts to manage windows:

| Shortcut | Action |
|---|---|
| `Ctrl+A c` | New window |
| `Ctrl+A n` / `Ctrl+A p` | Next / previous window |
| `Ctrl+A "` | List windows |
| `Ctrl+A d` | Detach (container keeps running) |

### Stop the container

```bash
docker compose down
```

### Non-interactive (one-shot) task

```bash
CLAUDE_PROMPT="Run tests and fix any failures, then commit and push." \
  docker compose run --rm claude
```

### Fresh session (re-clone)

Stop and remove the container, then start again:

```bash
docker compose down
docker compose up -d
```

The repo is re-cloned on each fresh start.

## How it works

1. **Entrypoint** (`docker-entrypoint.sh`) runs on container start:
   - Loads the SSH key into `ssh-agent`
   - Clones (or pulls) the git repo
   - Writes a `.env` file from `PROJECT_*` variables
   - Writes a permissive `~/.claude/settings.json`
   - Starts a detached `screen` session named `dev` and keeps the container alive
   - Attach any time with `docker exec -it claude-fitness screen -r dev`

2. **Permissions**: Claude is configured to auto-allow all Bash, file read/write, and search operations. No approval prompts.

3. **Secrets**: The Anthropic API key and SSH key live only in `.env.docker` (never committed). Project secrets are injected as `PROJECT_*` vars and written to the in-container `.env`.

## Security notes

- `.env.docker` contains sensitive keys — never commit it (it is gitignored)
- The deploy key should be scoped to a single repo
- The container runs as a non-root `claude` user
- No host filesystem is mounted — the container is fully isolated

## Deploying on the Hetzner VPS

Same steps as above. SSH into the server and:

```bash
ssh root@89.167.65.94
apt-get install -y docker.io docker-compose-plugin
git clone git@github.com:your-username/fitness.git /opt/claude-sandbox
cd /opt/claude-sandbox/docker
cp .env.docker.example .env.docker
# fill in .env.docker
docker compose build
docker compose run --rm claude
```
