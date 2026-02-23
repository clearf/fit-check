"""
Local chart preview using fixture data.

Builds a RunReport from the test fixtures (no DB or Garmin connection needed)
and renders the overview chart to /tmp/preview_chart.png.

Usage:
    python -m fitness.scripts.preview_chart
    # or
    source .venv/bin/activate && python scripts/preview_chart.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

# Allow running directly from repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fitness.analysis.bonk import BonkEvent, detect_bonk_per_segment
from fitness.analysis.galloway import GallowaySegments, detect_galloway_segments
from fitness.analysis.heart_rate import detect_cardiac_drift
from fitness.analysis.run_report import RunReport
from fitness.analysis.segments import LapSegment, build_lap_segments, build_mile_segments
from fitness.analysis.timeseries import TimeseriesPoint, datapoints_to_timeseries
from fitness.garmin.fit_parser import parse_fit_file
from fitness.garmin.normalizer import normalize_typed_split
from fitness.models.activity import Activity, ActivitySplit
from fitness.prompts.charts import make_run_overview_chart

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def load_splits() -> list:
    """Load lapDTOs from fixture and convert to ActivitySplit objects."""
    with open(FIXTURES / "garmin_activity_splits.json") as f:
        data = json.load(f)

    laps = data["lapDTOs"]
    # Compute elapsed seconds relative to first lap start
    def _parse(s):
        # "2026-02-18T19:22:38.0" → strip fractional seconds
        return datetime.strptime(s.split(".")[0], "%Y-%m-%dT%H:%M:%S")

    t0 = _parse(laps[0]["startTimeGMT"])
    splits = []
    for i, lap in enumerate(laps):
        t = _parse(lap["startTimeGMT"])
        elapsed = int((t - t0).total_seconds())
        normalized = normalize_typed_split(lap, split_index=i)
        normalized["start_elapsed_seconds"] = elapsed
        sp = ActivitySplit(
            id=i,
            activity_id=1,
            user_id=1,
            **normalized,
        )
        splits.append(sp)
    return splits


def load_real_timeseries() -> list:
    """Parse the real FIT fixture to get per-second timeseries."""
    datapoints = parse_fit_file(FIXTURES / "sample_activity.fit")
    return datapoints_to_timeseries(datapoints)


def main():
    print("Loading fixture splits...")
    splits = load_splits()
    print(f"  {len(splits)} laps loaded")

    print("Building timeseries from FIT file...")
    timeseries = load_real_timeseries()
    print(f"  {len(timeseries)} points")

    print("Building lap segments...")
    lap_segments = build_lap_segments(splits, timeseries)
    for seg in lap_segments:
        print(f"  [{seg.split_type:18s}] {seg.label:12s}  {seg.distance_miles:.2f}mi  "
              f"pace={seg.avg_pace_s_per_km:.0f}s/km  hr={seg.avg_hr:.0f}")

    # Dummy activity
    activity = Activity(
        id=1,
        garmin_activity_id="preview",
        name="8×800m Intervals (preview)",
        activity_type="running",
        start_time_utc=datetime(2026, 2, 18, 19, 22, 38),
        duration_seconds=sum(sp.duration_seconds for sp in splits),
        distance_meters=sum(sp.distance_meters for sp in splits),
        avg_hr=130.0,
        max_hr=155.0,
    )

    mile_segments = build_mile_segments(timeseries)
    bonk_events = detect_bonk_per_segment(timeseries, lap_segments)
    cardiac_drift = detect_cardiac_drift(timeseries)
    galloway = detect_galloway_segments([
        {
            "splitType": sp.split_type.replace("_segment", "").upper(),
            "totalElapsedTime": sp.duration_seconds,
            "totalDistance": sp.distance_meters,
            "averageHR": sp.avg_hr,
            "averageSpeed": (1000.0 / sp.avg_pace_seconds_per_km) if sp.avg_pace_seconds_per_km else None,
        }
        for sp in splits
    ])

    report = RunReport(
        activity=activity,
        timeseries=timeseries,
        mile_segments=mile_segments,
        lap_segments=lap_segments,
        bonk_events=bonk_events,
        cardiac_drift=cardiac_drift,
        galloway=galloway,
    )

    print(f"\nBonk events detected: {len(bonk_events)}")

    print("\nRendering overview chart...")
    png_bytes, caption = make_run_overview_chart(report)
    out = Path("/tmp/preview_chart.png")
    out.write_bytes(png_bytes)
    print(f"  Saved to {out}  ({len(png_bytes)//1024}KB)")
    print(f"  Caption: {caption}")

    print("\nDone. Open /tmp/preview_chart.png to inspect.")


if __name__ == "__main__":
    main()
