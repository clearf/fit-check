"""Tests for Galloway run/walk segment detection."""
from typing import List

import pytest

from fitness.analysis.galloway import GallowaySegments, detect_galloway_segments


def make_typed_splits(
    run_s: float = 180.0,
    walk_s: float = 60.0,
    cycles: int = 8,
    run_pace: float = 420.0,   # 7:00/km
    walk_pace: float = 800.0,  # 13:20/km
    run_hr: float = 155.0,
    walk_hr: float = 128.0,
) -> List[dict]:
    """
    Simulate typed splits from garminconnect get_activity_typed_splits().
    Produces alternating run/walk segments.
    """
    splits = []
    elapsed = 0.0
    flat_dist_per_run_s = 1000.0 / run_pace  # m/s
    flat_dist_per_walk_s = 1000.0 / walk_pace

    for i in range(cycles):
        # Run segment
        splits.append({
            "messageIndex": len(splits),
            "splitType": "RUN",
            "startTimeGMT": f"2025-01-15T07:{int(elapsed/60):02d}:00",
            "totalElapsedTime": run_s,
            "totalDistance": flat_dist_per_run_s * run_s,
            "averageHR": run_hr,
            "averageSpeed": 1000.0 / run_pace,
            "startTime": elapsed,
        })
        elapsed += run_s

        # Walk segment
        splits.append({
            "messageIndex": len(splits),
            "splitType": "WALK",
            "startTimeGMT": f"2025-01-15T07:{int(elapsed/60):02d}:00",
            "totalElapsedTime": walk_s,
            "totalDistance": flat_dist_per_walk_s * walk_s,
            "averageHR": walk_hr,
            "averageSpeed": 1000.0 / walk_pace,
            "startTime": elapsed,
        })
        elapsed += walk_s

    return splits


def make_continuous_run_splits(duration_s: float = 3600.0) -> List[dict]:
    """Single continuous run — no walk segments."""
    return [{
        "messageIndex": 0,
        "splitType": "RUN",
        "totalElapsedTime": duration_s,
        "totalDistance": duration_s * 2.222,
        "averageHR": 148.0,
        "averageSpeed": 2.222,
        "startTime": 0,
    }]


class TestDetectGallowaySegments:
    def test_detects_run_walk_pattern(self):
        splits = make_typed_splits(run_s=180.0, walk_s=60.0, cycles=8)
        result = detect_galloway_segments(splits)
        assert result.is_galloway is True

    def test_counts_run_and_walk_segments(self):
        splits = make_typed_splits(run_s=180.0, walk_s=60.0, cycles=8)
        result = detect_galloway_segments(splits)
        assert result.run_segment_count == 8
        assert result.walk_segment_count == 8

    def test_average_run_pace_correct(self):
        splits = make_typed_splits(run_s=180.0, walk_s=60.0, run_pace=420.0, cycles=5)
        result = detect_galloway_segments(splits)
        assert result.avg_run_pace_s_per_km == pytest.approx(420.0, abs=5.0)

    def test_average_walk_hr_correct(self):
        splits = make_typed_splits(walk_hr=128.0, cycles=5)
        result = detect_galloway_segments(splits)
        assert result.avg_walk_hr == pytest.approx(128.0, abs=1.0)

    def test_average_run_hr_correct(self):
        splits = make_typed_splits(run_hr=155.0, cycles=5)
        result = detect_galloway_segments(splits)
        assert result.avg_run_hr == pytest.approx(155.0, abs=1.0)

    def test_not_galloway_when_no_walk_segments(self):
        splits = make_continuous_run_splits()
        result = detect_galloway_segments(splits)
        assert result.is_galloway is False

    def test_not_galloway_when_fewer_than_3_walk_segments(self):
        splits = make_typed_splits(cycles=2)  # only 2 walk segments
        result = detect_galloway_segments(splits)
        assert result.is_galloway is False

    def test_empty_splits_not_galloway(self):
        result = detect_galloway_segments([])
        assert result.is_galloway is False

    def test_result_has_correct_type(self):
        splits = make_typed_splits()
        result = detect_galloway_segments(splits)
        assert isinstance(result, GallowaySegments)

    def test_walk_pace_slower_than_run_pace(self):
        splits = make_typed_splits(run_pace=420.0, walk_pace=800.0, cycles=5)
        result = detect_galloway_segments(splits)
        assert result.is_galloway is True
        # Walk pace (s/km) should be higher number (slower)
        assert result.avg_walk_pace_s_per_km > result.avg_run_pace_s_per_km
