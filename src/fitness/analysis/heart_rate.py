"""
Heart rate zone classification and cardiac drift detection.

Cardiac drift: HR rises progressively during a steady-state run while pace
stays constant. It's a sign of cardiovascular fatigue, dehydration, or heat
accumulation. We detect it by:
  1. Dividing the run into 5-minute windows (after a 15-min warmup)
  2. Keeping only "steady" windows where pace doesn't vary much
  3. Fitting a linear trend to mean HR across those windows
  4. If the upward trend is large enough → drift detected
"""
from dataclasses import dataclass
from statistics import mean, stdev
from typing import List, Optional

from fitness.analysis.timeseries import TimeseriesPoint


# ─── HR Zone Classification ────────────────────────────────────────────────────

# 5-zone model based on % of max HR
_ZONE_BOUNDARIES = [0.60, 0.70, 0.80, 0.90]  # lower bounds for zones 2-5


def classify_hr_zone(heart_rate: int, max_hr: int) -> int:
    """
    Classify a heart rate reading into zones 1-5 using % of max HR.

    Zone 1: < 60%  — very easy, recovery
    Zone 2: 60-70% — aerobic base, "fat burning"
    Zone 3: 70-80% — moderate aerobic (tempo)
    Zone 4: 80-90% — threshold
    Zone 5: > 90%  — max effort / VO2max

    Args:
        heart_rate: current HR in bpm
        max_hr: user's maximum heart rate in bpm

    Returns:
        Zone number 1-5
    """
    pct = heart_rate / max_hr
    for zone, boundary in enumerate(_ZONE_BOUNDARIES, start=2):
        if pct < boundary:
            return zone - 1
    return 5


# ─── Cardiac Drift Detection ───────────────────────────────────────────────────

@dataclass
class CardiacDriftEvent:
    """Result of cardiac drift detection."""
    onset_elapsed_seconds: int    # when drift becomes apparent
    total_hr_rise_bpm: float      # total HR rise across steady windows
    pace_at_onset_s_per_km: float # avg pace at onset (for context)


def detect_cardiac_drift(
    points: List[TimeseriesPoint],
    max_hr: int = 185,
    warmup_minutes: int = 15,
    window_minutes: int = 5,
    pace_stability_threshold: float = 0.10,  # 10% pace CV = steady window
    drift_threshold_bpm: float = 8.0,        # min HR rise to call it drift
    min_steady_windows: int = 4,             # need at least 4 steady windows
) -> Optional[CardiacDriftEvent]:
    """
    Detect cardiac drift: progressive HR rise during steady-state running.

    Algorithm:
    1. Skip the first warmup_minutes.
    2. Divide remaining points into non-overlapping windows of window_minutes.
    3. For each window, compute mean_hr, mean_pace, and pace CV (stddev/mean).
    4. Keep only "steady" windows: pace_cv < pace_stability_threshold.
    5. If fewer than min_steady_windows steady windows → no detection possible.
    6. Fit linear regression of window_index → mean_hr.
    7. If regression predicts total rise >= drift_threshold_bpm → drift detected.

    Returns:
        CardiacDriftEvent if drift detected, else None.
    """
    warmup_seconds = warmup_minutes * 60
    window_seconds = window_minutes * 60

    # Filter to points after warmup that have both HR and pace
    post_warmup = [
        p for p in points
        if p.elapsed_seconds >= warmup_seconds
        and p.heart_rate is not None
        and p.pace_seconds_per_km is not None
        and p.pace_seconds_per_km > 0
    ]

    if not post_warmup:
        return None

    # Build windows
    start_time = post_warmup[0].elapsed_seconds
    end_time = post_warmup[-1].elapsed_seconds
    windows = []

    t = start_time
    while t + window_seconds <= end_time:
        window_points = [
            p for p in post_warmup
            if t <= p.elapsed_seconds < t + window_seconds
        ]
        if len(window_points) >= 3:
            hrs = [p.heart_rate for p in window_points]
            paces = [p.pace_seconds_per_km for p in window_points]
            mean_hr = mean(hrs)
            mean_pace = mean(paces)
            pace_cv = (stdev(paces) / mean_pace) if len(paces) > 1 else 0.0

            windows.append({
                "start_t": t,
                "mean_hr": mean_hr,
                "mean_pace": mean_pace,
                "pace_cv": pace_cv,
            })
        t += window_seconds

    # Keep only steady windows
    steady = [w for w in windows if w["pace_cv"] < pace_stability_threshold]

    if len(steady) < min_steady_windows:
        return None

    # Linear regression: window_index → mean_hr
    # y = mean_hr, x = window_index (0, 1, 2, ...)
    n = len(steady)
    xs = list(range(n))
    ys = [w["mean_hr"] for w in steady]

    x_mean = mean(xs)
    y_mean = mean(ys)

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)

    if denominator == 0:
        return None

    slope = numerator / denominator  # bpm per window
    predicted_rise = slope * (n - 1)  # total rise across all windows

    if predicted_rise < drift_threshold_bpm:
        return None

    # Drift detected — onset is the first steady window
    first_steady = steady[0]
    return CardiacDriftEvent(
        onset_elapsed_seconds=first_steady["start_t"],
        total_hr_rise_bpm=round(predicted_rise, 1),
        pace_at_onset_s_per_km=first_steady["mean_pace"],
    )
