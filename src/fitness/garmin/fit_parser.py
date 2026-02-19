"""
FIT file parser: converts Garmin .fit binary files into a list of datapoint dicts.

Each dict corresponds to one FIT 'record' message (typically ~1 per second on
a Forerunner 245) and contains the fields we care about for run analysis.

Field mapping from FIT to our schema:
  FIT field             → our field
  timestamp             → elapsed_seconds (relative to first record)
  heart_rate            → heart_rate (bpm, int)
  enhanced_speed        → speed_ms (m/s, float) + pace_seconds_per_km (derived)
  enhanced_altitude     → elevation_meters (float)
  cadence               → cadence_spm (steps/min, int)
  distance              → distance_meters (cumulative, float)
  position_lat          → lat (degrees, converted from semicircles)
  position_long         → lon (degrees, converted from semicircles)
  temperature           → temperature_c (float)
"""

from pathlib import Path
from typing import Dict, Any, List, Optional

import fitparse


# Garmin semicircle → degree conversion constant
# Garmin stores lat/lon as 32-bit signed integers in "semicircles"
# Degrees = semicircles * (180 / 2^31)
_SEMICIRCLE_TO_DEGREES = 180.0 / (2**31)


class FitParseError(Exception):
    """Raised when a FIT file cannot be parsed."""


def parse_fit_file(path: Path) -> List[Dict[str, Any]]:
    """
    Parse a Garmin .fit file and return a list of per-second datapoint dicts.

    Args:
        path: Path to the .fit file

    Returns:
        List of dicts, one per 'record' message, with keys:
        elapsed_seconds, heart_rate, speed_ms, pace_seconds_per_km,
        elevation_meters, cadence_spm, distance_meters, lat, lon, temperature_c

    Raises:
        FitParseError: if the file doesn't exist or cannot be parsed as a valid FIT file
    """
    if not path.exists():
        raise FitParseError(f"FIT file not found: {path}")

    try:
        fit = fitparse.FitFile(str(path))
        records = list(fit.get_messages("record"))
    except Exception as exc:
        raise FitParseError(f"Failed to parse FIT file {path}: {exc}") from exc

    if not records:
        raise FitParseError(f"No 'record' messages found in FIT file: {path}")

    datapoints: List[Dict[str, Any]] = []
    first_timestamp: Optional[Any] = None

    for record in records:
        values = record.get_values()
        timestamp = values.get("timestamp")
        if timestamp is None:
            continue  # skip records without a timestamp

        if first_timestamp is None:
            first_timestamp = timestamp

        elapsed_seconds = int((timestamp - first_timestamp).total_seconds())

        # Speed → pace conversion (guard against division by zero)
        speed_ms: Optional[float] = None
        pace_s_per_km: Optional[float] = None
        raw_speed = values.get("enhanced_speed") or values.get("speed")
        if raw_speed is not None:
            speed_ms = float(raw_speed)
            if speed_ms > 0:
                pace_s_per_km = 1000.0 / speed_ms

        # Elevation: prefer enhanced_altitude (higher precision)
        elevation_meters: Optional[float] = None
        raw_alt = values.get("enhanced_altitude") or values.get("altitude")
        if raw_alt is not None:
            elevation_meters = float(raw_alt)

        # GPS coordinates: convert from Garmin semicircles to degrees
        lat: Optional[float] = None
        lon: Optional[float] = None
        raw_lat = values.get("position_lat")
        raw_lon = values.get("position_long")
        if raw_lat is not None:
            lat = raw_lat * _SEMICIRCLE_TO_DEGREES
        if raw_lon is not None:
            lon = raw_lon * _SEMICIRCLE_TO_DEGREES

        # Heart rate
        heart_rate: Optional[int] = None
        raw_hr = values.get("heart_rate")
        if raw_hr is not None:
            heart_rate = int(raw_hr)

        # Cadence (Forerunner 245 reports running cadence directly in steps/min)
        cadence_spm: Optional[int] = None
        raw_cad = values.get("cadence")
        if raw_cad is not None:
            cadence_spm = int(raw_cad)

        # Cumulative distance
        distance_meters: Optional[float] = None
        raw_dist = values.get("distance")
        if raw_dist is not None:
            distance_meters = float(raw_dist)

        # Temperature
        temperature_c: Optional[float] = None
        raw_temp = values.get("temperature")
        if raw_temp is not None:
            temperature_c = float(raw_temp)

        datapoints.append({
            "elapsed_seconds": elapsed_seconds,
            "heart_rate": heart_rate,
            "speed_ms": speed_ms,
            "pace_seconds_per_km": pace_s_per_km,
            "elevation_meters": elevation_meters,
            "cadence_spm": cadence_spm,
            "distance_meters": distance_meters,
            "lat": lat,
            "lon": lon,
            "temperature_c": temperature_c,
        })

    return datapoints
