"""Tests for bonk detection algorithm."""
from typing import List

import pytest

from fitness.analysis.bonk import BonkEvent, detect_bonk
from fitness.analysis.timeseries import TimeseriesPoint


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_normal_then_bonk(
    normal_duration_s: int = 1500,   # 25 min normal
    normal_pace: float = 450.0,      # 7:30/km
    normal_hr: int = 145,
    bonk_pace: float = 720.0,        # 12:00/km (very slow)
    bonk_hr: int = 168,
    bonk_duration_s: int = 600,      # stays bonked 10 min
    flat_elevation: float = 100.0,
) -> List[TimeseriesPoint]:
    """Normal run then sudden pace collapse + HR spike on flat terrain."""
    points = []
    # Normal phase
    for t in range(0, normal_duration_s, 5):
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=normal_hr + (t // 300),  # slight natural rise
            pace_seconds_per_km=normal_pace,
            speed_ms=1000.0 / normal_pace,
            elevation_meters=flat_elevation,
            cadence_spm=162,
            distance_meters=float(t) * 1000.0 / normal_pace,
            lat=None, lon=None, temperature_c=18.0,
        ))
    # Bonk phase — starts right after
    for t in range(normal_duration_s, normal_duration_s + bonk_duration_s, 5):
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=bonk_hr,
            pace_seconds_per_km=bonk_pace,
            speed_ms=1000.0 / bonk_pace,
            elevation_meters=flat_elevation,
            cadence_spm=145,
            distance_meters=float(normal_duration_s) * 1000.0 / normal_pace
                           + float(t - normal_duration_s) * 1000.0 / bonk_pace,
            lat=None, lon=None, temperature_c=18.0,
        ))
    return points


def make_normal_bonk_recovery(
    normal_pace: float = 450.0,
    bonk_pace: float = 660.0,       # 11:00/km
    recovery_pace: float = 470.0,   # nearly back to normal
) -> List[TimeseriesPoint]:
    """Run with a bonk that partially recovers."""
    points = []
    phases = [
        (1500, normal_pace, 145),   # 25 min normal
        (300, bonk_pace, 168),      # 5 min bonk
        (600, recovery_pace, 152),  # 10 min recovery
    ]
    t = 0
    for duration, pace, hr in phases:
        for _ in range(0, duration, 5):
            points.append(TimeseriesPoint(
                elapsed_seconds=t,
                heart_rate=hr,
                pace_seconds_per_km=pace,
                speed_ms=1000.0 / pace,
                elevation_meters=100.0,
                cadence_spm=162,
                distance_meters=float(t) * 1000.0 / pace,
                lat=None, lon=None, temperature_c=18.0,
            ))
            t += 5
    return points


def make_hill_run(
    flat_duration_s: int = 900,      # 15 min flat
    flat_pace: float = 450.0,
    flat_hr: int = 145,
    hill_grade: float = 0.12,        # 12% grade
    hill_duration_s: int = 300,      # 5 min hill
) -> List[TimeseriesPoint]:
    """A run where pace drops on a hill — should NOT trigger bonk detection."""
    # On a 12% hill, pace naturally drops by ~40% (Minetti effect)
    hill_pace = flat_pace * 1.6  # ~12:00/km on 12% grade
    hill_hr = flat_hr + 15       # HR rises on hill but that's expected

    points = []
    for t in range(0, flat_duration_s, 5):
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=flat_hr,
            pace_seconds_per_km=flat_pace,
            speed_ms=1000.0 / flat_pace,
            elevation_meters=100.0,  # flat
            cadence_spm=162,
            distance_meters=float(t) * 1000.0 / flat_pace,
            lat=None, lon=None, temperature_c=18.0,
        ))

    for t in range(flat_duration_s, flat_duration_s + hill_duration_s, 5):
        progress = t - flat_duration_s
        elev = 100.0 + progress * hill_grade  # climbing
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=hill_hr,
            pace_seconds_per_km=hill_pace,
            speed_ms=1000.0 / hill_pace,
            elevation_meters=elev,
            cadence_spm=155,
            distance_meters=float(flat_duration_s) * 1000.0 / flat_pace
                           + float(progress) * 1000.0 / hill_pace,
            lat=None, lon=None, temperature_c=18.0,
        ))
    return points


def make_early_slow_start(slow_duration_s: int = 300) -> List[TimeseriesPoint]:
    """Run that starts slow then settles — slow start should not be a bonk."""
    points = []
    for t in range(0, slow_duration_s, 5):
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=120,
            pace_seconds_per_km=600.0,  # slow start
            speed_ms=1000.0 / 600.0,
            elevation_meters=100.0,
            cadence_spm=145,
            distance_meters=None,
            lat=None, lon=None, temperature_c=18.0,
        ))
    for t in range(slow_duration_s, slow_duration_s + 1200, 5):
        points.append(TimeseriesPoint(
            elapsed_seconds=t,
            heart_rate=148,
            pace_seconds_per_km=450.0,  # settles into normal pace
            speed_ms=1000.0 / 450.0,
            elevation_meters=100.0,
            cadence_spm=162,
            distance_meters=None,
            lat=None, lon=None, temperature_c=18.0,
        ))
    return points


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestDetectBonk:
    def test_detects_clear_bonk(self):
        points = make_normal_then_bonk(
            normal_pace=450.0, bonk_pace=720.0, normal_hr=145, bonk_hr=168
        )
        bonks = detect_bonk(points)
        assert len(bonks) == 1

    def test_bonk_has_significant_pace_drop(self):
        points = make_normal_then_bonk(normal_pace=450.0, bonk_pace=720.0)
        bonks = detect_bonk(points)
        assert bonks[0].pace_drop_pct >= 0.20

    def test_bonk_not_recovered(self):
        """Run stays slow after bonk — should be marked not recovered."""
        points = make_normal_then_bonk(bonk_duration_s=900)  # stays bonked 15 min
        bonks = detect_bonk(points)
        assert len(bonks) >= 1
        assert not bonks[0].recovered

    def test_bonk_with_recovery(self):
        points = make_normal_bonk_recovery(
            normal_pace=450.0,
            bonk_pace=660.0,
            recovery_pace=470.0,
        )
        bonks = detect_bonk(points)
        assert len(bonks) >= 1
        assert bonks[0].recovered

    def test_no_bonk_on_hill(self):
        """Pace drop on a steep climb should not trigger bonk detection.
        The hill must be long enough (600s) that the grade window lands
        squarely on the climb, not on the flat-to-hill transition.
        """
        points = make_hill_run(
            flat_duration_s=900,   # 15 min flat
            hill_grade=0.12,
            hill_duration_s=600,   # 10 min hill — long enough to detect grade
        )
        bonks = detect_bonk(points)
        assert len(bonks) == 0, (
            f"Hill climb should not be a bonk, but detected: {bonks}"
        )

    def test_no_bonk_in_first_10_minutes(self):
        """Early slow start is not a bonk — ignore first 10 minutes."""
        points = make_early_slow_start(slow_duration_s=300)
        bonks = detect_bonk(points)
        assert len(bonks) == 0

    def test_bonk_event_fields_populated(self):
        points = make_normal_then_bonk()
        bonks = detect_bonk(points)
        assert len(bonks) >= 1
        b = bonks[0]
        assert isinstance(b, BonkEvent)
        assert b.elapsed_seconds_onset > 0
        assert b.pre_bonk_pace_s_per_km > 0
        assert b.bonk_pace_s_per_km > b.pre_bonk_pace_s_per_km
        assert b.pre_bonk_hr > 0
        assert b.peak_hr > b.pre_bonk_hr

    def test_no_bonk_on_flat_stable_run(self):
        """A boring steady run should produce zero bonk events."""
        points = [
            TimeseriesPoint(
                elapsed_seconds=t,
                heart_rate=148,
                pace_seconds_per_km=450.0,
                speed_ms=2.222,
                elevation_meters=100.0,
                cadence_spm=162,
                distance_meters=float(t) * 2.222,
                lat=None, lon=None, temperature_c=18.0,
            )
            for t in range(0, 3600, 5)
        ]
        bonks = detect_bonk(points)
        assert len(bonks) == 0

    def test_only_one_bonk_event_for_sustained_slowdown(self):
        """A single sustained bonk should be reported as one event, not many."""
        points = make_normal_then_bonk(
            normal_duration_s=1200, bonk_duration_s=1200
        )
        bonks = detect_bonk(points)
        assert len(bonks) == 1
