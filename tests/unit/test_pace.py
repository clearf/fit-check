"""Tests for grade-adjusted pace analysis — written first (TDD)."""
import pytest

from fitness.analysis.pace import (
    compute_grade,
    format_pace,
    grade_adjusted_pace,
    minetti_grade_multiplier,
    pace_from_speed_ms,
)


class TestMinettiGradeMultiplier:
    def test_flat_grade_returns_one(self):
        """At zero grade, no adjustment needed."""
        assert minetti_grade_multiplier(0.0) == pytest.approx(1.0, abs=0.01)

    def test_uphill_grade_greater_than_one(self):
        """Uphill costs more effort → multiplier > 1."""
        assert minetti_grade_multiplier(0.10) > 1.0

    def test_10_percent_uphill_approx_1_66(self):
        """At 10% grade, Minetti formula gives ~1.66 multiplier.
        Running uphill is substantially costly — higher than simpler approximations.
        This is the published Minetti (2002) value.
        """
        assert minetti_grade_multiplier(0.10) == pytest.approx(1.658, abs=0.01)

    def test_shallow_downhill_less_than_one(self):
        """Slight downhill is easier — meaningful savings at -5%."""
        result = minetti_grade_multiplier(-0.05)
        assert result == pytest.approx(0.763, abs=0.01)
        assert result < 1.0

    def test_steep_downhill_costs_more_than_moderate_downhill(self):
        """Minetti curve minimum is around -20%. Beyond that, cost rises again
        (eccentric braking on very steep terrain).
        -30% should cost more than -20%.
        """
        m_20 = minetti_grade_multiplier(-0.20)
        m_30 = minetti_grade_multiplier(-0.30)
        assert m_30 > m_20, "Steeper than -20% downhill should cost more"

    def test_grade_clamped_at_max(self):
        """Extreme grades are clamped to [-0.45, 0.45] to avoid polynomial blow-up."""
        result_high = minetti_grade_multiplier(0.60)
        result_clamped = minetti_grade_multiplier(0.45)
        assert result_high == result_clamped

    def test_grade_clamped_at_min(self):
        result_low = minetti_grade_multiplier(-0.60)
        result_clamped = minetti_grade_multiplier(-0.45)
        assert result_low == result_clamped

    @pytest.mark.parametrize("grade", [-0.45, -0.30, -0.10, 0, 0.10, 0.20, 0.30, 0.45])
    def test_multiplier_always_positive(self, grade):
        assert minetti_grade_multiplier(grade) > 0


class TestGradeAdjustedPace:
    def test_uphill_gap_faster_than_actual(self):
        """
        Running at 9:00/km (540s/km) up 10% grade.
        GAP should be ~7:30/km — the flat equivalent effort is faster than actual.
        """
        gap = grade_adjusted_pace(pace_s_per_km=540.0, grade=0.10)
        assert gap < 540.0

    def test_uphill_gap_approximate_value(self):
        """9:00/km (540s) at 10% grade → GAP ≈ 5:26/km (326s).
        Minetti multiplier at 10% is 1.658, so 540/1.658 ≈ 326s — a 3:26 flat-equivalent.
        Running 9:00/km up a 10% grade is hard work.
        """
        gap = grade_adjusted_pace(pace_s_per_km=540.0, grade=0.10)
        assert gap == pytest.approx(325.7, abs=5.0)

    def test_flat_gap_equals_actual(self):
        """On flat ground, GAP = actual pace."""
        gap = grade_adjusted_pace(pace_s_per_km=480.0, grade=0.0)
        assert gap == pytest.approx(480.0, abs=1.0)

    def test_downhill_gap_slower_than_actual(self):
        """Downhill: actual pace is fast but GAP reflects the real effort."""
        gap = grade_adjusted_pace(pace_s_per_km=400.0, grade=-0.08)
        assert gap > 400.0


class TestComputeGrade:
    def test_flat_segment_zero_grade(self):
        grade = compute_grade(elevation_start=100.0, elevation_end=100.0, distance_meters=500.0)
        assert grade == pytest.approx(0.0, abs=0.001)

    def test_10_percent_uphill(self):
        # +10m over 100m horizontal = 10% grade
        grade = compute_grade(elevation_start=100.0, elevation_end=110.0, distance_meters=100.0)
        assert grade == pytest.approx(0.10, abs=0.001)

    def test_negative_grade_downhill(self):
        grade = compute_grade(elevation_start=110.0, elevation_end=100.0, distance_meters=100.0)
        assert grade == pytest.approx(-0.10, abs=0.001)

    def test_zero_distance_returns_zero(self):
        """Guard against division by zero."""
        grade = compute_grade(elevation_start=100.0, elevation_end=110.0, distance_meters=0.0)
        assert grade == 0.0


class TestFormatPace:
    @pytest.mark.parametrize("pace_s_per_km,expected_per_km,expected_per_mi", [
        (300.0, "5:00/km", "8:03/mi"),   # 5:00/km = 8:03/mi
        (360.0, "6:00/km", "9:39/mi"),   # 6:00/km = 9:39/mi
        (480.0, "8:00/km", "12:52/mi"),  # 8:00/km = 12:52/mi
    ])
    def test_format_per_km(self, pace_s_per_km, expected_per_km, expected_per_mi):
        assert format_pace(pace_s_per_km, unit="km") == expected_per_km

    def test_format_per_mile(self):
        # 360 s/km * 1.60934 = 579.4 s/mi ≈ 9:39/mi
        result = format_pace(360.0, unit="mi")
        assert result == "9:39/mi"

    def test_format_defaults_to_miles(self):
        result = format_pace(360.0)
        assert "/mi" in result


class TestPaceFromSpeedMs:
    def test_2_778_ms_is_6_min_per_km(self):
        # 2.778 m/s * 3.6 = 10 km/h → 6:00/km (360 s/km)
        pace = pace_from_speed_ms(2.778)
        assert pace == pytest.approx(360.0, abs=1.0)

    def test_zero_speed_returns_none(self):
        assert pace_from_speed_ms(0.0) is None

    def test_negative_speed_returns_none(self):
        assert pace_from_speed_ms(-1.0) is None
