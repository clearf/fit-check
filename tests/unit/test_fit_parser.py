"""Tests for FIT file parser — written first (TDD).

These tests run against tests/fixtures/sample_activity.fit.
Export a run from Garmin Connect: Activity → ⚙️ → Export Original (.fit)
Place the file at tests/fixtures/sample_activity.fit before running.
"""
from pathlib import Path

import pytest

from fitness.garmin.fit_parser import FitParseError, parse_fit_file

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SAMPLE_FIT = FIXTURES_DIR / "sample_activity.fit"


@pytest.fixture(scope="module")
def parsed_datapoints():
    """Parse the sample FIT file once for all tests in this module."""
    if not SAMPLE_FIT.exists():
        pytest.skip(
            f"No FIT fixture found at {SAMPLE_FIT}. "
            "Export a run from Garmin Connect → Activity → ⚙️ → Export Original"
        )
    return parse_fit_file(SAMPLE_FIT)


class TestFitParserOutput:
    def test_returns_non_empty_list(self, parsed_datapoints):
        assert len(parsed_datapoints) > 0

    def test_one_hour_run_has_at_least_600_points(self, parsed_datapoints):
        """Even a 10-minute run should have at least 600 data points at 1s intervals."""
        assert len(parsed_datapoints) >= 600

    def test_each_point_has_elapsed_seconds(self, parsed_datapoints):
        for pt in parsed_datapoints:
            assert "elapsed_seconds" in pt
            assert isinstance(pt["elapsed_seconds"], int)
            assert pt["elapsed_seconds"] >= 0

    def test_elapsed_seconds_monotonically_increasing(self, parsed_datapoints):
        elapsed = [pt["elapsed_seconds"] for pt in parsed_datapoints]
        assert elapsed == sorted(elapsed), "elapsed_seconds must be monotonically increasing"

    def test_heart_rate_values_in_valid_range(self, parsed_datapoints):
        hr_points = [pt for pt in parsed_datapoints if pt.get("heart_rate") is not None]
        assert len(hr_points) > 0, "Expected at least some HR data points"
        for pt in hr_points:
            assert 40 <= pt["heart_rate"] <= 230, (
                f"HR {pt['heart_rate']} out of valid range at elapsed={pt['elapsed_seconds']}"
            )

    def test_pace_derived_correctly_from_speed(self, parsed_datapoints):
        """pace_seconds_per_km should equal 1000 / speed_ms where speed_ms > 0."""
        speed_points = [
            pt for pt in parsed_datapoints
            if pt.get("speed_ms") and pt["speed_ms"] > 0
            and pt.get("pace_seconds_per_km") is not None
        ]
        assert len(speed_points) > 0
        for pt in speed_points:
            expected_pace = 1000.0 / pt["speed_ms"]
            assert abs(pt["pace_seconds_per_km"] - expected_pace) < 0.1, (
                f"Pace mismatch: expected {expected_pace:.1f}, got {pt['pace_seconds_per_km']:.1f}"
            )

    def test_pace_values_in_realistic_running_range(self, parsed_datapoints):
        """Running pace should be between 3:00/km (elite sprint) and 20:00/km (fast walk)."""
        pace_points = [
            pt for pt in parsed_datapoints
            if pt.get("pace_seconds_per_km") and pt["pace_seconds_per_km"] > 0
        ]
        assert len(pace_points) > 0
        realistic = [pt for pt in pace_points if 180 <= pt["pace_seconds_per_km"] <= 1200]
        # Allow some GPS noise / standing-still points — at least 80% should be realistic
        assert len(realistic) / len(pace_points) >= 0.80, (
            f"Too many unrealistic pace points: {len(pace_points) - len(realistic)} out of {len(pace_points)}"
        )

    def test_elevation_data_present(self, parsed_datapoints):
        elev_points = [pt for pt in parsed_datapoints if pt.get("elevation_meters") is not None]
        assert len(elev_points) > 0, "Expected elevation data in FIT file"

    def test_elevation_values_realistic(self, parsed_datapoints):
        """Elevation should be between -100m (below sea level) and 5000m (high altitude run)."""
        elev_points = [pt for pt in parsed_datapoints if pt.get("elevation_meters") is not None]
        for pt in elev_points:
            assert -100 <= pt["elevation_meters"] <= 5000, (
                f"Elevation {pt['elevation_meters']} out of realistic range"
            )


class TestFitParserCoordinates:
    def test_lat_lon_converted_from_semicircles(self, parsed_datapoints):
        """Garmin stores lat/lon as semicircles. Parser must convert to degrees."""
        gps_points = [
            pt for pt in parsed_datapoints
            if pt.get("lat") is not None and pt.get("lon") is not None
        ]
        assert len(gps_points) > 0, "Expected GPS data in FIT file"
        for pt in gps_points:
            assert -90 <= pt["lat"] <= 90, f"lat {pt['lat']} out of degrees range"
            assert -180 <= pt["lon"] <= 180, f"lon {pt['lon']} out of degrees range"

    def test_lat_lon_not_semicircle_values(self, parsed_datapoints):
        """Semicircle values would be in the billions — ensure conversion happened."""
        gps_points = [pt for pt in parsed_datapoints if pt.get("lat") is not None]
        for pt in gps_points:
            assert abs(pt["lat"]) < 180, (
                f"lat {pt['lat']} looks like unconverted semicircles"
            )


class TestFitParserCadence:
    def test_cadence_values_realistic_for_running(self, parsed_datapoints):
        """Running cadence: 130-200 spm is realistic. 0 during walk breaks is ok."""
        cad_points = [
            pt for pt in parsed_datapoints
            if pt.get("cadence_spm") is not None and pt["cadence_spm"] > 0
        ]
        if len(cad_points) == 0:
            pytest.skip("No cadence data in this FIT file")
        for pt in cad_points:
            assert 100 <= pt["cadence_spm"] <= 230, (
                f"Cadence {pt['cadence_spm']} spm out of realistic range"
            )


class TestFitParserEdgeCases:
    def test_zero_speed_does_not_produce_pace(self, parsed_datapoints):
        """Division by zero guard: speed_ms=0 should yield pace=None, not infinity."""
        zero_speed = [pt for pt in parsed_datapoints if pt.get("speed_ms") == 0.0]
        for pt in zero_speed:
            assert pt.get("pace_seconds_per_km") is None, (
                "Zero speed should produce None pace, not a division error"
            )

    def test_invalid_path_raises_fit_parse_error(self):
        with pytest.raises(FitParseError):
            parse_fit_file(Path("/nonexistent/file.fit"))

    def test_non_fit_file_raises_fit_parse_error(self, tmp_path):
        bad_file = tmp_path / "not_a_fit.fit"
        bad_file.write_bytes(b"this is not a valid FIT file")
        with pytest.raises(FitParseError):
            parse_fit_file(bad_file)
