"""
Segment builders for run analysis.

Two segment types:
  - LapSegment: one per Garmin lap (Warmup / Run N / Walk N / Cooldown),
                built from ActivitySplit records stored in the DB.
  - RunSegment: legacy per-mile segments (kept for backward compat with prompts).

LapSegment is the preferred representation for charts and bonk detection.
RunSegment is still produced for the AI debrief prompt.

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

# A lap whose run_segment distance is below this threshold is treated as
# Warmup (if first) or Cooldown (if last).
WARMUP_COOLDOWN_DISTANCE_M = 1000.0


@dataclass
class LapSegment:
    """
    Statistics for one Garmin lap (intensityType-based segment).

    Labels follow the pattern:
      Warmup | Run 1, Run 2, … | Walk 1, Walk 2, … | Cooldown
    """
    label: str                          # "Warmup", "Run 1", "Walk 1", "Cooldown"
    split_type: str                     # "run_segment" | "walk_segment"
    start_elapsed_s: int
    end_elapsed_s: int
    duration_seconds: float
    distance_meters: float
    avg_pace_s_per_km: float
    avg_hr: float
    hr_zone_distribution: Dict[int, float] = field(default_factory=dict)

    # Target pace from the linked workout step (None when no structured target)
    target_pace_slow_s_per_km: Optional[float] = None   # slow end of pace band (more s/km)
    target_pace_fast_s_per_km: Optional[float] = None   # fast end of pace band (fewer s/km)

    @property
    def distance_miles(self) -> float:
        return self.distance_meters / METERS_PER_MILE

    def is_active(self) -> bool:
        """True for run/warmup/cooldown laps (eligible for bonk detection baseline).
        Walk and recovery segments are excluded."""
        return self.split_type in ("run_segment", "warmup_segment", "cooldown_segment")


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


def build_lap_segments(
    splits,  # List[ActivitySplit] — avoid circular import by using duck typing
    timeseries: List[TimeseriesPoint],
    max_hr: int = MAX_HR_DEFAULT,
) -> List[LapSegment]:
    """
    Build LapSegment objects from stored ActivitySplit records.

    Labeling priority (first match wins):
      1. warmup_segment type → "Warmup"
      2. cooldown_segment type → "Cooldown"
      3. Heuristic: first run_segment with distance < WARMUP_COOLDOWN_DISTANCE_M → "Warmup"
      4. Heuristic: last segment with distance < WARMUP_COOLDOWN_DISTANCE_M → "Cooldown"
      5. walk_segment / recovery → "Walk 1", "Walk 2", …
      6. run_segment → "Run 1", "Run 2", …

    HR zone distribution is computed from the timeseries points that fall
    within each lap's elapsed-second window.  If timeseries is empty, zones
    are all-zero dicts.

    Args:
        splits: Ordered list of ActivitySplit model instances.
        timeseries: Full activity timeseries (may be empty).
        max_hr: Athlete max HR for zone classification.

    Returns:
        List of LapSegment, one per split, in order.
    """
    if not splits:
        return []

    n = len(splits)
    # Pre-compute heuristic warmup/cooldown indices (fallback when explicit
    # intensityType wasn't preserved as warmup_segment/cooldown_segment).
    heuristic_warmup_idx: Optional[int] = None
    heuristic_cooldown_idx: Optional[int] = None

    if splits[0].split_type == "run_segment" and splits[0].distance_meters < WARMUP_COOLDOWN_DISTANCE_M:
        heuristic_warmup_idx = 0

    if n > 1 and splits[-1].split_type in ("run_segment", "walk_segment") \
            and splits[-1].distance_meters < WARMUP_COOLDOWN_DISTANCE_M:
        if (n - 1) != heuristic_warmup_idx:
            heuristic_cooldown_idx = n - 1

    run_counter = 0
    walk_counter = 0
    segments: List[LapSegment] = []

    for i, sp in enumerate(splits):
        start_s = sp.start_elapsed_seconds
        end_s = start_s + int(sp.duration_seconds)

        # HR zones from timeseries window
        window_pts = [
            p for p in timeseries
            if start_s <= p.elapsed_seconds < end_s
        ]
        zones = _hr_zone_distribution(window_pts, max_hr)

        # Determine label — explicit types take priority over heuristics
        if sp.split_type == "warmup_segment":
            label = "Warmup"
        elif sp.split_type == "cooldown_segment":
            label = "Cooldown"
        elif i == heuristic_warmup_idx:
            label = "Warmup"
        elif i == heuristic_cooldown_idx:
            label = "Cooldown"
        elif sp.split_type == "walk_segment":
            walk_counter += 1
            label = f"Walk {walk_counter}"
        else:
            run_counter += 1
            label = f"Run {run_counter}"

        segments.append(LapSegment(
            label=label,
            split_type=sp.split_type,
            start_elapsed_s=start_s,
            end_elapsed_s=end_s,
            duration_seconds=sp.duration_seconds,
            distance_meters=sp.distance_meters,
            avg_pace_s_per_km=sp.avg_pace_seconds_per_km or 0.0,
            avg_hr=sp.avg_hr or 0.0,
            hr_zone_distribution=zones,
            target_pace_slow_s_per_km=getattr(sp, "target_pace_slow_s_per_km", None),
            target_pace_fast_s_per_km=getattr(sp, "target_pace_fast_s_per_km", None),
        ))

    return segments


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
