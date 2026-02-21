# fit-check — Project Brief

> **Purpose of this document**: Orient a new Claude Code session quickly. Read this first, then `OPERATIONS.md` for deploy procedures.

---

## What This Is

A single-user Telegram bot that syncs Garmin Connect running data and generates AI-powered run debriefs. The owner sends `/lastrun` to Telegram and gets back a markdown debrief with pace analysis, Galloway walk/run detection, bonk/cardiac drift detection, HR zone breakdown, and sleep/HRV context — plus matplotlib charts.

**Stack**: Python 3.9, SQLite (SQLModel), python-telegram-bot 21, APScheduler, Claude (Anthropic), Whisper (OpenAI optional), garminconnect 0.2.8, fitparse.

**Deployed on**: Hetzner Cloud VPS, Debian, systemd service `fitness-bot`, user `fitness`.

---

## Repository Layout

```
src/fitness/
├── __main__.py          # Entrypoint: starts Telegram bot + APScheduler
├── config.py            # Pydantic Settings (reads .env)
├── ai/
│   ├── claude_client.py     # Thin async wrapper over anthropic SDK
│   └── whisper_client.py    # Thin async wrapper over openai SDK
├── analysis/
│   ├── bonk.py              # Bonk/cardiac drift detection from HR timeseries
│   ├── galloway.py          # Galloway run/walk interval detection from splits
│   ├── heart_rate.py        # HR zone distribution, avg, max
│   ├── pace.py              # Pace formatting utilities
│   ├── run_report.py        # RunReport dataclass + build_run_report()
│   ├── segments.py          # RunSegment/GallowaySegments typed dataclasses
│   └── timeseries.py        # Timeseries smoothing / resampling
├── api/
│   ├── main.py              # FastAPI app factory
│   └── routes/
│       ├── activities.py    # GET /activities, GET /activities/{id}
│       └── sync.py          # POST /sync/activity/{id}
├── bot/
│   ├── app.py               # build_bot_app(): wires handlers + bot_data
│   ├── handlers.py          # /lastrun, /debrief, /trends, /sync, freeform text
│   └── voice_handler.py     # Voice message → Whisper → query → Claude
├── db/
│   ├── engine.py            # get_engine() singleton
│   └── migrations.py        # SQLModel.metadata.create_all() on startup
├── garmin/
│   ├── auth.py              # GarminAuth: OAuth2 via garth, tokens on disk
│   ├── client.py            # GarminClient: async wrapper over garminconnect
│   ├── fit_parser.py        # parse_fit_file(): .fit → list of datapoint dicts
│   ├── normalizer.py        # normalize_*(): raw API dicts → model field dicts
│   └── sync_service.py      # GarminSyncService: orchestrates fetch + DB upsert
├── models/
│   ├── activity.py          # Activity, ActivityDatapoint, ActivitySplit
│   ├── sync.py              # SyncLog
│   └── wellness.py          # SleepRecord, HRVRecord
├── prompts/
│   ├── charts.py            # make_run_overview_chart(), make_elevation_chart()
│   ├── debrief.py           # build_debrief_prompt/system_prompt()
│   ├── trends.py            # build_trends_prompt()
│   └── voice.py             # build_voice_query_prompt()
└── scripts/
    ├── backfill.py          # python -m fitness backfill --days N
    └── setup.py             # python -m fitness setup (Garmin OAuth flow)
```

---

## Key Architectural Facts

### Garmin API (garminconnect 0.2.8 — important, breaking changes from 0.1.x)
- `get_activity()` → **removed**; use `get_activity_evaluation()` (returns nested `summaryDTO` schema)
- `get_activity_typed_splits()` → **removed**; use `get_activity_splits()` (returns `{"lapDTOs": [...]}`)
- `get_activities(activitytype=)` → **kwarg removed**; we filter client-side by `activityType.typeKey`
- `download_activity(dl_fmt=ORIGINAL)` → returns a **zip archive**, not raw FIT bytes. We unzip in memory before passing to fitparse. (This bit us in production — see git log `eb985fb`.)

### Two Garmin API response schemas (both handled by `normalizer.py`)
| Field | `get_activities()` list item | `get_activity_evaluation()` detail |
|---|---|---|
| Activity type | `activityType.typeKey` (top-level) | `activityTypeDTO.typeKey` (top-level) |
| Performance fields | Flat top-level | Nested under `summaryDTO` |
| Time format | `"2026-02-18 19:22:38"` (space) | `"2026-02-18T19:22:38.0"` (ISO 8601) |

### lapDTOs split schema (real Garmin data)
Items have `intensityType: ACTIVE | RECOVERY | WARMUP | COOLDOWN` (not `splitType: RUN/WALK`).
Fields are `distance` and `duration` (not `totalDistance` / `totalElapsedTime`).
Normalizer maps: `ACTIVE/WARMUP → run_segment`, `RECOVERY/COOLDOWN → walk_segment`.

### Garmin Auth
OAuth2 tokens stored in `~/.fitness/garmin_session/` (`oauth1_token.json`, `oauth2_token.json`).
**Garmin's OAuth flow is blocked on datacenter IPs** — always run `python -m fitness setup` locally and `scp` the token files to the VPS.

---

## Test Suite

**371 tests, 86% overall coverage.** Run with:

```bash
source .venv/bin/activate
pytest                                        # all tests
pytest --cov=src/fitness --cov-report=term-missing  # with coverage
pytest tests/unit/                            # unit only
pytest tests/integration/                    # integration only
```

### Test structure
```
tests/
├── fixtures/                    # Real scrubbed Garmin API responses (PII removed)
│   ├── garmin_activity_summary.json   # get_activity_evaluation() response (nested summaryDTO)
│   ├── garmin_activity_list_item.json # get_activities() list item (flat schema)
│   ├── garmin_activity_splits.json    # get_activity_splits() with lapDTOs (33 laps)
│   ├── garmin_typed_splits.json       # Synthetic splits for integration tests (intensityType schema)
│   ├── garmin_sleep.json              # Real sleep data, PII scrubbed
│   └── garmin_hrv.json                # Hand-crafted (no real HRV for capture date)
├── unit/
│   ├── test_garmin_auth.py
│   ├── test_garmin_client.py          # Includes zip-extraction regression test
│   ├── test_normalizer.py             # Tests against real fixture values
│   ├── test_fit_parser.py
│   ├── test_claude_client.py
│   ├── test_whisper_client.py
│   ├── test_prompts.py                # debrief, trends, voice prompts
│   ├── test_backfill.py
│   ├── test_scheduler.py
│   ├── test_bonk.py, test_galloway.py, test_heart_rate.py, etc.
│   └── test_models.py
└── integration/
    └── test_sync_service.py           # In-memory SQLite, AsyncMock client
```

### Important mocking patterns

**Lazy imports** (functions import inside their body): `_backfill()` and `_nightly_sync()` both import `GarminClient` and `GarminSyncService` inside the function. Patch at the *source* module, not the caller:
```python
# WRONG: patch("fitness.scripts.backfill.GarminClient")  ← AttributeError
# RIGHT:
patch("fitness.garmin.client.GarminClient", ...)
patch("fitness.garmin.sync_service.GarminSyncService", ...)
```

**FIT download mock**: `download_activity` returns a **zip**, not raw bytes. `FAKE_FIT_BYTES` in tests is built with `_make_zip(b"...")`. Tests that check the byte pipeline must not mock `parse_fit_file` away — capture what's written to disk instead.

**Coroutine cleanup**: When mocking `asyncio.run`, the captured coroutine must be `.close()`d immediately to avoid `RuntimeWarning: coroutine was never awaited`.

---

## Current Coverage Gaps

Modules with meaningful uncovered code:

| Module | Coverage | Notes |
|---|---|---|
| `__main__.py` | 0% | CLI entrypoint; would need subprocess or import-with-mock testing |
| `scripts/setup.py` | 0% | Interactive OAuth flow; hard to test without real Garmin |
| `bot/app.py` | 0% | PTB Application wiring; needs full PTB Application mock |
| `bot/handlers.py` | 71% | Missing: error path in `/debrief`, freeform text handler, chart sending |
| `bot/voice_handler.py` | 80% | Missing: error paths in Whisper call and audio download |
| `api/routes/sync.py` | 77% | Missing: error branches in POST /sync/activity/{id} |
| `garmin/normalizer.py` | 89% | Missing: walk/cooldown edge cases (line 82), error path in normalize_sleep (173), fallback date in normalize_hrv (205-206) |
| `analysis/bonk.py` | 92% | Missing: edge cases at lines 85, 111, 153, 182, 213-216 |
| `analysis/segments.py` | 89% | Missing: edge cases at lines 48, 55, 74, 109, 159-163, 177 |
| `scripts/backfill.py` | 93% | Missing: lines 60, 70, 74, 102, 124 |

The bot handlers and app.py are the most valuable gaps. They require a `PTB Application` mock pattern — the `build_bot_app()` function wires everything together and the handlers read from `context.bot_data`.

---

## Known Issues Fixed (recent git history)

| Commit | Issue |
|---|---|
| `eb985fb` | `FitParseError: Invalid .FIT File Header` — ORIGINAL download is a zip, not raw FIT |
| `ba06afa` | Integration tests using stale fixture values (wrong activityId, name, HR, split schema) |
| `dfa0778` | Added test coverage for claude_client, whisper_client, prompts, backfill, scheduler |
| `85c928a` | Replaced hand-crafted fixtures with real scrubbed Garmin API responses |
| `4dcd691` | Fixture capture script (`scripts/capture_fixtures.py`) |
| `e46fb1f` | `KeyError: startTimeGMT` — normalizer assumed flat schema, real API is nested |
| `9566d92` | Three garminconnect 0.2.8 API breakages (method renames, format changes) |

---

## Possible Next Work

Roughly in priority order:

1. **Bot handler test coverage** — `handlers.py` at 71% is the largest meaningful gap. Needs a PTB `Application`/`Update`/`ContextTypes` mock harness. The `/lastrun` success path, error path, chart-sending path are the key cases.

2. **`normalizer.py` edge cases** — line 82 (walk/cooldown split type fallthrough), lines 164-165/173 (normalize_sleep error handling), lines 205-206 (normalize_hrv fallback date). Small targeted tests.

3. **`api/routes/sync.py` error branches** — FastAPI TestClient is already a dependency, just needs wiring for the sync route error cases.

4. **`analysis/segments.py` and `bonk.py` gaps** — pure analysis functions, easy to add targeted unit tests for edge cases (empty input, single-point, all-walk, etc.).

5. **Pydantic v2 deprecation warning** — `config.py` uses class-based Config (Pydantic v1 style). Should migrate to `model_config = ConfigDict(...)` to suppress the warning and future-proof.

6. **`__main__.py` / `bot/app.py`** — These are the glue entrypoints. Low-value to test heavily but the 0% is a signal that startup failure modes aren't exercised at all.

---

## Deploy Reminder

After any code change: push to GitHub, then SSH deploy:

```bash
ssh fitness@<vps-ip> "cd ~/fitness && git pull && .venv/bin/pip install -e . && sudo -n systemctl restart fitness-bot"
ssh fitness@<vps-ip> "journalctl -u fitness-bot --no-pager -n 30"
```

See `OPERATIONS.md` for full details including Garmin token refresh procedure.
