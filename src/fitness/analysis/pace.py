"""
Grade-adjusted pace calculations and pace formatting utilities.

Uses the Minetti et al. (2002) metabolic cost of running on slopes formula,
the same model used by Strava for grade-adjusted pace.

Reference: Minetti AE et al. "Energy cost of walking and running at extreme
uphill and downhill slopes." J Appl Physiol. 2002.
"""
from typing import Optional

# 1 mile in kilometers
_KM_PER_MILE = 1.60934


def minetti_grade_multiplier(grade: float) -> float:
    """
    Compute the metabolic cost multiplier for running at a given grade.

    Uses the Minetti polynomial formula. Values > 1 mean the effort costs
    more than flat running; values < 1 mean it costs less.

    Note: very steep downhills (-15%+) increase cost due to eccentric
    braking load — the curve is not monotonic.

    Args:
        grade: slope as a decimal (0.10 = 10% uphill, -0.05 = 5% downhill).
               Clamped to [-0.45, 0.45] to avoid polynomial blow-up.

    Returns:
        Multiplier ≥ 0.0 relative to flat effort.
    """
    g = max(-0.45, min(0.45, grade))
    # Minetti polynomial for metabolic rate (W/kg per m/s) as a function of grade
    # Normalized so that g=0 → multiplier=1.0
    factor = (
        155.4 * g**5
        - 30.4 * g**4
        - 43.3 * g**3
        + 46.3 * g**2
        + 19.5 * g
        + 3.6
    )
    # At g=0: factor = 3.6; divide by 3.6 to normalize
    flat_cost = 3.6
    return factor / flat_cost


def grade_adjusted_pace(pace_s_per_km: float, grade: float) -> float:
    """
    Compute grade-adjusted pace (GAP) — the equivalent flat-ground pace
    that represents the same physiological effort as running at `pace_s_per_km`
    on terrain with the given grade.

    - Uphill: GAP < actual pace (you were working harder than the pace shows)
    - Downhill: GAP > actual pace (you were working less hard than the pace shows)

    Args:
        pace_s_per_km: actual pace in seconds per kilometer
        grade: slope as a decimal (positive = uphill)

    Returns:
        Grade-adjusted pace in seconds per kilometer
    """
    multiplier = minetti_grade_multiplier(grade)
    return pace_s_per_km / multiplier


def compute_grade(
    elevation_start: float,
    elevation_end: float,
    distance_meters: float,
) -> float:
    """
    Compute the slope grade between two elevation points.

    Args:
        elevation_start: starting elevation in meters
        elevation_end: ending elevation in meters
        distance_meters: horizontal distance (or path distance) in meters

    Returns:
        Grade as a decimal (0.10 = 10% uphill). Returns 0.0 if distance is zero.
    """
    if distance_meters <= 0:
        return 0.0
    return (elevation_end - elevation_start) / distance_meters


def pace_from_speed_ms(speed_ms: float) -> Optional[float]:
    """
    Convert speed in m/s to pace in seconds per kilometer.

    Args:
        speed_ms: speed in meters per second

    Returns:
        Pace in seconds/km, or None if speed is zero or negative.
    """
    if speed_ms <= 0:
        return None
    return 1000.0 / speed_ms


def format_pace(pace_s_per_km: float, unit: str = "mi") -> str:
    """
    Format a pace (seconds/km) as a human-readable string.

    Args:
        pace_s_per_km: pace in seconds per kilometer
        unit: "km" for per-kilometer, "mi" for per-mile (default)

    Returns:
        Formatted string like "8:30/mi" or "5:17/km"
    """
    if unit == "mi":
        pace_s = pace_s_per_km * _KM_PER_MILE
        unit_label = "mi"
    else:
        pace_s = pace_s_per_km
        unit_label = "km"

    minutes = int(pace_s) // 60
    seconds = int(pace_s) % 60
    return f"{minutes}:{seconds:02d}/{unit_label}"
