# Fitness Bot — Operations Reference

> See `CLAUDE.md` for Claude Code workflow rules (TDD, commits, deploys).
> See `PROJECT_BRIEF.md` for architecture and codebase details.
> Use the `/commit` and `/deploy` skills for all commit and deploy operations.

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

The VPS IP is stored in the **local** `.env` as `VPS_IP`. SSH as `fitness` (key-based):

```bash
source .env
ssh fitness@$VPS_IP
```

The `fitness` user has passwordless sudo for exactly two commands:
- `sudo /usr/bin/systemctl restart fitness-bot`
- `sudo /usr/bin/systemctl status fitness-bot`

Note: extra flags (e.g. `--no-pager`) break the sudoers match — use the commands exactly as written above.
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
scp ~/.fitness/garmin_session/oauth1_token.json fitness@$VPS_IP:/home/fitness/.fitness/garmin_session/
scp ~/.fitness/garmin_session/oauth2_token.json fitness@$VPS_IP:/home/fitness/.fitness/garmin_session/

# Restart on VPS:
ssh fitness@$VPS_IP "sudo /usr/bin/systemctl restart fitness-bot"
```

Tokens expire after several weeks to months. Re-run `python -m fitness setup` when they do.

---

## Service Management (on VPS, as `fitness` user)

The `fitness` user has passwordless sudo for exactly these two `systemctl` commands. Do not add extra flags — they break the sudoers match.

```bash
# Restart
ssh fitness@$VPS_IP "sudo /usr/bin/systemctl restart fitness-bot"

# Status
ssh fitness@$VPS_IP "sudo /usr/bin/systemctl status fitness-bot"

# Logs (live) — no sudo needed for journalctl
ssh fitness@$VPS_IP "journalctl -u fitness-bot -f"

# Logs (last 50 lines)
ssh fitness@$VPS_IP "journalctl -u fitness-bot --no-pager -n 50"
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
ssh fitness@$VPS_IP "journalctl -u fitness-bot --no-pager -n 100"
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
