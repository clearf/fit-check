"""
Galloway run/walk segment detection.

Detects whether a run used a Galloway (run/walk) strategy by inspecting
typed splits from the Garmin Connect API. For the MVP we assume all runs
are compliant with the plan — this module simply detects the pattern and
computes per-phase statistics so the segment builder and prompt layer can
distinguish run-phase data from walk-break data.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class GallowaySegments:
    """Result of Galloway run/walk detection."""
    is_galloway: bool
    run_segment_count: int
    walk_segment_count: int
    avg_run_pace_s_per_km: Optional[float]   # None if no run segments
    avg_walk_pace_s_per_km: Optional[float]  # None if no walk segments
    avg_run_hr: Optional[float]              # None if no HR data
    avg_walk_hr: Optional[float]             # None if no HR data


def detect_galloway_segments(
    typed_splits: List[dict],
    min_walk_segments: int = 3,
) -> GallowaySegments:
    """
    Detect Galloway run/walk pattern from garminconnect typed splits.

    Args:
        typed_splits: List of split dicts from get_activity_typed_splits().
                      Each dict has at minimum: splitType, totalElapsedTime,
                      totalDistance, averageSpeed, averageHR.
        min_walk_segments: Minimum number of walk segments required to call
                           this a Galloway run (default 3).

    Returns:
        GallowaySegments with detection result and per-phase statistics.
    """
    if not typed_splits:
        return GallowaySegments(
            is_galloway=False,
            run_segment_count=0,
            walk_segment_count=0,
            avg_run_pace_s_per_km=None,
            avg_walk_pace_s_per_km=None,
            avg_run_hr=None,
            avg_walk_hr=None,
        )

    run_splits = [
        s for s in typed_splits
        if str(s.get("splitType", "")).upper() == "RUN"
    ]
    walk_splits = [
        s for s in typed_splits
        if str(s.get("splitType", "")).upper() == "WALK"
    ]

    is_galloway = len(walk_splits) >= min_walk_segments

    def _avg_pace(splits: List[dict]) -> Optional[float]:
        """Weighted average pace (s/km) by distance."""
        total_dist = sum(s.get("totalDistance", 0) for s in splits)
        if total_dist <= 0:
            # Fall back to averaging averageSpeed
            speeds = [s["averageSpeed"] for s in splits if s.get("averageSpeed")]
            if not speeds:
                return None
            avg_speed = sum(speeds) / len(speeds)
            return 1000.0 / avg_speed if avg_speed > 0 else None

        # Weighted by distance: total_time / total_dist * 1000
        total_time = sum(s.get("totalElapsedTime", 0) for s in splits)
        return (total_time / total_dist) * 1000.0 if total_dist > 0 else None

    def _avg_hr(splits: List[dict]) -> Optional[float]:
        """Simple mean of averageHR across splits that have HR data."""
        hrs = [s["averageHR"] for s in splits if s.get("averageHR") is not None]
        return sum(hrs) / len(hrs) if hrs else None

    return GallowaySegments(
        is_galloway=is_galloway,
        run_segment_count=len(run_splits),
        walk_segment_count=len(walk_splits),
        avg_run_pace_s_per_km=_avg_pace(run_splits) if run_splits else None,
        avg_walk_pace_s_per_km=_avg_pace(walk_splits) if walk_splits else None,
        avg_run_hr=_avg_hr(run_splits) if run_splits else None,
        avg_walk_hr=_avg_hr(walk_splits) if walk_splits else None,
    )
