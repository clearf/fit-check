"""Tests for heart rate analysis: zone classification and cardiac drift detection."""
from typing import List

import pytest

from fitness.analysis.heart_rate import (
    CardiacDriftEvent,
    classify_hr_zone,
    detect_cardiac_drift,
)
from fitness.analysis.timeseries import TimeseriesPoint


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_steady_run_with_drift(
    duration_minutes: int = 45,
    pace_s_per_km: float = 450.0,
    hr_start: int = 135,
    hr_end: int = 155,
    pace_variation_pct: float = 0.05,
) -> List[TimeseriesPoint]:
    """
    Synthetic run where pace is nearly constant but HR climbs linearly.
    Simulates classic cardiac drift from dehydration or heat.
    """
    import math
    points = []
    total_seconds = duration_minutes * 60
    hr_range = hr_end - hr_start

    for t in range(0, total_seconds, 5):  # 5-second intervals
        hr = int(hr_start + hr_range * (t / total_seconds))
        # Slight sinusoidal variation in pace to simulate natural running rhythm
        pace_variation = pace_s_per_km * pace_variation_pct * math.sin(t / 30)
        pace = pace_s_per_km + pace_variation
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=hr,
            pace_seconds_per_km=pace,
            speed_ms=1000.0 / pace if pace > 0 else None,
            elevation_meters=100.0,  # flat
            cadence_spm=162,
            distance_meters=float(t) * (1000.0 / pace_s_per_km) / 1000.0 * 1000.0 if t > 0 else 0.0,
            lat=None,
            lon=None,
            temperature_c=18.0,
        ))
    return points


def make_interval_run(duration_minutes: int = 30) -> List[TimeseriesPoint]:
    """
    Synthetic interval run: alternating fast/slow segments.
    HR fluctuates wildly — should NOT trigger cardiac drift detection.
    """
    points = []
    total_seconds = duration_minutes * 60
    for t in range(0, total_seconds, 5):
        # Alternate between fast (HR 170) and slow (HR 120) every 3 minutes
        cycle = (t // 180) % 2
        hr = 170 if cycle == 0 else 120
        pace = 280.0 if cycle == 0 else 450.0  # fast=4:40/km, slow=7:30/km
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=hr,
            pace_seconds_per_km=pace,
            speed_ms=1000.0 / pace,
            elevation_meters=100.0,
            cadence_spm=180 if cycle == 0 else 150,
            distance_meters=None,
            lat=None,
            lon=None,
            temperature_c=15.0,
        ))
    return points


def make_short_run(duration_minutes: int = 10) -> List[TimeseriesPoint]:
    """Too short to detect drift reliably."""
    return [
        TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=145,
            pace_seconds_per_km=450.0,
            speed_ms=2.222,
            elevation_meters=100.0,
            cadence_spm=162,
            distance_meters=None,
            lat=None,
            lon=None,
            temperature_c=15.0,
        )
        for t in range(0, duration_minutes * 60, 5)
    ]


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestClassifyHRZone:
    @pytest.mark.parametrize("hr,max_hr,expected_zone", [
        (100, 185, 1),   # 54% → zone 1 (<60%)
        (115, 185, 2),   # 62% → zone 2 (60-70%)
        (136, 185, 3),   # 74% → zone 3 (70-80%)
        (158, 185, 4),   # 85% → zone 4 (80-90%)
        (170, 185, 5),   # 92% → zone 5 (>90%)
    ])
    def test_classifies_correctly(self, hr, max_hr, expected_zone):
        assert classify_hr_zone(hr, max_hr) == expected_zone

    def test_boundary_60_pct_is_zone_2(self):
        # Exactly 60% should be zone 2 (boundary belongs to higher zone)
        assert classify_hr_zone(int(185 * 0.60), 185) == 2

    def test_boundary_90_pct_is_zone_5(self):
        # int(185 * 0.90) = 166; 166/185 = 0.897 which is < 0.90 → zone 4
        # Use ceiling to get an HR that is actually >= 90%
        import math
        hr_at_90pct = math.ceil(185 * 0.90)  # = 167, 167/185 = 0.903 → zone 5
        assert classify_hr_zone(hr_at_90pct, 185) == 5

    @pytest.mark.parametrize("hr", [40, 60, 80, 100, 130, 150, 170, 185])
    def test_zone_always_between_1_and_5(self, hr):
        zone = classify_hr_zone(hr, 185)
        assert 1 <= zone <= 5


class TestDetectCardiacDrift:
    def test_detects_drift_in_steady_run(self):
        points = make_steady_run_with_drift(
            duration_minutes=45,
            hr_start=135,
            hr_end=158,
            pace_variation_pct=0.05,
        )
        result = detect_cardiac_drift(points, max_hr=185)
        assert result is not None, "Expected cardiac drift to be detected"

    def test_drift_event_has_positive_hr_rise(self):
        points = make_steady_run_with_drift(hr_start=135, hr_end=158)
        result = detect_cardiac_drift(points, max_hr=185)
        assert result is not None
        assert result.total_hr_rise_bpm > 0

    def test_drift_onset_after_warmup(self):
        """Drift detection should ignore the first 15 minutes (warmup)."""
        points = make_steady_run_with_drift(duration_minutes=45)
        result = detect_cardiac_drift(points, max_hr=185)
        assert result is not None
        assert result.onset_elapsed_seconds >= 15 * 60

    def test_no_drift_in_interval_run(self):
        """Highly variable pace invalidates steady-state windows — no drift detected."""
        points = make_interval_run(duration_minutes=30)
        result = detect_cardiac_drift(points, max_hr=185)
        assert result is None

    def test_no_drift_in_short_run(self):
        """Too few steady windows in a 10-minute run."""
        points = make_short_run(duration_minutes=10)
        result = detect_cardiac_drift(points, max_hr=185)
        assert result is None

    def test_no_drift_when_hr_stable(self):
        """Perfectly flat HR should not trigger drift."""
        points = make_steady_run_with_drift(
            duration_minutes=45,
            hr_start=148,
            hr_end=150,  # only 2 bpm change — noise, not drift
        )
        result = detect_cardiac_drift(points, max_hr=185)
        assert result is None

    def test_drift_event_fields_populated(self):
        points = make_steady_run_with_drift(hr_start=132, hr_end=158)
        result = detect_cardiac_drift(points, max_hr=185)
        assert result is not None
        assert isinstance(result, CardiacDriftEvent)
        assert result.onset_elapsed_seconds >= 0
        assert result.total_hr_rise_bpm > 0
        assert result.pace_at_onset_s_per_km > 0
