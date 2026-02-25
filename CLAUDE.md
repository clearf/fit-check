# fit-check — Claude Code Guide

> Read this file first. Then read `OPERATIONS.md` for deploy details and `PROJECT_BRIEF.md` for architecture deep-dives.

---

## Project Overview

A single-user Telegram bot that syncs Garmin Connect running data and generates AI-powered run debriefs via Claude. Owner sends `/lastrun` to Telegram and receives a markdown debrief with pace analysis, HR zones, bonk detection, Galloway detection, and matplotlib charts.

**Stack**: Python 3.9 (local) / 3.12 (VPS), SQLite (SQLModel), python-telegram-bot 21, APScheduler, Claude (Anthropic), garminconnect 0.2.8, fitparse.

---

## Development Philosophy

### Test-Driven Development (Required)

**Tests must be written alongside implementation — never after.**

The purpose of tests is to independently verify correctness, not to confirm that code already written happens to work. Follow this process:

1. **Before writing a function**: write the test that defines its expected behavior
2. **Write the implementation** to make the test pass
3. **Refactor** if needed, keeping tests green
4. Tests and implementation may be written in the same session, but tests must act as an independent specification — not a post-facto rubber stamp

If a task doesn't obviously require new tests (e.g. pure refactor, config change), state why explicitly before proceeding.

**Run tests before every commit** (see `/commit` skill). A commit must not be made if tests are failing.

### Test command

```bash
.venv/bin/pytest tests/ \
  --ignore=tests/unit/test_scheduler.py \
  --ignore=tests/integration/test_api_activities.py \
  --ignore=tests/integration/test_api_sync.py \
  -q
# Expected: ~475+ passed
# The ignored files have pre-existing Pydantic V2 config errors — do not fix incidentally
```

---

## Workflow Rules

### Commits & Deploys

- **Claude is responsible for all commits and pushes.** Do not ask the user to commit manually.
- After completing a task, automatically run `/commit` (tests → commit → push).
- To deploy to the VPS after a commit, run `/deploy`.
- Use the skills: `/commit` and `/deploy` — do not inline their logic.

### Commit Message Format

```
type(scope): short description

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

---

## Key Architectural Facts

See `PROJECT_BRIEF.md` for full details. Critical gotchas:

- `garminconnect 0.2.8` has **breaking changes** from 0.1.x — see PROJECT_BRIEF.md §Garmin API
- Garmin's OAuth flow is **blocked on datacenter IPs** — always run `python -m fitness setup` locally
- FIT file downloads from `download_activity(ORIGINAL)` are **zip archives**, not raw FIT bytes — unzip in memory before passing to fitparse
- Lazy imports in `_backfill()` and `_nightly_sync()` — patch at the *source* module, not the caller

---

## Local Development

```bash
source .venv/bin/activate
python -m fitness setup   # first-time or after Garmin session expiry
python -m fitness         # run bot locally
```

---

## VPS & Deploy

See `OPERATIONS.md` for full deploy steps, service management, and Garmin token refresh.

- VPS IP: stored in local `.env` as `VPS_IP`
- SSH as `root` (key-based): `source .env && ssh root@$VPS_IP`
- Service: `systemd` unit `fitness-bot`, requires root to restart
