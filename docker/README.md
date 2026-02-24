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
- `ANTHROPIC_API_KEY` — your Anthropic API key
- `GIT_REPO_URL` — SSH URL of the repo (e.g. `git@github.com:user/fitness.git`)
- `GIT_SSH_PRIVATE_KEY` — contents of `~/.ssh/claude_docker` (the private key)
- `PROJECT_*` — all variables your project's `.env` needs

For `GIT_SSH_PRIVATE_KEY`, paste the private key with literal newlines — the entrypoint handles it correctly.

### 3. Build the image

```bash
docker compose build
```

## Usage

### Interactive session

```bash
docker compose run --rm claude
```

Claude launches in interactive mode inside the container. It has cloned the repo and written the project `.env`. Type your task and Claude will work autonomously.

### Non-interactive (one-shot) task

Set `CLAUDE_PROMPT` in `.env.docker` (or inline):

```bash
CLAUDE_PROMPT="Run tests and fix any failures, then commit and push." \
  docker compose run --rm claude
```

### Restart a fresh session (re-clone)

```bash
docker compose run --rm claude
```

Each `run` starts a fresh container. The repo is re-cloned (or pulled if the image layer cached it) every time.

## How it works

1. **Entrypoint** (`docker-entrypoint.sh`) runs on container start:
   - Loads the SSH key into `ssh-agent`
   - Clones (or pulls) the git repo
   - Writes a `.env` file from `PROJECT_*` variables
   - Writes a permissive `~/.claude/settings.json`
   - Launches `claude --dangerously-skip-permissions`

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
