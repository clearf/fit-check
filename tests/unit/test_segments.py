"""Tests for per-mile segment builder."""
from typing import List

import pytest

from fitness.analysis.segments import RunSegment, build_mile_segments
from fitness.analysis.timeseries import TimeseriesPoint


def make_flat_run(
    distance_m: float = 8046.72,  # 5 miles
    pace_s_per_km: float = 450.0,  # 7:30/km
    hr: int = 148,
    elevation: float = 100.0,
    interval_s: int = 5,
) -> List[TimeseriesPoint]:
    """Flat steady-state run at constant pace and HR."""
    speed_ms = 1000.0 / pace_s_per_km
    total_s = int(distance_m / speed_ms)
    points = []
    for t in range(0, total_s, interval_s):
        dist = speed_ms * t
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=hr,
            pace_seconds_per_km=pace_s_per_km,
            speed_ms=speed_ms,
            elevation_meters=elevation,
            cadence_spm=162,
            distance_meters=dist,
            lat=None,
            lon=None,
            temperature_c=15.0,
        ))
    return points


def make_hilly_run(
    flat_distance_m: float = 4000.0,
    hill_distance_m: float = 1000.0,
    grade: float = 0.08,
    base_elevation: float = 100.0,
    flat_pace: float = 450.0,
    hill_pace: float = 540.0,  # slower on hill
) -> List[TimeseriesPoint]:
    """Run with a distinct hilly section."""
    points = []
    speed_flat = 1000.0 / flat_pace
    speed_hill = 1000.0 / hill_pace
    t = 0

    # Flat section
    for _ in range(int(flat_distance_m / speed_flat / 5)):
        dist = speed_flat * t
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=148,
            pace_seconds_per_km=flat_pace,
            speed_ms=speed_flat,
            elevation_meters=base_elevation,
            cadence_spm=162,
            distance_meters=dist,
            lat=None, lon=None, temperature_c=15.0,
        ))
        t += 5

    # Hill section
    flat_dist_so_far = speed_flat * t
    for i in range(int(hill_distance_m / speed_hill / 5)):
        hill_progress = speed_hill * (i * 5)
        dist = flat_dist_so_far + hill_progress
        elev = base_elevation + hill_progress * grade
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=162,
            pace_seconds_per_km=hill_pace,
            speed_ms=speed_hill,
            elevation_meters=elev,
            cadence_spm=158,
            distance_meters=dist,
            lat=None, lon=None, temperature_c=15.0,
        ))
        t += 5

    return points


class TestBuildMileSegments:
    def test_five_mile_run_has_five_segments(self):
        points = make_flat_run(distance_m=8046.72)  # 5 miles
        segments = build_mile_segments(points)
        assert len(segments) == 5

    def test_segment_labels_are_sequential(self):
        points = make_flat_run(distance_m=4828.0)  # 3 miles
        segments = build_mile_segments(points)
        labels = [s.label for s in segments]
        assert labels == ["Mile 1", "Mile 2", "Mile 3"]

    def test_segment_avg_pace_close_to_actual(self):
        points = make_flat_run(pace_s_per_km=450.0)
        segments = build_mile_segments(points)
        for seg in segments:
            # Pace in s/km: 450.0 * 1.60934 ≈ 724.2 s/mi
            assert seg.avg_pace_s_per_km == pytest.approx(450.0, rel=0.05)

    def test_segment_avg_hr_close_to_actual(self):
        points = make_flat_run(hr=148)
        segments = build_mile_segments(points)
        for seg in segments:
            assert seg.avg_hr == pytest.approx(148.0, abs=2.0)

    def test_hr_zone_distribution_sums_to_one(self):
        points = make_flat_run(hr=148)
        segments = build_mile_segments(points)
        for seg in segments:
            total = sum(seg.hr_zone_distribution.values())
            assert total == pytest.approx(1.0, abs=0.01)

    def test_hr_zone_distribution_has_zones_1_to_5(self):
        points = make_flat_run()
        segments = build_mile_segments(points)
        for seg in segments:
            assert all(k in range(1, 6) for k in seg.hr_zone_distribution.keys())

    def test_hilly_segment_has_nonzero_grade(self):
        points = make_hilly_run(flat_distance_m=1609.0, hill_distance_m=1609.0, grade=0.08)
        segments = build_mile_segments(points)
        # Second segment should be the hilly one
        assert len(segments) >= 2
        hilly_segs = [s for s in segments if s.grade_pct > 2.0]
        assert len(hilly_segs) >= 1

    def test_flat_segment_near_zero_grade(self):
        points = make_flat_run(distance_m=4828.0)
        segments = build_mile_segments(points)
        for seg in segments:
            assert abs(seg.grade_pct) < 1.0

    def test_gap_equals_pace_on_flat(self):
        """On flat terrain, grade-adjusted pace ≈ actual pace."""
        points = make_flat_run(distance_m=4828.0, pace_s_per_km=450.0)
        segments = build_mile_segments(points)
        for seg in segments:
            assert seg.gap_s_per_km == pytest.approx(seg.avg_pace_s_per_km, rel=0.02)

    def test_empty_points_returns_empty(self):
        segments = build_mile_segments([])
        assert segments == []

    def test_too_short_run_returns_empty(self):
        # Less than 1 mile — no complete segments
        points = make_flat_run(distance_m=500.0)
        segments = build_mile_segments(points)
        assert segments == []

    def test_segment_start_and_end_elapsed_seconds(self):
        points = make_flat_run(distance_m=4828.0)
        segments = build_mile_segments(points)
        # Segments should be contiguous
        for i in range(1, len(segments)):
            assert segments[i].start_elapsed_s >= segments[i - 1].end_elapsed_s

    def test_each_segment_is_run_segment_type(self):
        points = make_flat_run(distance_m=4828.0)
        segments = build_mile_segments(points)
        for seg in segments:
            assert isinstance(seg, RunSegment)
