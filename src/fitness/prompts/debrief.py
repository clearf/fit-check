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

    # ── Workout Intent (structured plan, when available) ──────────────────────
    wc = getattr(report, "workout_classification", None)
    if wc is not None:
        _WORKOUT_TYPE_LABELS = {
            "speed": "Speed/Interval",
            "hill": "Hill Repeats",
            "race_pace": "Tempo/Race Pace",
            "long_run": "Long Run",
            "easy": "Easy/Recovery",
            "drills": "Drills/Form Work",
            "unknown": "Structured Workout",
        }
        type_label = _WORKOUT_TYPE_LABELS.get(wc.workout_type, "Structured Workout")
        name_str = f" — {wc.workout_name}" if wc.workout_name else ""
        lines.append(f"## Workout Intent: {type_label}{name_str}")
        if wc.workout_description:
            lines.append(f"_{wc.workout_description}_")
        if wc.structured_summary:
            lines.append("")
            lines.append("**Planned structure:**")
            for step_line in wc.structured_summary.split("\n"):
                lines.append(f"  {step_line}")
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

    # ── Lap segments with per-segment timeseries ──────────────────────────────
    seg_section = _format_lap_segments(report)
    if seg_section:
        lines.append(seg_section)
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
        "_Please give a coaching debrief. Reference specific segment labels "
        "(e.g., 'Run 3', 'Walk 2') and elapsed times when citing the data. "
        "Use the per-segment timeseries to comment on intra-segment dynamics "
        "(e.g., HR rising within a run interval, pace fading mid-rep, HR "
        "recovery during walk breaks). Ask one follow-up question if relevant "
        "context is missing._"
    )

    return "\n".join(lines)


def build_debrief_system_prompt() -> str:
    """System prompt instructing Claude how to behave as a running coach."""
    return (
        "You are a knowledgeable, encouraging running coach providing a post-run debrief. "
        "Your analysis is grounded in the objective data provided — pace, HR, elevation, "
        "and detected events. Be specific: cite specific segment labels and elapsed times "
        "when referencing the data. Use a coaching voice that is curious and supportive, "
        "never judgmental. "
        "When the data shows something notable (bonk, cardiac drift, great negative split), "
        "explain the physiology briefly in plain language. "
        "If the runner has shared a subjective reflection, integrate both the data evidence "
        "and their experience — explain whether the data corroborates what they felt. "
        "\n\n"
        "When per-segment timeseries data is provided, analyze the shape of each interval — "
        "not just the average. For run segments: is pace holding steady or fading mid-rep? "
        "Is HR rising within the rep (indicating accumulated fatigue)? For walk segments: "
        "does HR drop meaningfully before the next run begins (adequate recovery)? "
        "Trend across run intervals: is each successive run interval slower or more costly "
        "(higher HR for same pace)? Use this to distinguish acute events (a single bad rep) "
        "from progressive fatigue. "
        "\n\n"
        "When a Workout Intent section is provided, evaluate actual performance against the "
        "structured plan. For speed/interval workouts, check whether reps hit target pace "
        "and whether recovery was adequate. For tempo/race-pace workouts, evaluate whether "
        "sustained effort matched the intended zone. For drills (cadence, acceleration-glider), "
        "comment on execution quality. For hill repeats, note effort consistency. "
        "Always frame the debrief around what the workout was trying to achieve physiologically "
        "and how well the execution served that goal. "
        "\n\n"
        "Keep the debrief to 3-5 paragraphs unless asked for more detail. "
        "End with exactly ONE follow-up question if there's missing context that would "
        "meaningfully change your analysis (e.g., pre-run nutrition, sleep quality if not "
        "provided, training load). If all context is present, skip the question."
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _find_bonk_for_segment(seg, bonk_events):
    """Return the first BonkEvent whose onset falls within seg's time window, or None."""
    for bonk in bonk_events:
        if seg.start_elapsed_s <= bonk.elapsed_seconds_onset <= seg.end_elapsed_s:
            return bonk
    return None


def _format_lap_segments(report: RunReport) -> str:
    """
    Build a compact per-segment timeseries block for the debrief prompt.

    Each lap segment gets a one-line header plus a CSV of timeseries data
    sampled every 5 seconds, giving Claude visibility into intra-segment
    pace and HR dynamics rather than just averages.

    Returns an empty string if there are no lap segments.
    """
    if not report.lap_segments:
        return ""

    heading = (
        "## Lap Segments (Galloway)"
        if report.galloway.is_galloway
        else "## Lap Segments"
    )
    section_lines = [heading]

    for seg in report.lap_segments:
        # ── Segment header ────────────────────────────────────────────────
        start_mm = seg.start_elapsed_s // 60
        start_ss = seg.start_elapsed_s % 60
        end_mm = seg.end_elapsed_s // 60
        end_ss = seg.end_elapsed_s % 60
        time_range = f"@{start_mm}:{start_ss:02d}–{end_mm}:{end_ss:02d}"

        parts = [f"### {seg.label} ({time_range}, {seg.distance_miles:.2f}mi"]
        if seg.avg_pace_s_per_km and seg.avg_pace_s_per_km > 0:
            parts.append(f", avg {format_pace(seg.avg_pace_s_per_km)}")
        if seg.avg_hr and seg.avg_hr > 0:
            parts.append(f", avg HR {int(seg.avg_hr)} bpm")
        parts.append(")")

        is_warmup = seg.label == "Warmup" or seg.split_type == "warmup_segment"
        is_cooldown = seg.label == "Cooldown" or seg.split_type == "cooldown_segment"
        if is_warmup:
            parts.append("  (warmup)")
        elif is_cooldown:
            parts.append("  (cooldown)")

        # Bonk annotation
        bonk = _find_bonk_for_segment(seg, report.bonk_events)
        if bonk:
            recovery_str = "recovered" if bonk.recovered else "did not recover"
            parts.append(
                f"  \u26a0 BONK ONSET: {format_pace(bonk.pre_bonk_pace_s_per_km)}"
                f" \u2192 {format_pace(bonk.bonk_pace_s_per_km)}, "
                f"HR {bonk.pre_bonk_hr:.0f}\u2192{bonk.peak_hr:.0f} bpm, "
                f"{recovery_str}"
            )

        section_lines.append("".join(parts))

        # ── Per-segment timeseries CSV ────────────────────────────────────
        seg_points = [
            p for p in report.timeseries
            if seg.start_elapsed_s <= p.elapsed_seconds <= seg.end_elapsed_s
            and p.elapsed_seconds % 5 == 0
        ]

        if len(seg_points) >= 2:
            section_lines.append("elapsed_s,hr,pace_min_per_mi,elev_m")
            for p in seg_points:
                hr_str = str(p.heart_rate) if p.heart_rate is not None else ""
                if p.pace_seconds_per_km is not None:
                    pace_s_mi = p.pace_seconds_per_km * 1.60934
                    pace_str = f"{int(pace_s_mi) // 60}:{int(pace_s_mi) % 60:02d}"
                else:
                    pace_str = ""
                elev_str = (
                    f"{p.elevation_meters:.1f}"
                    if p.elevation_meters is not None
                    else ""
                )
                section_lines.append(
                    f"{p.elapsed_seconds},{hr_str},{pace_str},{elev_str}"
                )

        section_lines.append("")

    return "\n".join(section_lines)
