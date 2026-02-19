"""Trends prompt builder — 30-day narrative summary."""
from datetime import datetime
from typing import List

from fitness.analysis.pace import format_pace
from fitness.models.activity import Activity


def build_trends_prompt(activities: List[Activity]) -> str:
    """
    Build a prompt summarising recent training load and trends.

    Args:
        activities: List of Activity rows, most recent first.

    Returns:
        Formatted markdown for Claude.
    """
    if not activities:
        return "No recent activities found in the database."

    lines = [f"## Last {len(activities)} Runs — Training Trend Analysis\n"]

    total_dist = sum(a.distance_meters for a in activities) / 1609.344
    total_time_h = sum(a.duration_seconds for a in activities) / 3600
    avg_hr_vals = [a.avg_hr for a in activities if a.avg_hr]
    avg_hr_mean = sum(avg_hr_vals) / len(avg_hr_vals) if avg_hr_vals else None

    lines.append(
        f"Total: {total_dist:.1f} miles over {total_time_h:.1f} hours "
        f"| Avg HR: {int(avg_hr_mean)} bpm" if avg_hr_mean else
        f"Total: {total_dist:.1f} miles over {total_time_h:.1f} hours"
    )
    lines.append("")

    lines.append("| Date | Miles | Pace | Avg HR | Ascent |")
    lines.append("|------|-------|------|--------|--------|")
    for act in activities:
        dist_mi = act.distance_meters / 1609.344
        pace_str = format_pace(act.avg_pace_seconds_per_km) if act.avg_pace_seconds_per_km else "n/a"
        hr_str = f"{int(act.avg_hr)}" if act.avg_hr else "n/a"
        asc_str = f"+{int(act.total_ascent_meters)}ft" if act.total_ascent_meters else "n/a"
        lines.append(
            f"| {act.start_time_utc.strftime('%b %d')} "
            f"| {dist_mi:.1f} "
            f"| {pace_str} "
            f"| {hr_str} "
            f"| {asc_str} |"
        )

    lines.append("")
    lines.append(
        "_Summarise training load, pace trends, HR trends, and any patterns "
        "worth noting (improving fitness, overtraining signals, consistency). "
        "Be specific and encouraging._"
    )

    return "\n".join(lines)
