"""
TimeseriesPoint dataclass and conversion from raw FIT parser dicts.

TimeseriesPoint is the universal in-memory representation used by all analysis
modules. It is a plain Python dataclass — no SQLModel, no DB dependencies.
Analysis functions take List[TimeseriesPoint] and return pure results.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class TimeseriesPoint:
    """
    One measurement sample from a Garmin activity.
    Typically ~1 per second from a Forerunner 245.
    All fields except elapsed_seconds are optional (device may not record all metrics).
    """

    elapsed_seconds: int
    heart_rate: Optional[int] = None          # bpm
    pace_seconds_per_km: Optional[float] = None  # seconds per kilometer
    speed_ms: Optional[float] = None          # m/s (raw)
    elevation_meters: Optional[float] = None  # meters above sea level
    cadence_spm: Optional[int] = None         # steps per minute
    distance_meters: Optional[float] = None   # cumulative from activity start
    lat: Optional[float] = None               # decimal degrees
    lon: Optional[float] = None               # decimal degrees
    temperature_c: Optional[float] = None     # Celsius


def datapoints_to_timeseries(datapoints: List[Dict[str, Any]]) -> List[TimeseriesPoint]:
    """
    Convert a list of raw FIT parser dicts (from fit_parser.parse_fit_file)
    into TimeseriesPoint instances.

    This is the bridge between the persistence layer (dict from FIT parser or
    DB ActivityDatapoint) and the analysis layer.
    """
    return [
        TimeseriesPoint(
            elapsed_seconds=dp["elapsed_seconds"],
            heart_rate=dp.get("heart_rate"),
            pace_seconds_per_km=dp.get("pace_seconds_per_km"),
            speed_ms=dp.get("speed_ms"),
            elevation_meters=dp.get("elevation_meters"),
            cadence_spm=dp.get("cadence_spm"),
            distance_meters=dp.get("distance_meters"),
            lat=dp.get("lat"),
            lon=dp.get("lon"),
            temperature_c=dp.get("temperature_c"),
        )
        for dp in datapoints
    ]
