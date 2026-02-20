# Fitness Bot — Operations Guide

Single-user Telegram bot that syncs Garmin Connect data and provides AI-powered run debriefs via Claude.

---

## Architecture

- **Bot process**: `python -m fitness` — Telegram bot + APScheduler (nightly Garmin sync)
- **VPS**: Debian-based, user `fitness`, service `fitness-bot` managed by systemd
- **Auth**: Garmin uses OAuth tokens (garth); Telegram token + Anthropic key in `.env`

---

## VPS Access

```bash
ssh fitness@<vps-ip>
```

Key-based auth. The `fitness` user has passwordless sudo for service control only.

---

## Standard Deploy (from local machine)

After pushing code changes, deploy to VPS:

```bash
ssh fitness@<vps-ip> "cd ~/fitness && git pull && .venv/bin/pip install -e . && sudo -n systemctl restart fitness-bot"
```

Check it started cleanly:

```bash
ssh fitness@<vps-ip> "journalctl -u fitness-bot --no-pager -n 50"
```

---

## Git Workflow

**Claude Code is responsible for commits and pushes.** Do not commit manually unless Claude is unavailable.

Standard commit flow after making changes:

```bash
git add <files>
git commit -m "type(scope): description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push
```

Then run the deploy command above.

---

## Local Development

```bash
cd ~/fitness   # or wherever the repo is cloned
source .venv/bin/activate
python -m fitness setup   # first-time or after session expiry
python -m fitness         # run bot locally
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
scp ~/.fitness/garmin_session/oauth1_token.json fitness@<vps-ip>:~/.fitness/garmin_session/
scp ~/.fitness/garmin_session/oauth2_token.json fitness@<vps-ip>:~/.fitness/garmin_session/

# Restart on VPS:
ssh fitness@<vps-ip> "sudo -n systemctl restart fitness-bot"
```

Tokens expire after several weeks to months. Re-run `python -m fitness setup` when they do.

---

## Service Management (on VPS)

```bash
# Restart
sudo -n systemctl restart fitness-bot

# Logs (live)
journalctl -u fitness-bot -f

# Logs (last 50 lines)
journalctl -u fitness-bot --no-pager -n 50
```

Note: `sudo -n` is required for non-interactive (SSH) sessions.

---

## Environment Variables

Stored in `~/fitness/.env` on the VPS. Required keys:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_ID=...   # your Telegram user ID (also used for error notifications)
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...             # optional — enables voice messages via Whisper
DATABASE_URL=sqlite:///./fitness.db
GARMIN_SYNC_HOUR=3             # UTC hour for nightly sync
```

---

## Error Reporting

Unhandled exceptions are sent directly to the owner via Telegram (using `TELEGRAM_ALLOWED_USER_ID`).
Garmin sync results (success or failure) are also reported via Telegram after `/sync`.

If the bot goes silent, check the logs:

```bash
ssh fitness@<vps-ip> "journalctl -u fitness-bot --no-pager -n 100"
```

---

## Bot Commands

| Command | Description |
|---|---|
| `/lastrun` | Debrief of most recent activity |
| `/debrief [id]` | Debrief a specific activity by ID |
| `/trends` | 30-day training summary |
| `/sync` | Trigger an on-demand Garmin sync |
| _(any text)_ | Free-form question answered with run context |
