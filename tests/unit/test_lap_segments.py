"""
Tests for lap-based segment builder.

build_lap_segments() uses ActivitySplit records (stored from Garmin lapDTOs)
to produce LapSegment objects that reflect the actual workout structure
(Warmup / Run 1 / Rest 1 / … / Cooldown) rather than geographic miles.
"""
import pytest
from typing import List

from fitness.analysis.segments import LapSegment, build_lap_segments
from fitness.analysis.timeseries import TimeseriesPoint
from fitness.models.activity import ActivitySplit


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_split(
    split_index: int,
    split_type: str,
    start_elapsed_seconds: int,
    duration_seconds: float,
    distance_meters: float,
    avg_hr: float = 140.0,
    avg_pace_seconds_per_km: float = 360.0,
    total_ascent_meters: float = 0.0,
) -> ActivitySplit:
    s = ActivitySplit(
        id=split_index,
        activity_id=1,
        user_id=1,
        split_index=split_index,
        split_type=split_type,
        start_elapsed_seconds=start_elapsed_seconds,
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        avg_hr=avg_hr,
        avg_pace_seconds_per_km=avg_pace_seconds_per_km,
        total_ascent_meters=total_ascent_meters,
    )
    return s


def make_timeseries_for_splits(splits: List[ActivitySplit]) -> List[TimeseriesPoint]:
    """Build a synthetic timeseries that spans all splits."""
    pts = []
    dist = 0.0
    for sp in splits:
        end_t = sp.start_elapsed_seconds + int(sp.duration_seconds)
        step = 5
        for t in range(sp.start_elapsed_seconds, end_t, step):
            speed = sp.distance_meters / sp.duration_seconds if sp.duration_seconds > 0 else 0.0
            pace = (1000.0 / speed) if speed > 0 else None
            elapsed_in_split = t - sp.start_elapsed_seconds
            pts.append(TimeseriesPoint(
                elapsed_seconds=t,
                heart_rate=int(sp.avg_hr) if sp.avg_hr else None,
                pace_seconds_per_km=pace,
                speed_ms=speed,
                distance_meters=dist + elapsed_in_split * speed,
                elevation_meters=50.0,
            ))
        dist += sp.distance_meters
    return pts


# ─── Typical structured workout ───────────────────────────────────────────────

TYPICAL_SPLITS = [
    make_split(0, "run_segment",  0,    300,   800.0,  avg_hr=120.0, avg_pace_seconds_per_km=375.0),  # Warmup
    make_split(1, "run_segment",  300,  1800,  4828.0, avg_hr=155.0, avg_pace_seconds_per_km=373.0),  # Long run
    make_split(2, "walk_segment", 2100, 300,   300.0,  avg_hr=130.0, avg_pace_seconds_per_km=1000.0), # Walk
    make_split(3, "run_segment",  2400, 300,   800.0,  avg_hr=118.0, avg_pace_seconds_per_km=375.0),  # Cooldown
]


class TestBuildLapSegments:
    def test_returns_one_segment_per_split(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert len(segs) == 4

    def test_segment_is_lap_segment_type(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        for s in segs:
            assert isinstance(s, LapSegment)

    def test_labels_warmup_first(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[0].label == "Warmup"

    def test_labels_cooldown_last(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[-1].label == "Cooldown"

    def test_labels_run_segments_sequentially(self):
        # Two active run splits in the middle should be "Run 1", "Run 2"
        splits = [
            make_split(0, "run_segment",  0,   300,  800.0),  # Warmup
            make_split(1, "run_segment",  300, 600,  1600.0), # Run 1
            make_split(2, "walk_segment", 900, 120,  100.0),  # Walk 1
            make_split(3, "run_segment",  1020, 600, 1600.0), # Run 2
            make_split(4, "run_segment",  1620, 300, 800.0),  # Cooldown
        ]
        segs = build_lap_segments(splits, [])
        labels = [s.label for s in segs]
        assert labels == ["Warmup", "Run 1", "Walk 1", "Run 2", "Cooldown"]

    def test_labels_walk_segments_sequentially(self):
        splits = [
            make_split(0, "run_segment",  0,   600,  1600.0),
            make_split(1, "walk_segment", 600, 120,  100.0),
            make_split(2, "run_segment",  720, 600,  1600.0),
            make_split(3, "walk_segment", 1320, 120, 100.0),
            make_split(4, "run_segment",  1440, 600, 1600.0),
        ]
        segs = build_lap_segments(splits, [])
        walk_labels = [s.label for s in segs if "Walk" in s.label]
        assert walk_labels == ["Walk 1", "Walk 2"]

    def test_split_type_preserved(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[0].split_type == "run_segment"
        assert segs[2].split_type == "walk_segment"

    def test_distance_meters_preserved(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[0].distance_meters == pytest.approx(800.0)
        assert segs[1].distance_meters == pytest.approx(4828.0)

    def test_duration_seconds_preserved(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[0].duration_seconds == pytest.approx(300.0)

    def test_avg_pace_preserved_from_split(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        # Walk segment pace should be the stored avg_pace
        assert segs[2].avg_pace_s_per_km == pytest.approx(1000.0)

    def test_avg_hr_preserved_from_split(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[0].avg_hr == pytest.approx(120.0)

    def test_distance_display_miles(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        # 800m ≈ 0.497 miles
        assert segs[0].distance_miles == pytest.approx(800.0 / 1609.344, rel=1e-3)

    def test_empty_splits_returns_empty(self):
        segs = build_lap_segments([], [])
        assert segs == []

    def test_single_run_segment_labeled_run_1(self):
        splits = [make_split(0, "run_segment", 0, 1800, 5000.0)]
        segs = build_lap_segments(splits, [])
        assert segs[0].label == "Run 1"

    def test_hr_zone_distribution_computed_from_timeseries(self):
        ts = make_timeseries_for_splits(TYPICAL_SPLITS)
        segs = build_lap_segments(TYPICAL_SPLITS, ts)
        # All HR points in the warmup split are 120 bpm → low zone
        warmup_seg = segs[0]
        assert isinstance(warmup_seg.hr_zone_distribution, dict)
        assert set(warmup_seg.hr_zone_distribution.keys()) == {1, 2, 3, 4, 5}
        assert abs(sum(warmup_seg.hr_zone_distribution.values()) - 1.0) < 0.01

    def test_hr_zone_distribution_empty_when_no_timeseries(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        # Without timeseries, zones should be all zeros
        for seg in segs:
            assert all(v == 0.0 for v in seg.hr_zone_distribution.values())

    def test_start_elapsed_seconds_matches_split(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[0].start_elapsed_s == 0
        assert segs[1].start_elapsed_s == 300

    def test_end_elapsed_seconds_is_start_plus_duration(self):
        segs = build_lap_segments(TYPICAL_SPLITS, [])
        assert segs[0].end_elapsed_s == pytest.approx(300.0)
        assert segs[1].end_elapsed_s == pytest.approx(300 + 1800.0)


# ─── Label edge cases ─────────────────────────────────────────────────────────

class TestLapSegmentLabeling:
    def test_no_warmup_no_cooldown_all_runs(self):
        """Without warmup/cooldown heuristic, first and last run are labeled Run N."""
        splits = [
            make_split(0, "run_segment",  0,    600,  1600.0),
            make_split(1, "walk_segment", 600,  120,  100.0),
            make_split(2, "run_segment",  720,  600,  1600.0),
        ]
        segs = build_lap_segments(splits, [])
        labels = [s.label for s in segs]
        assert labels == ["Run 1", "Walk 1", "Run 2"]

    def test_first_run_segment_called_warmup_when_short(self):
        """First run segment < 1km should be labeled Warmup."""
        splits = [
            make_split(0, "run_segment",  0,    300,  800.0),   # <1km → Warmup
            make_split(1, "run_segment",  300,  3600, 9000.0),  # main run → Run 1
            make_split(2, "run_segment",  3900, 300,  600.0),   # <1km → Cooldown
        ]
        segs = build_lap_segments(splits, [])
        assert segs[0].label == "Warmup"
        assert segs[-1].label == "Cooldown"
        assert segs[1].label == "Run 1"

    def test_last_walk_segment_called_cooldown_when_short(self):
        """Last segment as walk_segment → labeled Cooldown."""
        splits = [
            make_split(0, "run_segment",  0,    3600, 9000.0),
            make_split(1, "walk_segment", 3600, 300,  400.0),   # final walk → Cooldown
        ]
        segs = build_lap_segments(splits, [])
        assert segs[-1].label == "Cooldown"


class TestLapSegmentWktStepType:
    """Tests for wkt_step_type field: recovery labeling and is_transitional()."""

    def test_run_segment_with_recovery_step_type_labeled_recovery(self):
        """run_segment with wkt_step_type='recovery' should be labeled 'Recovery N'.
        Uses distance > WARMUP_COOLDOWN_DISTANCE_M to avoid warmup heuristic."""
        # Place the recovery between two normal-sized run segments so heuristics
        # don't override: first/last splits are large enough to avoid warmup/cooldown.
        splits = [
            ActivitySplit(
                id=0, activity_id=1, user_id=1, split_index=0,
                split_type="run_segment", start_elapsed_seconds=0,
                duration_seconds=300.0, distance_meters=1200.0,
                avg_hr=165.0, avg_pace_seconds_per_km=250.0,
            ),
            ActivitySplit(
                id=1, activity_id=1, user_id=1, split_index=1,
                split_type="run_segment", start_elapsed_seconds=300,
                duration_seconds=180.0, distance_meters=1200.0,
                avg_hr=120.0, avg_pace_seconds_per_km=450.0,
                wkt_step_type="recovery",
            ),
        ]
        segs = build_lap_segments(splits, [])
        recovery_seg = segs[1]
        assert recovery_seg.label == "Recovery 1"

    def test_multiple_recovery_segments_labeled_sequentially(self):
        """Multiple recovery splits should be labeled Recovery 1, Recovery 2, ..."""
        # Use distances >= WARMUP_COOLDOWN_DISTANCE_M (1000m) to avoid heuristic
        # warmup/cooldown labeling on any segment.
        splits = [
            ActivitySplit(
                id=0, activity_id=1, user_id=1, split_index=0,
                split_type="run_segment", start_elapsed_seconds=0,
                duration_seconds=300.0, distance_meters=1200.0,
                avg_hr=165.0, avg_pace_seconds_per_km=250.0,
            ),
            ActivitySplit(
                id=1, activity_id=1, user_id=1, split_index=1,
                split_type="run_segment", start_elapsed_seconds=300,
                duration_seconds=180.0, distance_meters=1200.0,
                avg_hr=120.0, avg_pace_seconds_per_km=450.0,
                wkt_step_type="recovery",
            ),
            ActivitySplit(
                id=2, activity_id=1, user_id=1, split_index=2,
                split_type="run_segment", start_elapsed_seconds=480,
                duration_seconds=300.0, distance_meters=1200.0,
                avg_hr=168.0, avg_pace_seconds_per_km=250.0,
            ),
            ActivitySplit(
                id=3, activity_id=1, user_id=1, split_index=3,
                split_type="run_segment", start_elapsed_seconds=780,
                duration_seconds=180.0, distance_meters=1200.0,
                avg_hr=118.0, avg_pace_seconds_per_km=450.0,
                wkt_step_type="recovery",
            ),
        ]
        segs = build_lap_segments(splits, [])
        labels = [s.label for s in segs]
        assert labels == ["Run 1", "Recovery 1", "Run 2", "Recovery 2"]

    def test_run_segment_without_recovery_type_still_labeled_run(self):
        """run_segment with no wkt_step_type should still be labeled 'Run N'."""
        sp = ActivitySplit(
            id=0, activity_id=1, user_id=1,
            split_index=0, split_type="run_segment",
            start_elapsed_seconds=0, duration_seconds=600.0, distance_meters=1600.0,
            avg_hr=155.0, avg_pace_seconds_per_km=375.0,
        )
        segs = build_lap_segments([sp], [])
        assert segs[0].label == "Run 1"

    def test_is_transitional_true_for_other_step_type(self):
        """LapSegment.is_transitional() returns True when wkt_step_type='other'."""
        sp = ActivitySplit(
            id=0, activity_id=1, user_id=1,
            split_index=0, split_type="run_segment",
            start_elapsed_seconds=0, duration_seconds=30.0, distance_meters=50.0,
            avg_hr=130.0, avg_pace_seconds_per_km=600.0,
            wkt_step_type="other",
        )
        segs = build_lap_segments([sp], [])
        assert segs[0].is_transitional() is True

    def test_is_transitional_false_for_normal_run(self):
        """LapSegment.is_transitional() returns False for a regular run_segment."""
        sp = ActivitySplit(
            id=0, activity_id=1, user_id=1,
            split_index=0, split_type="run_segment",
            start_elapsed_seconds=0, duration_seconds=300.0, distance_meters=800.0,
            avg_hr=165.0, avg_pace_seconds_per_km=283.0,
            wkt_step_type="interval",
        )
        segs = build_lap_segments([sp], [])
        assert segs[0].is_transitional() is False

    def test_is_transitional_false_when_wkt_step_type_none(self):
        """LapSegment.is_transitional() returns False when wkt_step_type is None."""
        sp = ActivitySplit(
            id=0, activity_id=1, user_id=1,
            split_index=0, split_type="run_segment",
            start_elapsed_seconds=0, duration_seconds=300.0, distance_meters=800.0,
            avg_hr=165.0, avg_pace_seconds_per_km=283.0,
        )
        segs = build_lap_segments([sp], [])
        assert segs[0].is_transitional() is False

    def test_wkt_step_type_passed_through_to_segment(self):
        """wkt_step_type is propagated from ActivitySplit to LapSegment."""
        sp = ActivitySplit(
            id=0, activity_id=1, user_id=1,
            split_index=0, split_type="run_segment",
            start_elapsed_seconds=0, duration_seconds=300.0, distance_meters=800.0,
            avg_hr=165.0, avg_pace_seconds_per_km=283.0,
            wkt_step_type="interval",
        )
        segs = build_lap_segments([sp], [])
        assert segs[0].wkt_step_type == "interval"


class TestLapSegmentTargetPace:
    """LapSegment passes target pace fields through from ActivitySplit."""

    def test_target_pace_defaults_to_none(self):
        """LapSegment.target_pace_slow/fast are None when split has no target."""
        sp = make_split(0, "run_segment", 0, 227, 800.0)
        segs = build_lap_segments([sp], [])
        assert segs[0].target_pace_slow_s_per_km is None
        assert segs[0].target_pace_fast_s_per_km is None

    def test_target_pace_passed_through_from_split(self):
        """LapSegment carries target_pace_slow/fast from ActivitySplit."""
        sp = ActivitySplit(
            id=0,
            activity_id=1,
            user_id=1,
            split_index=0,
            split_type="run_segment",
            start_elapsed_seconds=0,
            duration_seconds=227.0,
            distance_meters=800.0,
            avg_hr=165.0,
            avg_pace_seconds_per_km=283.0,
            target_pace_slow_s_per_km=295.1,
            target_pace_fast_s_per_km=282.6,
        )
        segs = build_lap_segments([sp], [])
        assert segs[0].target_pace_slow_s_per_km == pytest.approx(295.1)
        assert segs[0].target_pace_fast_s_per_km == pytest.approx(282.6)

    def test_mixed_splits_only_interval_has_target(self):
        """Only splits with workout targets carry them through; others get None."""
        interval = ActivitySplit(
            id=0, activity_id=1, user_id=1, split_index=0,
            split_type="run_segment", start_elapsed_seconds=0,
            duration_seconds=227.0, distance_meters=800.0,
            avg_hr=165.0, avg_pace_seconds_per_km=283.0,
            target_pace_slow_s_per_km=295.1,
            target_pace_fast_s_per_km=282.6,
        )
        recovery = ActivitySplit(
            id=1, activity_id=1, user_id=1, split_index=1,
            split_type="walk_segment", start_elapsed_seconds=227,
            duration_seconds=180.0, distance_meters=300.0,
            avg_hr=120.0, avg_pace_seconds_per_km=600.0,
            target_pace_slow_s_per_km=None,
            target_pace_fast_s_per_km=None,
        )
        segs = build_lap_segments([interval, recovery], [])
        assert segs[0].target_pace_slow_s_per_km == pytest.approx(295.1)
        assert segs[1].target_pace_slow_s_per_km is None
