# fit-check — Project Brief

> **Purpose of this document**: Deep architecture reference. Read `CLAUDE.md` first, then this file for architecture details and `OPERATIONS.md` for VPS operations.

---

## What This Is

A single-user Telegram bot that syncs Garmin Connect running data and generates AI-powered run debriefs. The owner sends `/lastrun` to Telegram and gets back a markdown debrief with pace analysis, Galloway walk/run detection, bonk/cardiac drift detection, HR zone breakdown, and sleep/HRV context — plus matplotlib charts.

**Stack**: Python 3.9 (local), Python 3.12 (VPS), SQLite (SQLModel), python-telegram-bot 21, APScheduler, Claude (Anthropic), Whisper (OpenAI optional), garminconnect 0.2.8, fitparse.

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
│   ├── bonk.py              # detect_bonk(), detect_bonk_per_segment()
│   ├── galloway.py          # Galloway run/walk interval detection from splits
│   ├── heart_rate.py        # HR zone distribution, avg, max
│   ├── pace.py              # format_pace() utility
│   ├── run_report.py        # RunReport dataclass + build_run_report()
│   ├── segments.py          # LapSegment, build_lap_segments(), build_mile_segments()
│   └── timeseries.py        # TimeseriesPoint, datapoints_to_timeseries()
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
│   ├── charts.py            # make_run_overview_chart() — see Chart Design below
│   ├── debrief.py           # build_debrief_prompt/system_prompt()
│   ├── trends.py            # build_trends_prompt()
│   └── voice.py             # build_voice_query_prompt()
└── scripts/
    ├── backfill.py          # python -m fitness backfill --days N
    └── setup.py             # python -m fitness setup (Garmin OAuth flow)

scripts/
└── preview_chart.py         # Local chart preview from FIT fixture (no DB needed)
                             # Loads tests/fixtures/sample_activity.fit for real
                             # per-second pace variation. Run with:
                             # source .venv/bin/activate && python scripts/preview_chart.py
                             # open /tmp/preview_chart.png
```

---

## Chart Design (make_run_overview_chart)

The overview chart is the primary visual output of `/lastrun`. It is a 2-panel stacked figure (12×9 inches, dark theme `#1a1a2e`):

### Panel 1 — Pace over time
- **X-axis**: elapsed minutes
- **Pace line**: rolling-median smoothed (window=20), masked above `MAX_DISPLAY_PACE_MIN_MI` (11:00/mi) so walk/rest segments simply vanish rather than spiking. Y-axis hard-capped at 11:00/mi.
- **Y-axis**: inverted (faster = higher), bounded to the 5th–95th percentile of `run_segment` laps only (excludes walk, warmup, cooldown, tiny laps from bounds calculation)
- **Background shading**: teal (run), dim teal (warmup/cooldown), grey (walk/recovery), purple (drill micro-laps < `MIN_LAP_DISPLAY_M` = 50m)
- **Segment header labels** (top of panel):
  - Run/warmup/cooldown ≥ 0.1 mi: `"Run 3\n0.50mi\n7:42/mi"` in light grey
  - Walk: name only, rotated 90°, dim grey — always shown (no crowding suppression)
  - Crowding suppression for run labels: skipped if too close to previous run label
- **Cross-rep average lines**: one dashed colored line per rep group (groups clustered by distance ±5%), spanning first rep to last rep. Color-coded from `REP_COLORS` palette. Label floats on the line at a staggered x position (cycles through 25/45/62/78% of span) with a semi-transparent dark bbox.
- **Elevation overlay**: dim gold filled area on a right Y-axis (twinx), scaled to occupy the bottom ~20% of the panel so it doesn't obscure the pace line.
- **Bonk markers**: vertical red dashed lines at bonk onset times, with a small "bonk" label at the bottom.

### Panel 2 — HR over time
- HR line in coral red, alpha 0.85
- HR zone threshold lines (Z1/Z2 through Z4/Z5) as dim dashed horizontal lines

### Key constants (charts.py)
```python
MIN_LAP_DISPLAY_M = 50.0          # laps shorter than this → "Drills" shading
REP_DISTANCE_TOLERANCE = 0.05     # 5% distance tolerance for rep grouping
MIN_REPS_FOR_REFERENCE = 2        # minimum reps to draw a cross-rep line
MAX_DISPLAY_PACE_MIN_MI = 11.0    # pace mask + Y-axis hard cap
REP_COLORS = ["#ffd700", "#ff9f43", "#ff6b9d", "#a29bfe", "#55efc4", "#fdcb6e"]
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
Items have `intensityType: ACTIVE | RECOVERY | WARMUP | COOLDOWN`.
Fields are `distance` and `duration` (not `totalDistance` / `totalElapsedTime`).
Normalizer maps: `ACTIVE → run_segment`, `RECOVERY → walk_segment`, `WARMUP → warmup_segment`, `COOLDOWN → cooldown_segment`.

**start_elapsed_seconds**: computed in `sync_service._upsert_splits()` by parsing each lap's `startTimeGMT` (ISO 8601 string) relative to the activity's `start_time_utc`. The normalizer cannot do this alone — it doesn't know the activity start time.

### LapSegment dataclass (analysis/segments.py)
```python
@dataclass
class LapSegment:
    label: str              # "Warmup", "Run 1", "Walk 1", "Cooldown"
    split_type: str         # run_segment | walk_segment | warmup_segment | cooldown_segment
    start_elapsed_s: int
    end_elapsed_s: int
    duration_seconds: float
    distance_meters: float
    avg_pace_s_per_km: float
    avg_hr: float
    hr_zone_distribution: Dict[int, float]

    def is_active(self) -> bool:
        return self.split_type in ("run_segment", "warmup_segment", "cooldown_segment")
```

`build_lap_segments(splits, timeseries)` builds these from stored `ActivitySplit` rows. Uses explicit type priority (warmup_segment/cooldown_segment) first, then heuristics as fallback for older data.

### Segment-aware bonk detection (analysis/bonk.py)
`detect_bonk_per_segment(points, lap_segments)` filters timeseries to only `is_active()` windows before running the bonk algorithm, eliminating false positives during recovery intervals.

### Garmin Auth
OAuth2 tokens stored in `~/.fitness/garmin_session/` (`oauth1_token.json`, `oauth2_token.json`).
**Garmin's OAuth flow is blocked on datacenter IPs** — always run `python -m fitness setup` locally and `scp` the token files to the VPS.

---

## Test Suite

**421 tests.** Run with:

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
├── fixtures/
│   ├── garmin_activity_summary.json   # get_activity_evaluation() response (nested summaryDTO)
│   ├── garmin_activity_list_item.json # get_activities() list item (flat schema)
│   ├── garmin_activity_splits.json    # get_activity_splits() with lapDTOs (33 laps, 8×800m)
│   ├── garmin_typed_splits.json       # Synthetic splits for integration tests
│   ├── garmin_sleep.json              # Real sleep data, PII scrubbed
│   ├── garmin_hrv.json                # Hand-crafted
│   └── sample_activity.fit            # Real FIT file (130KB) for the 8×800m workout
├── unit/
│   ├── test_lap_segments.py           # LapSegment, build_lap_segments()
│   ├── test_segment_aware_bonk.py     # detect_bonk_per_segment()
│   ├── test_lap_charts.py             # make_run_overview_chart(), _group_rep_laps()
│   ├── test_normalizer.py
│   ├── test_prompts.py
│   └── ... (other unit tests)
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

**FIT download mock**: `download_activity` returns a **zip**, not raw bytes. `FAKE_FIT_BYTES` in tests is built with `_make_zip(b"...")`.

**Coroutine cleanup**: When mocking `asyncio.run`, the captured coroutine must be `.close()`d immediately to avoid `RuntimeWarning: coroutine was never awaited`.

---

## Known Issues Fixed (recent git history)

| Commit | Issue |
|---|---|
| `7fbbf66` | Remove standalone elevation chart — now overlaid on pace panel |
| `381ba2a` | `start_elapsed_seconds = 0` for all splits — sync_service now parses `startTimeGMT` relative to activity start |
| `30165cb` | Full chart redesign: lap-segment aware, real FIT timeseries, elevation overlay, bonk markers, cross-rep average lines |
| `eb985fb` | `FitParseError: Invalid .FIT File Header` — ORIGINAL download is a zip, not raw FIT |
| `9566d92` | Three garminconnect 0.2.8 API breakages (method renames, format changes) |

---

## Possible Next Work

Roughly in priority order:


1. **Target pace overlay on charts (Phase 2)** — Garmin structured workouts include per-step target pace ranges, linked to laps via `wktStepIndex` on each `lapDTO`. The `associatedWorkoutId` is already stored in `raw_summary_json`. Implementation requires: (a) fetching the workout definition via `get_workout(workoutId)` during sync, (b) storing step targets (pace low/high, HR zone) keyed by `wktStepIndex`, (c) rendering a grey target band behind the actual pace line in `make_run_overview_chart()` — matching the Garmin Connect web UI.

2. **Re-sync existing activities** — After the `start_elapsed_seconds` fix (commit `381ba2a`), any previously-synced activities in the DB have all splits at t=0. A `/sync` command from Telegram (or `python -m fitness backfill`) will re-ingest them correctly.

3. **Bot handler test coverage** — `handlers.py` at 71% is the largest meaningful gap. Needs a PTB `Application`/`Update`/`ContextTypes` mock harness.

4. **Pydantic v2 deprecation warning** — `config.py` uses class-based Config (Pydantic v1 style). Should migrate to `model_config = ConfigDict(...)`.

5. **`normalizer.py` edge cases** — line 82 (walk/cooldown split type fallthrough), normalize_sleep error handling, normalize_hrv fallback date.

---

## Deploy

Use the `/deploy` skill. See `OPERATIONS.md` for full details including Garmin token refresh procedure.
