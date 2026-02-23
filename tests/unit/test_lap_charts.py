"""
Tests for lap-segment-based charts.

Chart design:
  - 2 tall panels stacked: pace over time (top), HR over time (bottom)
  - Background shading by segment type
  - Tiny laps (< MIN_LAP_DISPLAY_M) collapsed into a "Drills" region
  - Median rep pace reference line for repeated same-distance active reps
  - X-axis in minutes elapsed
  - Caption includes activity name and date
"""
from datetime import datetime
from typing import List, Optional

import pytest

from fitness.analysis.bonk import BonkEvent
from fitness.analysis.galloway import GallowaySegments
from fitness.analysis.run_report import RunReport
from fitness.analysis.segments import LapSegment, RunSegment
from fitness.analysis.timeseries import TimeseriesPoint
from fitness.models.activity import Activity
from fitness.prompts.charts import (
    MIN_LAP_DISPLAY_M,
    _group_rep_laps,
    make_run_overview_chart,
    make_elevation_chart,
)


# ─── Factories ────────────────────────────────────────────────────────────────

def make_activity(
    name: str = "Morning Run",
    distance_meters: float = 8046.72,
    duration_seconds: float = 2520.0,
    start_time_utc: Optional[datetime] = None,
) -> Activity:
    return Activity(
        garmin_activity_id="99999",
        name=name,
        activity_type="running",
        start_time_utc=start_time_utc or datetime(2026, 2, 18, 19, 0, 0),
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
    )


def make_lap_segment(
    label: str,
    split_type: str = "run_segment",
    start_elapsed_s: int = 0,
    duration_seconds: float = 600.0,
    distance_meters: float = 1600.0,
    avg_pace_s_per_km: float = 375.0,
    avg_hr: float = 145.0,
    target_pace_slow_s_per_km: Optional[float] = None,
    target_pace_fast_s_per_km: Optional[float] = None,
) -> LapSegment:
    return LapSegment(
        label=label,
        split_type=split_type,
        start_elapsed_s=start_elapsed_s,
        end_elapsed_s=start_elapsed_s + int(duration_seconds),
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        avg_pace_s_per_km=avg_pace_s_per_km,
        avg_hr=avg_hr,
        hr_zone_distribution={1: 0.1, 2: 0.3, 3: 0.3, 4: 0.25, 5: 0.05},
        target_pace_slow_s_per_km=target_pace_slow_s_per_km,
        target_pace_fast_s_per_km=target_pace_fast_s_per_km,
    )


def make_timeseries(n_points: int = 200, with_elevation: bool = True) -> List[TimeseriesPoint]:
    pts = []
    for i in range(n_points):
        t = i * 15
        pts.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=140 + (i % 20),
            pace_seconds_per_km=360.0 + (i % 30),
            speed_ms=2.78,
            distance_meters=float(i) * 41.7,
            elevation_meters=(50.0 + i * 0.1) if with_elevation else None,
        ))
    return pts


# Typical 8×800m interval workout lap structure
INTERVAL_LAP_SEGMENTS = [
    make_lap_segment("Warmup",   "warmup_segment",  0,     300,  800.0,  avg_pace_s_per_km=375.0, avg_hr=120.0),
    make_lap_segment("Run 1",    "run_segment",     300,   227,  800.0,  avg_pace_s_per_km=284.0, avg_hr=145.0),
    make_lap_segment("Walk 1",   "walk_segment",    527,   180,  250.0,  avg_pace_s_per_km=720.0, avg_hr=126.0),
    make_lap_segment("Run 2",    "run_segment",     707,   231,  800.0,  avg_pace_s_per_km=289.0, avg_hr=144.0),
    make_lap_segment("Walk 2",   "walk_segment",    938,   180,  250.0,  avg_pace_s_per_km=720.0, avg_hr=126.0),
    make_lap_segment("Run 3",    "run_segment",     1118,  235,  800.0,  avg_pace_s_per_km=294.0, avg_hr=150.0),
    make_lap_segment("Walk 3",   "walk_segment",    1353,  180,  250.0,  avg_pace_s_per_km=720.0, avg_hr=130.0),
    make_lap_segment("Cooldown", "cooldown_segment",1533,  249,  163.0,  avg_pace_s_per_km=1531.0, avg_hr=99.0),
]

SIMPLE_LAP_SEGMENTS = [
    make_lap_segment("Warmup",  "warmup_segment",  0,    300,  800.0),
    make_lap_segment("Run 1",   "run_segment",     300,  3600, 9000.0),
    make_lap_segment("Cooldown","cooldown_segment", 3900, 300,  600.0),
]


def make_report(
    lap_segments: Optional[List[LapSegment]] = None,
    timeseries: Optional[List[TimeseriesPoint]] = None,
    bonk_events: Optional[List[BonkEvent]] = None,
    with_elevation: bool = True,
    duration_seconds: float = 4500.0,
) -> RunReport:
    return RunReport(
        activity=make_activity(duration_seconds=duration_seconds),
        timeseries=timeseries if timeseries is not None else make_timeseries(with_elevation=with_elevation),
        mile_segments=[],
        lap_segments=lap_segments if lap_segments is not None else SIMPLE_LAP_SEGMENTS,
        bonk_events=bonk_events or [],
        cardiac_drift=None,
        galloway=GallowaySegments(
            is_galloway=False,
            run_segment_count=1,
            walk_segment_count=0,
            avg_run_pace_s_per_km=360.0,
            avg_walk_pace_s_per_km=None,
            avg_run_hr=155.0,
            avg_walk_hr=None,
        ),
    )


# ─── PNG output sanity ────────────────────────────────────────────────────────

class TestChartOutputFormat:
    def test_returns_bytes_and_caption(self):
        report = make_report()
        result = make_run_overview_chart(report)
        assert isinstance(result, tuple) and len(result) == 2
        png_bytes, caption = result
        assert isinstance(png_bytes, bytes)
        assert isinstance(caption, str)

    def test_png_magic_bytes(self):
        report = make_report()
        png_bytes, _ = make_run_overview_chart(report)
        assert png_bytes[:4] == b'\x89PNG'

    def test_caption_contains_activity_name(self):
        report = make_report()
        _, caption = make_run_overview_chart(report)
        assert "Morning Run" in caption

    def test_no_crash_with_empty_timeseries(self):
        report = make_report(timeseries=[])
        png_bytes, _ = make_run_overview_chart(report)
        assert png_bytes[:4] == b'\x89PNG'

    def test_no_crash_with_empty_lap_segments(self):
        report = make_report(lap_segments=[])
        png_bytes, _ = make_run_overview_chart(report)
        assert png_bytes[:4] == b'\x89PNG'

    def test_no_crash_with_single_segment(self):
        segs = [make_lap_segment("Run 1", "run_segment", 0, 3600, 9000.0)]
        report = make_report(lap_segments=segs)
        png_bytes, _ = make_run_overview_chart(report)
        assert png_bytes[:4] == b'\x89PNG'

    def test_no_crash_with_interval_workout(self):
        report = make_report(lap_segments=INTERVAL_LAP_SEGMENTS)
        png_bytes, _ = make_run_overview_chart(report)
        assert png_bytes[:4] == b'\x89PNG'

    def test_produces_nontrivial_png(self):
        report = make_report(lap_segments=INTERVAL_LAP_SEGMENTS)
        png_bytes, _ = make_run_overview_chart(report)
        assert len(png_bytes) > 10_000


# ─── MIN_LAP_DISPLAY_M constant ───────────────────────────────────────────────

class TestMinLapDisplayConstant:
    def test_constant_exists_and_is_positive(self):
        assert isinstance(MIN_LAP_DISPLAY_M, (int, float))
        assert MIN_LAP_DISPLAY_M > 0

    def test_constant_is_at_least_50m(self):
        # Tiny GPS-artifact laps (8m, 23m) should be suppressed
        assert MIN_LAP_DISPLAY_M >= 50.0


# ─── Rep grouping helper ──────────────────────────────────────────────────────

class TestGroupRepLaps:
    """_group_rep_laps() identifies sets of active laps with matching distances
    (within tolerance) — these are the reps in an interval workout."""

    def test_returns_list(self):
        result = _group_rep_laps(INTERVAL_LAP_SEGMENTS)
        assert isinstance(result, list)

    def test_finds_800m_reps(self):
        # 3 active laps all at 800m → should be grouped
        groups = _group_rep_laps(INTERVAL_LAP_SEGMENTS)
        rep_distances = [g[0].distance_meters for g in groups if len(g) >= 2]
        assert any(abs(d - 800.0) < 50 for d in rep_distances)

    def test_single_laps_not_grouped(self):
        # Warmup and cooldown are unique distances — not grouped as reps
        groups = _group_rep_laps(INTERVAL_LAP_SEGMENTS)
        # All groups should have >= 2 members (singletons filtered out)
        for g in groups:
            assert len(g) >= 2

    def test_non_interval_run_returns_empty(self):
        # A simple warmup + single long run + cooldown has no repeated reps
        groups = _group_rep_laps(SIMPLE_LAP_SEGMENTS)
        assert groups == []

    def test_empty_input(self):
        assert _group_rep_laps([]) == []

    def test_all_walk_segments_returns_empty(self):
        segs = [
            make_lap_segment("Walk 1", "walk_segment", 0, 180, 250.0),
            make_lap_segment("Walk 2", "walk_segment", 180, 180, 250.0),
        ]
        assert _group_rep_laps(segs) == []


# ─── Elevation chart ──────────────────────────────────────────────────────────

class TestElevationChart:
    def test_returns_png_with_elevation(self):
        report = make_report(with_elevation=True)
        result = make_elevation_chart(report)
        assert result is not None
        png_bytes, caption = result
        assert png_bytes[:4] == b'\x89PNG'
        assert "Morning Run" in caption

    def test_returns_none_without_elevation(self):
        report = make_report(with_elevation=False)
        assert make_elevation_chart(report) is None

    def test_bonk_markers_do_not_crash(self):
        bonk = BonkEvent(
            elapsed_seconds_onset=750,
            pre_bonk_pace_s_per_km=360.0,
            bonk_pace_s_per_km=600.0,
            pace_drop_pct=0.67,
            pre_bonk_hr=148.0,
            peak_hr=168.0,
            recovered=False,
        )
        report = make_report(bonk_events=[bonk], with_elevation=True)
        result = make_elevation_chart(report)
        assert result is not None
        assert result[0][:4] == b'\x89PNG'


# ─── Target pace bands ────────────────────────────────────────────────────────

class TestTargetPaceBands:
    """Target pace band overlay: grey fill behind pace line for laps with targets."""

    def test_no_crash_with_no_targets(self):
        """Laps without target fields render without error."""
        segs = [make_lap_segment("Run 1", "run_segment", 0, 227, 800.0)]
        report = make_report(lap_segments=segs)
        png, _ = make_run_overview_chart(report)
        assert png[:4] == b'\x89PNG'

    def test_no_crash_with_targets(self):
        """Laps with target pace fields render without error and produce real content."""
        seg = make_lap_segment(
            "Run 1", "run_segment", 0, 227, 800.0,
            target_pace_slow_s_per_km=295.1,   # 4:55/km — slow end
            target_pace_fast_s_per_km=282.6,   # 4:42/km — fast end
        )
        report = make_report(lap_segments=[seg])
        png, _ = make_run_overview_chart(report)
        assert png[:4] == b'\x89PNG'
        assert len(png) > 10_000

    def test_no_crash_mixed_targets(self):
        """Some laps have targets, some don't — both render without error."""
        segs = [
            make_lap_segment("Warmup",   "warmup_segment",   0,   300, 800.0),
            make_lap_segment(
                "Run 1", "run_segment", 300, 227, 800.0,
                target_pace_slow_s_per_km=295.1,
                target_pace_fast_s_per_km=282.6,
            ),
            make_lap_segment("Walk 1",   "walk_segment",     527, 180, 250.0),
            make_lap_segment(
                "Run 2", "run_segment", 707, 231, 800.0,
                target_pace_slow_s_per_km=295.1,
                target_pace_fast_s_per_km=282.6,
            ),
            make_lap_segment("Cooldown", "cooldown_segment", 938, 249, 163.0),
        ]
        report = make_report(lap_segments=segs)
        png, _ = make_run_overview_chart(report)
        assert png[:4] == b'\x89PNG'
        assert len(png) > 10_000

    def test_no_crash_interval_workout_with_targets(self):
        """Full interval workout with target bands on all run segments."""
        segs_with_targets = []
        for seg in INTERVAL_LAP_SEGMENTS:
            if seg.split_type == "run_segment":
                segs_with_targets.append(make_lap_segment(
                    seg.label, seg.split_type, seg.start_elapsed_s,
                    seg.duration_seconds, seg.distance_meters,
                    avg_pace_s_per_km=seg.avg_pace_s_per_km,
                    avg_hr=seg.avg_hr,
                    target_pace_slow_s_per_km=295.1,
                    target_pace_fast_s_per_km=282.6,
                ))
            else:
                segs_with_targets.append(seg)
        report = make_report(lap_segments=segs_with_targets)
        png, _ = make_run_overview_chart(report)
        assert png[:4] == b'\x89PNG'
        assert len(png) > 10_000

    def test_no_crash_empty_timeseries_with_targets(self):
        """Empty timeseries + targets doesn't crash."""
        seg = make_lap_segment(
            "Run 1", "run_segment", 0, 227, 800.0,
            target_pace_slow_s_per_km=295.1,
            target_pace_fast_s_per_km=282.6,
        )
        report = make_report(lap_segments=[seg], timeseries=[])
        png, _ = make_run_overview_chart(report)
        assert png[:4] == b'\x89PNG'
