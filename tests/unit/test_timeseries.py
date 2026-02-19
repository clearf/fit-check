"""Tests for TimeseriesPoint and datapoints_to_timeseries conversion."""
import pytest

from fitness.analysis.timeseries import TimeseriesPoint, datapoints_to_timeseries


class TestTimeseriesPoint:
    def test_required_field_only(self):
        pt = TimeseriesPoint(elapsed_seconds=60)
        assert pt.elapsed_seconds == 60
        assert pt.heart_rate is None
        assert pt.pace_seconds_per_km is None
        assert pt.elevation_meters is None

    def test_all_fields(self):
        pt = TimeseriesPoint(
            elapsed_seconds=120,
            heart_rate=148,
            pace_seconds_per_km=450.0,
            speed_ms=2.222,
            elevation_meters=105.3,
            cadence_spm=162,
            distance_meters=266.6,
            lat=47.6062,
            lon=-122.3321,
            temperature_c=14.5,
        )
        assert pt.heart_rate == 148
        assert pt.lat == 47.6062


class TestDatapointsToTimeseries:
    def test_converts_list_of_dicts(self):
        raw = [
            {
                "elapsed_seconds": 0,
                "heart_rate": 130,
                "speed_ms": 2.5,
                "pace_seconds_per_km": 400.0,
                "elevation_meters": 100.0,
                "cadence_spm": 158,
                "distance_meters": 0.0,
                "lat": 47.6,
                "lon": -122.3,
                "temperature_c": 15.0,
            },
            {
                "elapsed_seconds": 5,
                "heart_rate": 132,
                "speed_ms": 2.6,
                "pace_seconds_per_km": 384.6,
                "elevation_meters": 100.5,
                "cadence_spm": 160,
                "distance_meters": 12.5,
                "lat": 47.601,
                "lon": -122.301,
                "temperature_c": 15.0,
            },
        ]
        result = datapoints_to_timeseries(raw)
        assert len(result) == 2
        assert all(isinstance(p, TimeseriesPoint) for p in result)
        assert result[0].elapsed_seconds == 0
        assert result[1].heart_rate == 132

    def test_handles_missing_optional_fields(self):
        raw = [{"elapsed_seconds": 10}]
        result = datapoints_to_timeseries(raw)
        assert len(result) == 1
        assert result[0].heart_rate is None
        assert result[0].elevation_meters is None

    def test_empty_list(self):
        assert datapoints_to_timeseries([]) == []

    def test_preserves_order(self):
        raw = [{"elapsed_seconds": i} for i in [0, 5, 10, 15, 20]]
        result = datapoints_to_timeseries(raw)
        elapsed = [p.elapsed_seconds for p in result]
        assert elapsed == [0, 5, 10, 15, 20]
