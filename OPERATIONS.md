# Fitness Bot — Operations Guide

Single-user Telegram bot that syncs Garmin Connect data and provides AI-powered run debriefs via Claude.

---

## Architecture

- **Bot process**: `python -m fitness` — Telegram bot + APScheduler (nightly Garmin sync)
- **VPS**: Debian-based, systemd service `fitness-bot`
- **Service user**: `fitness` (unprivileged); service files owned by root
- **App directory**: `/home/fitness/fitness/` (the git repo)
- **Virtualenv**: `/home/fitness/fitness/.venv/`
- **Database**: `/home/fitness/fitness/fitness.db` (SQLite, path from `DATABASE_URL` in `.env`)
- **Garmin tokens**: `/home/fitness/.fitness/garmin_session/`
- **Auth**: Garmin uses OAuth tokens (garth); Telegram token + Anthropic key in `.env`

---

## VPS Access

VPS IP: `89.167.65.94`. SSH as `fitness` (key-based, from Claude Code Docker container):

```bash
ssh fitness@89.167.65.94
```

The `fitness` user has passwordless sudo for exactly two commands:
- `sudo /usr/bin/systemctl restart fitness-bot`
- `sudo /usr/bin/systemctl status fitness-bot`

Note: extra flags (e.g. `--no-pager`) break the sudoers match — use the commands exactly as written above.

---

## Git Workflow

**Claude Code is responsible for commits and pushes.** Do not commit manually unless Claude is unavailable.

**Standard practice: every completed feature/fix is committed, pushed, and deployed immediately.**

Standard commit-push-deploy flow (run directly from Claude Code):

```bash
# 1. Commit
git add <files>
git commit -m "type(scope): description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# 2. Push
git push

# 3. Pull on VPS + restart + verify
ssh fitness@89.167.65.94 "cd /home/fitness/fitness && git pull && sudo /usr/bin/systemctl restart fitness-bot && sleep 3 && sudo /usr/bin/systemctl status fitness-bot"
```

If pip dependencies changed (new packages in `pyproject.toml`), install before restarting:

```bash
ssh fitness@89.167.65.94 "cd /home/fitness/fitness && .venv/bin/pip install -e . -q"
```

---

## Database Migrations

Schema changes are handled by `src/fitness/db/migrations.py` via `run_migrations()`, which is called automatically at bot startup (in `engine.py`). Migrations are idempotent — safe to restart multiple times.

No manual migration steps are needed after deploy. The new columns will be added on first startup if they don't already exist.

---

## Local Development

```bash
cd /Volumes/Storage/Users/clearf/Documents/repos/fitness
source .venv/bin/activate
python -m fitness setup   # first-time or after Garmin session expiry
python -m fitness         # run bot locally
```

Run tests:

```bash
.venv/bin/pytest tests/ \
  --ignore=tests/unit/test_scheduler.py \
  --ignore=tests/integration/test_api_activities.py \
  --ignore=tests/integration/test_api_sync.py \
  -q
# Expected: ~475 passed (the ignored files have pre-existing Pydantic V2 config errors)
```

---

## Garmin Authentication

Garmin auth uses OAuth tokens via the `garth` library (garminconnect 0.2.x).
Tokens are stored in `~/.fitness/garmin_session/` (`oauth1_token.json`, `oauth2_token.json`).

**Garmin's OAuth flow is blocked on VPS/datacenter IPs.** Always run setup locally:

```bash
# On local machine:
python -m fitness setup

# Copy tokens to VPS:
source .env
scp ~/.fitness/garmin_session/oauth1_token.json root@$VPS_IP:/home/fitness/.fitness/garmin_session/
scp ~/.fitness/garmin_session/oauth2_token.json root@$VPS_IP:/home/fitness/.fitness/garmin_session/
ssh root@$VPS_IP "chown fitness:fitness /home/fitness/.fitness/garmin_session/*.json"

# Restart on VPS:
ssh root@$VPS_IP "systemctl restart fitness-bot"
```

Tokens expire after several weeks to months. Re-run `python -m fitness setup` when they do.

---

## Service Management (on VPS, as root)

```bash
# Restart
systemctl restart fitness-bot

# Status
systemctl status fitness-bot

# Logs (live)
journalctl -u fitness-bot -f

# Logs (last 50 lines)
journalctl -u fitness-bot --no-pager -n 50
```

Service file location: `/etc/systemd/system/fitness-bot.service`

---

## Environment Variables

Stored in `/home/fitness/fitness/.env` on the VPS. Required keys:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_ID=...   # your Telegram user ID (also used for error notifications)
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...             # optional — enables voice messages via Whisper
DATABASE_URL=sqlite:///./fitness.db
GARMIN_SYNC_HOUR=3             # UTC hour for nightly sync
VPS_IP=...                     # only needed in local .env for deploy scripts
```

---

## Error Reporting

Unhandled exceptions are sent directly to the owner via Telegram (using `TELEGRAM_ALLOWED_USER_ID`).
Garmin sync results (success or failure) are also reported via Telegram after `/sync`.

If the bot goes silent, check the logs:

```bash
source .env
ssh root@$VPS_IP "journalctl -u fitness-bot --no-pager -n 100"
```

---

## Bot Commands

| Command | Description |
|---|---|
| `/lastrun` | Debrief of most recent activity |
| `/debrief [id]` | Debrief a specific activity by ID |
| `/trends` | 30-day training summary |
| `/sync` | Trigger an on-demand Garmin sync |
| `/clear` | Clear conversation history for the current run |
| `/clearall` | Clear all run conversation histories |
| _(any text)_ | Follow-up question in current run's conversation |
