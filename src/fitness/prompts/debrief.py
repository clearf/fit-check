"""
Debrief prompt builder.

Renders a RunReport into structured markdown that Claude can interpret.
Claude receives data, not charts — charts go to Telegram separately.
The prompt is rich enough that Claude can cite specific mile markers,
times, HR values, and flag anomalies.
"""
from typing import Optional

from fitness.analysis.pace import format_pace
from fitness.analysis.run_report import RunReport


def build_debrief_prompt(
    report: RunReport,
    reflection: Optional[str] = None,
) -> str:
    """
    Build the user-turn prompt for Claude's run debrief.

    Args:
        report: Assembled RunReport from build_run_report().
        reflection: Optional voice/text reflection from the runner
                    (already transcribed if from voice).

    Returns:
        Formatted markdown string to send as the user message to Claude.
    """
    act = report.activity
    dist_mi = act.distance_meters / 1609.344
    duration_min = int(act.duration_seconds // 60)
    duration_sec = int(act.duration_seconds % 60)

    lines = []

    # ── Header ─────────────────────────────────────────────────────────────────
    lines.append(
        f"## Run: {act.start_time_utc.strftime('%B %d at %-I:%M%p').lower()} "
        f"— {dist_mi:.1f} miles in {duration_min}:{duration_sec:02d}"
    )

    summary_parts = [
        f"Avg Pace: {format_pace(act.avg_pace_seconds_per_km or 0)}" if act.avg_pace_seconds_per_km else None,
        f"Avg HR: {int(act.avg_hr)} bpm" if act.avg_hr else None,
        f"Max HR: {int(act.max_hr)} bpm" if act.max_hr else None,
        f"Elevation: +{int(act.total_ascent_meters)}ft" if act.total_ascent_meters else None,
    ]
    lines.append("  |  ".join(p for p in summary_parts if p))
    lines.append("")

    # ── Galloway summary ───────────────────────────────────────────────────────
    g = report.galloway
    if g.is_galloway:
        run_pace_str = format_pace(g.avg_run_pace_s_per_km) if g.avg_run_pace_s_per_km else "n/a"
        walk_pace_str = format_pace(g.avg_walk_pace_s_per_km) if g.avg_walk_pace_s_per_km else "n/a"
        lines.append("## Galloway Structure Detected")
        lines.append(
            f"{g.run_segment_count} run intervals / {g.walk_segment_count} walk breaks  |  "
            f"Avg run pace: {run_pace_str}  |  Avg walk pace: {walk_pace_str}  |  "
            f"Avg run HR: {int(g.avg_run_hr or 0)} bpm  |  Avg walk HR: {int(g.avg_walk_hr or 0)} bpm"
        )
        lines.append("")

    # ── Mile-by-mile table ─────────────────────────────────────────────────────
    if report.mile_segments:
        lines.append("## Mile-by-Mile")
        lines.append(
            "| Mile | Pace    | Avg HR | Elevation | GAP     | Notes |"
        )
        lines.append(
            "|------|---------|--------|-----------|---------|-------|"
        )
        for seg in report.mile_segments:
            elev_str = (
                f"{seg.grade_pct * 52.8:+.0f}ft"
                if abs(seg.grade_pct) >= 0.5
                else "flat"
            )
            notes = _segment_notes(seg, report)
            lines.append(
                f"| {seg.label} | {format_pace(seg.avg_pace_s_per_km)} "
                f"| {int(seg.avg_hr)} "
                f"| {elev_str} "
                f"| {format_pace(seg.gap_s_per_km)} "
                f"| {notes} |"
            )
        lines.append("")

    # ── Bonk events ────────────────────────────────────────────────────────────
    if report.bonk_events:
        lines.append("## Performance Collapse Detected")
        for bonk in report.bonk_events:
            onset_min = bonk.elapsed_seconds_onset // 60
            onset_sec = bonk.elapsed_seconds_onset % 60
            recovery_str = "recovered" if bonk.recovered else "did not recover"
            lines.append(
                f"At {onset_min}:{onset_sec:02d}: pace dropped "
                f"{format_pace(bonk.pre_bonk_pace_s_per_km)} to "
                f"{format_pace(bonk.bonk_pace_s_per_km)} "
                f"({bonk.pace_drop_pct * 100:.0f}% slower). "
                f"HR: {bonk.pre_bonk_hr:.0f} to {bonk.peak_hr:.0f} bpm. "
                f"Runner {recovery_str}."
            )
        lines.append("")
    else:
        lines.append("## Performance Collapse\nNone detected.\n")

    # ── Cardiac drift ──────────────────────────────────────────────────────────
    if report.cardiac_drift:
        drift = report.cardiac_drift
        onset_min = drift.onset_elapsed_seconds // 60
        lines.append("## Cardiac Drift")
        lines.append(
            f"Detected from {onset_min} min onward. "
            f"HR rose {drift.total_hr_rise_bpm:.1f} bpm over steady-pace segments "
            f"(pace at onset: {format_pace(drift.pace_at_onset_s_per_km)})."
        )
    else:
        lines.append("## Cardiac Drift\nNot detected.\n")
    lines.append("")

    # ── Wellness context ───────────────────────────────────────────────────────
    wellness_lines = []
    if report.sleep:
        sl = report.sleep
        hours = (sl.duration_seconds or 0) // 3600
        mins = ((sl.duration_seconds or 0) % 3600) // 60
        deep_h = (sl.deep_sleep_seconds or 0) // 3600
        deep_m = ((sl.deep_sleep_seconds or 0) % 3600) // 60
        score_str = f" | Score: {sl.sleep_score}" if sl.sleep_score else ""
        wellness_lines.append(
            f"Sleep night before: {hours}h {mins}min | Deep: {deep_h}h {deep_m}min{score_str}"
        )
    if report.hrv:
        h = report.hrv
        trend = ""
        if h.last_night_avg_hrv and h.weekly_avg_hrv:
            diff = h.last_night_avg_hrv - h.weekly_avg_hrv
            trend = f" ({'up' if diff >= 0 else 'down'} {abs(diff):.0f} vs 7-day avg {h.weekly_avg_hrv:.0f}ms)"
        wellness_lines.append(
            f"HRV: {h.last_night_avg_hrv:.0f}ms{trend} | Status: {h.status or 'n/a'}"
        )
    if report.body_battery:
        bb = report.body_battery
        wellness_lines.append(
            f"Body Battery at start: {bb.charged_value}/100"
        )

    if wellness_lines:
        lines.append("## Context")
        lines.extend(wellness_lines)
        lines.append("")

    # ── Runner reflection (if provided) ───────────────────────────────────────
    if reflection:
        lines.append("## Runner Reflection")
        lines.append(f'"{reflection}"')
        lines.append("")

    lines.append(
        "_Please give a coaching debrief. Cite specific mile markers and "
        "times. Ask one follow-up question if relevant context is missing._"
    )

    return "\n".join(lines)


def build_debrief_system_prompt() -> str:
    """System prompt instructing Claude how to behave as a running coach."""
    return (
        "You are a knowledgeable, encouraging running coach providing a post-run debrief. "
        "Your analysis is grounded in the objective data provided — pace, HR, elevation, "
        "and detected events. Be specific: cite exact mile markers, elapsed times, and "
        "bpm values. Use a coaching voice that is curious and supportive, never judgmental. "
        "When the data shows something notable (bonk, cardiac drift, great negative split), "
        "explain the physiology briefly in plain language. "
        "If the runner has shared a subjective reflection, integrate both the data evidence "
        "and their experience — explain whether the data corroborates what they felt. "
        "Keep the debrief to 3-5 paragraphs unless asked for more detail. "
        "End with exactly ONE follow-up question if there's missing context that would "
        "meaningfully change your analysis (e.g., pre-run nutrition, sleep quality if not "
        "provided, training load). If all context is present, skip the question."
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _segment_notes(seg, report: RunReport) -> str:
    """Generate brief notes for a mile segment table cell."""
    notes = []

    for bonk in report.bonk_events:
        if seg.start_elapsed_s <= bonk.elapsed_seconds_onset <= seg.end_elapsed_s:
            notes.append("bonk onset")

    if seg.grade_pct >= 3.0:
        notes.append("climb")
    elif seg.grade_pct <= -3.0:
        notes.append("descent")

    gap_diff = seg.avg_pace_s_per_km - seg.gap_s_per_km
    if gap_diff > 15:
        notes.append("grade-adjusted faster")
    elif gap_diff < -15:
        notes.append("grade-adjusted slower")

    return ", ".join(notes) if notes else ""
