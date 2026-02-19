"""
Per-mile segment builder.

Slices a run's timeseries into one-mile segments and computes per-segment
statistics: average pace, average HR, elevation grade, grade-adjusted pace
(GAP), and HR zone distribution.

One mile = 1609.344 metres (standard).
"""
from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, List, Optional

from fitness.analysis.heart_rate import classify_hr_zone
from fitness.analysis.pace import grade_adjusted_pace, minetti_grade_multiplier
from fitness.analysis.timeseries import TimeseriesPoint

METERS_PER_MILE = 1609.344
MAX_HR_DEFAULT = 185


@dataclass
class RunSegment:
    """Statistics for a single mile-long segment of a run."""
    label: str                          # "Mile 1", "Mile 2", …
    start_elapsed_s: int
    end_elapsed_s: int
    avg_pace_s_per_km: float
    avg_hr: float
    grade_pct: float                    # % grade (positive = uphill)
    gap_s_per_km: float                 # grade-adjusted pace in s/km
    hr_zone_distribution: Dict[int, float] = field(default_factory=dict)
    # zone keys 1-5, values are fractions summing to ~1.0


def _grade_pct_for_segment(pts: List[TimeseriesPoint]) -> float:
    """
    Estimate the average grade over a segment as a percentage.

    Uses the first and last points that have both elevation and distance data.
    Returns 0.0 if insufficient data.
    """
    valid = [
        p for p in pts
        if p.elevation_meters is not None and p.distance_meters is not None
    ]
    if len(valid) < 2:
        return 0.0

    valid = sorted(valid, key=lambda p: p.elapsed_seconds)
    elev_change = valid[-1].elevation_meters - valid[0].elevation_meters
    dist_change = valid[-1].distance_meters - valid[0].distance_meters

    if dist_change <= 0:
        return 0.0

    return (elev_change / dist_change) * 100.0  # convert to percent


def _hr_zone_distribution(
    pts: List[TimeseriesPoint],
    max_hr: int = MAX_HR_DEFAULT,
) -> Dict[int, float]:
    """
    Compute the fraction of time spent in each HR zone (1-5).

    Each point represents one equal time slice (typically 5 seconds).
    Points without HR data are excluded.
    """
    zone_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    hr_pts = [p for p in pts if p.heart_rate is not None]

    if not hr_pts:
        return {z: 0.0 for z in range(1, 6)}

    for p in hr_pts:
        z = classify_hr_zone(p.heart_rate, max_hr)
        zone_counts[z] += 1

    total = sum(zone_counts.values())
    return {z: zone_counts[z] / total for z in range(1, 6)}


def build_mile_segments(
    points: List[TimeseriesPoint],
    max_hr: int = MAX_HR_DEFAULT,
) -> List[RunSegment]:
    """
    Slice a run into complete one-mile segments and compute per-segment stats.

    Incomplete final miles (< 1 mile remaining) are dropped.

    Args:
        points: Chronologically ordered list of TimeseriesPoint.
        max_hr: Athlete's maximum heart rate (used for HR zone classification).

    Returns:
        List of RunSegment, one per complete mile, in order.
    """
    if not points:
        return []

    # Sort by elapsed time (defensive — callers should pass sorted data)
    pts = sorted(points, key=lambda p: p.elapsed_seconds)

    # Determine total distance covered
    dist_pts = [p for p in pts if p.distance_meters is not None]
    if not dist_pts:
        return []

    total_distance = max(p.distance_meters for p in dist_pts)
    if total_distance < METERS_PER_MILE:
        return []

    segments: List[RunSegment] = []
    mile_index = 0

    while True:
        mile_start_m = mile_index * METERS_PER_MILE
        mile_end_m = (mile_index + 1) * METERS_PER_MILE

        # A complete mile requires that the runner covered at least
        # mile_start_m. Allow a small tolerance (one GPS interval ≈ 5s * max_speed)
        # so that floating-point sampling gaps don't drop the last mile.
        TOLERANCE_M = 10.0
        if mile_start_m >= total_distance + TOLERANCE_M:
            break  # no data at all in this mile band

        # Collect points that started before mile_end_m
        mile_pts = [
            p for p in pts
            if p.distance_meters is not None
            and mile_start_m <= p.distance_meters < mile_end_m
        ]

        if not mile_pts:
            break

        # A "complete" mile requires at least 95% coverage of the mile band.
        # This tolerates the discrete 5-second sampling intervals that mean
        # the last recorded distance is typically a few metres short of the
        # exact mile boundary.
        coverage = max(p.distance_meters for p in mile_pts) - mile_start_m
        if coverage < METERS_PER_MILE * 0.95:
            break  # genuinely incomplete mile

        mile_pts = sorted(mile_pts, key=lambda p: p.elapsed_seconds)

        # Timing
        start_elapsed = mile_pts[0].elapsed_seconds
        end_elapsed = mile_pts[-1].elapsed_seconds

        # Average pace (s/km) — use points with valid pace
        pace_pts = [p for p in mile_pts if p.pace_seconds_per_km is not None and p.pace_seconds_per_km > 0]
        if pace_pts:
            avg_pace = mean(p.pace_seconds_per_km for p in pace_pts)
        else:
            # Derive from elapsed time and distance
            elapsed_s = end_elapsed - start_elapsed
            if elapsed_s > 0:
                avg_pace = (elapsed_s / METERS_PER_MILE) * 1000.0
            else:
                avg_pace = 0.0

        # Average HR
        hr_pts = [p for p in mile_pts if p.heart_rate is not None]
        avg_hr = mean(p.heart_rate for p in hr_pts) if hr_pts else 0.0

        # Grade
        grade_pct = _grade_pct_for_segment(mile_pts)
        grade_decimal = grade_pct / 100.0

        # Grade-adjusted pace (GAP)
        if avg_pace > 0:
            gap = grade_adjusted_pace(avg_pace, grade_decimal)
        else:
            gap = avg_pace

        # HR zone distribution
        hr_zones = _hr_zone_distribution(mile_pts, max_hr)

        segments.append(RunSegment(
            label=f"Mile {mile_index + 1}",
            start_elapsed_s=start_elapsed,
            end_elapsed_s=end_elapsed,
            avg_pace_s_per_km=round(avg_pace, 2),
            avg_hr=round(avg_hr, 1),
            grade_pct=round(grade_pct, 2),
            gap_s_per_km=round(gap, 2),
            hr_zone_distribution=hr_zones,
        ))

        mile_index += 1

    return segments
