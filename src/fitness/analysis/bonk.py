"""
Bonk detection: identifies sudden pace collapse + HR spike on flat terrain.

A "bonk" (also called "hitting the wall") is a metabolic event where glycogen
stores are depleted and performance collapses. Signature:
  - Pace drops > 20% suddenly (not gradually like cardiac drift)
  - HR spikes or remains elevated despite slower pace
  - Not explained by terrain (flat ground)
  - Runner may or may not recover

We distinguish bonks from hills using elevation gradient data.
A pace drop on a 5%+ grade is a hill, not a bonk.
"""
from dataclasses import dataclass
from statistics import median
from typing import List, Optional

from fitness.analysis.timeseries import TimeseriesPoint


@dataclass
class BonkEvent:
    """A detected performance collapse event."""
    elapsed_seconds_onset: int        # when the bonk starts
    pre_bonk_pace_s_per_km: float     # avg pace in 3 min before onset
    bonk_pace_s_per_km: float         # avg pace in 3 min after onset
    pace_drop_pct: float              # (bonk_pace - pre_pace) / pre_pace
    pre_bonk_hr: float                # avg HR before
    peak_hr: float                    # peak HR during bonk
    recovered: bool                   # True if pace returned to within 15% of pre-bonk
    elapsed_seconds_end: Optional[int] = None  # None if never recovered


def _rolling_median_pace(
    points: List[TimeseriesPoint],
    elapsed: int,
    window_seconds: int,
    direction: str = "before",
) -> Optional[float]:
    """
    Compute median pace in a window before or after a given elapsed time.
    Excludes None paces and zero speeds.
    """
    if direction == "before":
        window_pts = [
            p for p in points
            if elapsed - window_seconds <= p.elapsed_seconds < elapsed
            and p.pace_seconds_per_km is not None
            and p.pace_seconds_per_km > 0
        ]
    else:
        window_pts = [
            p for p in points
            if elapsed <= p.elapsed_seconds < elapsed + window_seconds
            and p.pace_seconds_per_km is not None
            and p.pace_seconds_per_km > 0
        ]

    if len(window_pts) < 3:
        return None
    return median(p.pace_seconds_per_km for p in window_pts)


def _mean_hr_window(
    points: List[TimeseriesPoint],
    elapsed: int,
    window_seconds: int,
    direction: str = "before",
) -> Optional[float]:
    """Compute mean HR in a window before or after elapsed time."""
    if direction == "before":
        window_pts = [
            p for p in points
            if elapsed - window_seconds <= p.elapsed_seconds < elapsed
            and p.heart_rate is not None
        ]
    else:
        window_pts = [
            p for p in points
            if elapsed <= p.elapsed_seconds < elapsed + window_seconds
            and p.heart_rate is not None
        ]

    if not window_pts:
        return None
    return sum(p.heart_rate for p in window_pts) / len(window_pts)


def _elevation_grade_around(
    points: List[TimeseriesPoint],
    elapsed: int,
    window_seconds: int = 60,
) -> float:
    """
    Estimate the terrain grade AFTER a given elapsed time.
    We look forward (from elapsed to elapsed + 2*window_seconds) because
    we're assessing whether the pace drop is caused by upcoming terrain.

    Returns grade as a decimal (0.10 = 10% uphill).
    Returns 0.0 if elevation data is insufficient.
    """
    # Look primarily forward (post-onset) since pace has already dropped
    window_pts = [
        p for p in points
        if elapsed <= p.elapsed_seconds <= elapsed + 2 * window_seconds
        and p.elevation_meters is not None
        and p.distance_meters is not None
    ]

    if len(window_pts) < 2:
        return 0.0

    # Sort by elapsed time to get start/end
    window_pts = sorted(window_pts, key=lambda p: p.elapsed_seconds)
    elev_change = window_pts[-1].elevation_meters - window_pts[0].elevation_meters
    dist_change = window_pts[-1].distance_meters - window_pts[0].distance_meters

    if dist_change <= 0:
        return 0.0

    return elev_change / dist_change


def detect_bonk(
    points: List[TimeseriesPoint],
    pace_drop_threshold: float = 0.20,   # 20% pace drop = significant
    hr_spike_threshold: float = 8.0,     # 8 bpm HR spike accompanying drop
    pre_window_seconds: int = 180,       # 3 min window for pre-bonk baseline
    post_window_seconds: int = 180,      # 3 min window for post-bonk assessment
    recovery_window_seconds: int = 480,  # 8 min to assess recovery
    recovery_threshold: float = 0.15,   # pace must return within 15% of pre-bonk
    hill_grade_threshold: float = 0.05,  # ignore pace drops on >5% grade
    min_elapsed_seconds: int = 600,      # ignore first 10 minutes (warmup)
    merge_window_seconds: int = 120,     # merge candidates within 2 minutes
) -> List[BonkEvent]:
    """
    Detect bonk events in a run.

    A bonk candidate is confirmed when:
    - Pace drops > pace_drop_threshold relative to recent baseline
    - HR spikes > hr_spike_threshold bpm
    - The terrain grade is < hill_grade_threshold (not a hill)

    Multiple candidates within merge_window_seconds are merged into one event.

    Args:
        points: List of TimeseriesPoint from the activity

    Returns:
        List of BonkEvent (empty list if none detected)
    """
    if not points:
        return []

    # Only check points after warmup, at reasonable intervals (every 15s)
    candidate_times = [
        p.elapsed_seconds for p in points
        if p.elapsed_seconds >= min_elapsed_seconds
    ]
    # Sample every 15 seconds to avoid redundant checks
    candidate_times = [t for t in candidate_times if t % 15 == 0]

    raw_candidates = []

    for t in candidate_times:
        pre_pace = _rolling_median_pace(points, t, pre_window_seconds, "before")
        post_pace = _rolling_median_pace(points, t, post_window_seconds, "after")

        if pre_pace is None or post_pace is None:
            continue

        # Check for significant pace drop
        pace_drop = (post_pace - pre_pace) / pre_pace
        if pace_drop < pace_drop_threshold:
            continue

        # Check for HR spike
        pre_hr = _mean_hr_window(points, t, 60, "before")
        post_hr = _mean_hr_window(points, t, 60, "after")

        if pre_hr is None or post_hr is None:
            continue

        hr_spike = post_hr - pre_hr
        if hr_spike < hr_spike_threshold:
            continue

        # Reject if on a significant hill
        grade = _elevation_grade_around(points, t)
        if abs(grade) >= hill_grade_threshold:
            continue

        # We have a candidate bonk
        raw_candidates.append({
            "t": t,
            "pre_pace": pre_pace,
            "post_pace": post_pace,
            "pace_drop_pct": pace_drop,
            "pre_hr": pre_hr,
            "peak_hr": post_hr,
        })

    if not raw_candidates:
        return []

    # Merge candidates within merge_window_seconds into single events
    merged = []
    current = raw_candidates[0]
    for candidate in raw_candidates[1:]:
        if candidate["t"] - current["t"] <= merge_window_seconds:
            # Keep the candidate with the larger pace drop
            if candidate["pace_drop_pct"] > current["pace_drop_pct"]:
                current = candidate
        else:
            merged.append(current)
            current = candidate
    merged.append(current)

    # Build BonkEvent objects with recovery assessment
    events = []
    for c in merged:
        onset = c["t"]
        recovery_start = onset + post_window_seconds + recovery_window_seconds
        recovery_pace = _rolling_median_pace(
            points, recovery_start, pre_window_seconds, "after"
        )

        recovered = False
        end_t: Optional[int] = None
        if recovery_pace is not None:
            recovered = recovery_pace <= c["pre_pace"] * (1 + recovery_threshold)
            if recovered:
                end_t = recovery_start

        events.append(BonkEvent(
            elapsed_seconds_onset=onset,
            pre_bonk_pace_s_per_km=c["pre_pace"],
            bonk_pace_s_per_km=c["post_pace"],
            pace_drop_pct=round(c["pace_drop_pct"], 3),
            pre_bonk_hr=round(c["pre_hr"], 1),
            peak_hr=round(c["peak_hr"], 1),
            recovered=recovered,
            elapsed_seconds_end=end_t,
        ))

    return events
