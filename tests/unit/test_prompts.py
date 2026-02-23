"""Tests for prompt builders: debrief, trends, voice.

These tests focus on the structure and content of the rendered markdown
strings, not the exact wording — so Claude's system prompt can be tweaked
without breaking tests. We verify:
  - Required sections are present
  - Key data values appear in the output
  - Optional sections only appear when data is provided
"""
from datetime import datetime, date
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from fitness.analysis.bonk import BonkEvent
from fitness.analysis.galloway import GallowaySegments
from fitness.analysis.heart_rate import CardiacDriftEvent
from fitness.analysis.run_report import RunReport
from fitness.analysis.segments import RunSegment
from fitness.models.activity import Activity
from fitness.models.wellness import HRVRecord, SleepRecord
from fitness.prompts.debrief import build_debrief_prompt, build_debrief_system_prompt
from fitness.prompts.trends import build_trends_prompt
from fitness.prompts.voice import build_voice_query_prompt, build_whisper_prompt


# ─── Factories ────────────────────────────────────────────────────────────────

def make_activity(
    *,
    distance_meters: float = 8046.72,    # 5 miles
    duration_seconds: float = 2520.0,    # 42 min
    avg_hr: Optional[float] = 148.0,
    max_hr: Optional[float] = 172.0,
    avg_pace_seconds_per_km: Optional[float] = 312.0,  # ~8:20/mi
    total_ascent_meters: Optional[float] = 85.0,
    total_descent_meters: Optional[float] = 82.0,
    start_time_utc: Optional[datetime] = None,
    name: str = "Morning Run",
) -> Activity:
    act = Activity(
        garmin_activity_id="12345",
        name=name,
        activity_type="running",
        start_time_utc=start_time_utc or datetime(2025, 1, 15, 7, 30, 0),
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        avg_hr=avg_hr,
        max_hr=max_hr,
        avg_pace_seconds_per_km=avg_pace_seconds_per_km,
        total_ascent_meters=total_ascent_meters,
        total_descent_meters=total_descent_meters,
    )
    return act


def make_galloway(
    *,
    is_galloway: bool = True,
    run_segment_count: int = 8,
    walk_segment_count: int = 7,
    avg_run_pace: float = 290.0,
    avg_walk_pace: float = 600.0,
    avg_run_hr: float = 155.0,
    avg_walk_hr: float = 120.0,
) -> GallowaySegments:
    return GallowaySegments(
        is_galloway=is_galloway,
        run_segment_count=run_segment_count,
        walk_segment_count=walk_segment_count,
        avg_run_pace_s_per_km=avg_run_pace,
        avg_walk_pace_s_per_km=avg_walk_pace,
        avg_run_hr=avg_run_hr,
        avg_walk_hr=avg_walk_hr,
    )


def make_run_segment(
    label: int = 1,
    avg_pace: float = 312.0,
    avg_hr: float = 145.0,
    grade_pct: float = 0.0,
    gap_s_per_km: float = 312.0,
) -> RunSegment:
    return RunSegment(
        label=label,
        start_elapsed_s=0,
        end_elapsed_s=504,
        avg_pace_s_per_km=avg_pace,
        avg_hr=avg_hr,
        grade_pct=grade_pct,
        gap_s_per_km=gap_s_per_km,
        hr_zone_distribution={1: 0.1, 2: 0.3, 3: 0.3, 4: 0.25, 5: 0.05},
    )


def make_run_report(
    *,
    activity: Optional[Activity] = None,
    galloway: Optional[GallowaySegments] = None,
    mile_segments: Optional[List[RunSegment]] = None,
    lap_segments=None,
    bonk_events: Optional[List[BonkEvent]] = None,
    cardiac_drift: Optional[CardiacDriftEvent] = None,
    sleep: Optional[SleepRecord] = None,
    hrv: Optional[HRVRecord] = None,
    body_battery=None,
) -> RunReport:
    return RunReport(
        activity=activity or make_activity(),
        timeseries=[],
        galloway=galloway or make_galloway(is_galloway=False),
        mile_segments=mile_segments or [],
        lap_segments=lap_segments or [],
        bonk_events=bonk_events or [],
        cardiac_drift=cardiac_drift,
        sleep=sleep,
        hrv=hrv,
        body_battery=body_battery,
    )


# ─── build_debrief_prompt ─────────────────────────────────────────────────────

class TestBuildDebriefPrompt:
    def test_returns_string(self):
        report = make_run_report()
        result = build_debrief_prompt(report)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_header_contains_date(self):
        report = make_run_report(
            activity=make_activity(start_time_utc=datetime(2025, 1, 15, 7, 30, 0))
        )
        result = build_debrief_prompt(report)
        assert "january 15" in result.lower()

    def test_header_contains_distance(self):
        report = make_run_report(activity=make_activity(distance_meters=8046.72))
        result = build_debrief_prompt(report)
        assert "5.0 miles" in result

    def test_header_contains_duration(self):
        # 2520s = 42:00
        report = make_run_report(activity=make_activity(duration_seconds=2520.0))
        result = build_debrief_prompt(report)
        assert "42:00" in result

    def test_avg_hr_shown(self):
        report = make_run_report(activity=make_activity(avg_hr=148.0))
        result = build_debrief_prompt(report)
        assert "148 bpm" in result

    def test_galloway_section_when_detected(self):
        report = make_run_report(galloway=make_galloway(is_galloway=True))
        result = build_debrief_prompt(report)
        assert "Galloway" in result

    def test_galloway_section_absent_when_not_detected(self):
        report = make_run_report(galloway=make_galloway(is_galloway=False))
        result = build_debrief_prompt(report)
        assert "Galloway" not in result

    def test_mile_table_when_segments_provided(self):
        segs = [make_run_segment(label=i) for i in range(1, 4)]
        report = make_run_report(mile_segments=segs)
        result = build_debrief_prompt(report)
        assert "Mile-by-Mile" in result
        assert "| Mile |" in result

    def test_no_mile_table_when_no_segments(self):
        report = make_run_report(mile_segments=[])
        result = build_debrief_prompt(report)
        assert "Mile-by-Mile" not in result

    def test_bonk_section_when_detected(self):
        bonk = BonkEvent(
            elapsed_seconds_onset=1680,  # 28 min
            pre_bonk_pace_s_per_km=300.0,
            bonk_pace_s_per_km=380.0,
            pace_drop_pct=0.267,
            pre_bonk_hr=151.0,
            peak_hr=168.0,
            recovered=False,
        )
        report = make_run_report(bonk_events=[bonk])
        result = build_debrief_prompt(report)
        assert "Performance Collapse" in result
        assert "28:00" in result

    def test_no_bonk_section_shows_none_detected(self):
        report = make_run_report(bonk_events=[])
        result = build_debrief_prompt(report)
        assert "None detected" in result

    def test_cardiac_drift_section_when_detected(self):
        drift = CardiacDriftEvent(
            onset_elapsed_seconds=900,   # 15 min
            total_hr_rise_bpm=12.5,
            pace_at_onset_s_per_km=312.0,
        )
        report = make_run_report(cardiac_drift=drift)
        result = build_debrief_prompt(report)
        assert "Cardiac Drift" in result
        assert "12.5 bpm" in result

    def test_no_drift_shows_not_detected(self):
        report = make_run_report(cardiac_drift=None)
        result = build_debrief_prompt(report)
        assert "Not detected" in result

    def test_sleep_context_shown_when_present(self):
        sleep = SleepRecord(
            sleep_date=date(2025, 1, 14),
            duration_seconds=25200,      # 7h
            deep_sleep_seconds=5400,     # 1h30m
            sleep_score=75,
        )
        report = make_run_report(sleep=sleep)
        result = build_debrief_prompt(report)
        assert "Sleep" in result
        assert "7h" in result

    def test_no_sleep_section_when_absent(self):
        report = make_run_report(sleep=None)
        result = build_debrief_prompt(report)
        assert "Sleep" not in result

    def test_hrv_context_shown_when_present(self):
        hrv = HRVRecord(
            record_date=date(2025, 1, 14),
            weekly_avg_hrv=58.0,
            last_night_avg_hrv=52.0,
            status="BALANCED",
        )
        report = make_run_report(hrv=hrv)
        result = build_debrief_prompt(report)
        assert "HRV" in result
        assert "52" in result

    def test_reflection_appended_when_provided(self):
        report = make_run_report()
        result = build_debrief_prompt(report, reflection="Legs felt heavy from the start.")
        assert "Runner Reflection" in result
        assert "Legs felt heavy" in result

    def test_no_reflection_section_when_absent(self):
        report = make_run_report()
        result = build_debrief_prompt(report, reflection=None)
        assert "Runner Reflection" not in result

    def test_coaching_instruction_at_end(self):
        report = make_run_report()
        result = build_debrief_prompt(report)
        assert "debrief" in result.lower()


class TestBuildDebriefSystemPrompt:
    def test_returns_string(self):
        result = build_debrief_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mentions_coaching_voice(self):
        result = build_debrief_system_prompt()
        assert "coach" in result.lower()

    def test_mentions_data_grounded_analysis(self):
        result = build_debrief_system_prompt()
        assert "data" in result.lower()


# ─── build_trends_prompt ──────────────────────────────────────────────────────

class TestBuildTrendsPrompt:
    def test_empty_activities_returns_message(self):
        result = build_trends_prompt([])
        assert "No recent activities" in result

    def test_returns_string_with_activities(self):
        acts = [make_activity() for _ in range(3)]
        result = build_trends_prompt(acts)
        assert isinstance(result, str)

    def test_activity_count_in_header(self):
        acts = [make_activity() for _ in range(5)]
        result = build_trends_prompt(acts)
        assert "5" in result

    def test_total_distance_shown(self):
        # 3 runs × 8046.72m = 24140.16m ≈ 15.0 miles
        acts = [make_activity(distance_meters=8046.72) for _ in range(3)]
        result = build_trends_prompt(acts)
        assert "15.0 miles" in result

    def test_table_header_present(self):
        acts = [make_activity()]
        result = build_trends_prompt(acts)
        assert "| Date |" in result
        assert "| Miles |" in result

    def test_each_activity_has_row(self):
        acts = [
            make_activity(start_time_utc=datetime(2025, 1, i + 10, 7, 0)) for i in range(3)
        ]
        result = build_trends_prompt(acts)
        lines = result.splitlines()
        data_rows = [l for l in lines if l.startswith("| Jan")]
        assert len(data_rows) == 3

    def test_pace_formatted_in_table(self):
        acts = [make_activity(avg_pace_seconds_per_km=312.0)]  # 8:20/km
        result = build_trends_prompt(acts)
        # format_pace(312) = "8:20/km" or similar
        assert "/km" in result or "/mi" in result or "8:" in result

    def test_na_shown_for_missing_hr(self):
        acts = [make_activity(avg_hr=None)]
        result = build_trends_prompt(acts)
        assert "n/a" in result

    def test_coaching_instruction_at_end(self):
        acts = [make_activity()]
        result = build_trends_prompt(acts)
        assert "trend" in result.lower()


# ─── build_voice_query_prompt ─────────────────────────────────────────────────

class TestBuildVoiceQueryPrompt:
    def test_returns_string(self):
        result = build_voice_query_prompt("My legs felt heavy.")
        assert isinstance(result, str)

    def test_transcript_in_output_without_report(self):
        result = build_voice_query_prompt("My legs felt heavy.")
        assert "My legs felt heavy" in result

    def test_no_data_fallback_message_when_no_report(self):
        result = build_voice_query_prompt("Felt great!")
        assert "No run data" in result

    def test_with_report_includes_debrief(self):
        report = make_run_report()
        result = build_voice_query_prompt("Felt heavy", report=report)
        # Should include the debrief prompt content
        assert "miles" in result.lower()

    def test_with_report_includes_reflection(self):
        report = make_run_report()
        result = build_voice_query_prompt("Legs were dead.", report=report)
        # Reflection is passed through to build_debrief_prompt
        assert "Legs were dead" in result


# ─── build_whisper_prompt ─────────────────────────────────────────────────────

class TestBuildWhisperPrompt:
    def test_returns_string(self):
        result = build_whisper_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_running_vocabulary(self):
        result = build_whisper_prompt()
        running_terms = ["Galloway", "pace", "heart rate", "cadence"]
        assert any(term.lower() in result.lower() for term in running_terms)
