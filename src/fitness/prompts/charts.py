"""
Chart generation for run analysis.

Produces matplotlib figures as PNG bytes (for Telegram photo messages).
Each chart function returns (png_bytes, caption).

Overview chart design:
  - 2 tall panels stacked: pace over time (top), HR over time (bottom)
  - X-axis: elapsed time in minutes (what the runner feels, not distance)
  - Background shading by segment type:
      warmup/cooldown → dim teal
      active run      → teal
      walk/rest       → grey
      tiny drill laps → collapsed into a single "Drills" region
  - Segment labels along the top of the pace panel (name / distance / avg pace)
  - Per-segment dashed gold line at avg pace (no text label — header carries it)
  - Cross-rep solid gold line spanning all reps at their collective median
  - Elevation profile overlaid on pace panel (right Y-axis, dim gold fill)
  - Bonk events marked as vertical red dashed lines on the pace panel
  - HR zone threshold lines on the HR panel
"""
import io
import base64
from statistics import median
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import numpy as np

from fitness.analysis.run_report import RunReport
from fitness.analysis.segments import LapSegment
from fitness.analysis.timeseries import TimeseriesPoint
from fitness.analysis.pace import format_pace

# ─── Constants ────────────────────────────────────────────────────────────────

# Laps shorter than this are collapsed into a "Drills" shaded region
MIN_LAP_DISPLAY_M = 50.0

# Distance tolerance for grouping reps (fraction of lap distance)
REP_DISTANCE_TOLERANCE = 0.05   # 5% — 800m ± 40m counts as same rep

# Minimum rep count to draw a median reference line
MIN_REPS_FOR_REFERENCE = 2

# Pace above which the line is suppressed (walk/rest — not interesting on pace panel)
# Also used as the hard bottom of the Y-axis so the scale never opens past this.
MAX_DISPLAY_PACE_MIN_MI = 11.0   # 11:00/mi

# Colour cycle for per-rep median lines (distinct, works on dark background)
REP_COLORS = ["#ffd700", "#ff9f43", "#ff6b9d", "#a29bfe", "#55efc4", "#fdcb6e"]

# Zone colours matching Garmin/Strava conventions
ZONE_COLORS = {1: "#5b9bd5", 2: "#70ad47", 3: "#ffc000", 4: "#ed7d31", 5: "#c00000"}

# Segment shading colours (semi-transparent fills)
SHADE = {
    "run_segment":      ("#4ecdc4", 0.12),  # teal
    "warmup_segment":   ("#4ecdc4", 0.06),  # dim teal
    "cooldown_segment": ("#4ecdc4", 0.06),  # dim teal
    "walk_segment":     ("#888888", 0.15),  # grey
    "lap":              ("#888888", 0.08),
}

MAX_HR_DEFAULT = 185


# ─── Public API ───────────────────────────────────────────────────────────────

def make_run_overview_chart(report: RunReport) -> Tuple[bytes, str]:
    """
    Two-panel overview chart (pace over time, HR over time).
    Background shading shows workout structure; dashed lines show
    median rep pace for interval workouts.

    Returns (png_bytes, caption).
    """
    pts = report.timeseries
    lap_segs = report.lap_segments

    # Build time arrays (minutes) and metric arrays
    t_min_pace, pace_min_mi = _timeseries_pace(pts)
    t_min_hr, hr_vals = _timeseries_hr(pts)

    # Identify rep groups for reference lines
    rep_groups = _group_rep_laps(lap_segs)

    # Total duration in minutes (for x-axis limit)
    total_min = report.activity.duration_seconds / 60.0

    fig = plt.figure(figsize=(12, 9))
    fig.patch.set_facecolor("#1a1a2e")
    gs = gridspec.GridSpec(2, 1, figure=fig, hspace=0.08, height_ratios=[1, 1])

    ax_pace = fig.add_subplot(gs[0])
    ax_hr   = fig.add_subplot(gs[1], sharex=ax_pace)

    _style_ax(ax_pace)
    _style_ax(ax_hr)

    # ── Segment background shading ────────────────────────────────────────────
    _draw_segment_shading(ax_pace, ax_hr, lap_segs, total_min)

    # ── Segment labels along top of pace panel ────────────────────────────────
    _draw_segment_labels(ax_pace, lap_segs, total_min)

    # ── Pace line ─────────────────────────────────────────────────────────────
    if t_min_pace and pace_min_mi:
        pace_arr = np.array(pace_min_mi)
        smooth = _rolling_median(pace_arr, window=20)
        # Mask points slower than threshold — walk/rest segments drop off the
        # bottom of the chart rather than drawing a distracting spike.
        smooth_masked = np.where(smooth <= MAX_DISPLAY_PACE_MIN_MI, smooth, np.nan)
        ax_pace.plot(t_min_pace[:len(smooth_masked)], smooth_masked,
                     color="#4ecdc4", linewidth=1.8, label="Pace", zorder=3)
        ax_pace.invert_yaxis()
        ax_pace.set_ylabel("Pace (min/mi)", color="#aaaaaa", fontsize=9)
        ax_pace.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{int(v)}:{int((v % 1)*60):02d}")
        )
        # Clip Y-axis to active-segment pace range (eliminates walk/rest outliers).
        # Use the 5th–95th percentile of run-segment points for robust bounds,
        # then add a small margin so the line never touches the edge.
        active_paces = _active_segment_paces(pace_min_mi, t_min_pace, lap_segs)
        if active_paces:
            lo = float(np.percentile(active_paces, 5))
            hi = float(np.percentile(active_paces, 95))
        else:
            lo, hi = float(np.min(pace_arr)), float(np.max(pace_arr))
        margin = (hi - lo) * 0.15 + 0.25
        # Y-axis is inverted: faster (lower value) is at top → set_ylim(top=lo, bottom=hi)
        # Hard-cap the bottom at MAX_DISPLAY_PACE_MIN_MI so slow warmup/cooldown
        # points don't stretch the scale even if they sneak into the percentile.
        axis_bottom = min(hi + margin, MAX_DISPLAY_PACE_MIN_MI)
        ax_pace.set_ylim(bottom=axis_bottom, top=max(0, lo - margin))

    # ── Cross-rep median reference line (interval consistency) ────────────────
    if t_min_pace and pace_min_mi:
        _draw_rep_reference_lines(ax_pace, rep_groups, pts)

    # ── Elevation overlay on pace panel (right Y-axis) ────────────────────────
    _draw_elevation_overlay(ax_pace, pts, report.bonk_events)

    # ── HR line ───────────────────────────────────────────────────────────────
    if t_min_hr and hr_vals:
        ax_hr.plot(t_min_hr, hr_vals, color="#ff6b6b", linewidth=1.2,
                   alpha=0.85, zorder=3)
        _draw_hr_zone_lines(ax_hr, max_hr=MAX_HR_DEFAULT)
        ax_hr.set_ylabel("Heart Rate (bpm)", color="#aaaaaa", fontsize=9)
        ax_hr.set_ylim(bottom=max(0, min(hr_vals) - 10))

    # ── X-axis ────────────────────────────────────────────────────────────────
    ax_hr.set_xlabel("Time (min)", color="#aaaaaa", fontsize=9)
    ax_pace.tick_params(labelbottom=False)   # hide x-ticks on top panel

    # ── Title ─────────────────────────────────────────────────────────────────
    act = report.activity
    dist_mi = act.distance_meters / 1609.344
    dur_min = int(act.duration_seconds // 60)
    dur_sec = int(act.duration_seconds % 60)
    caption = (
        f"{act.name}  ·  {act.start_time_utc.strftime('%b %d %Y')}  ·  "
        f"{dist_mi:.1f} mi  ·  {dur_min}:{dur_sec:02d}"
    )
    fig.suptitle(caption, color="white", fontsize=11, fontweight="bold", y=0.98)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read(), caption


def make_elevation_chart(report: RunReport) -> Optional[Tuple[bytes, str]]:
    """Elevation profile with bonk markers. Returns None if no elevation data."""
    pts = [p for p in report.timeseries
           if p.elevation_meters is not None and p.distance_meters is not None]
    if len(pts) < 10:
        return None

    dist_mi = [p.distance_meters / 1609.344 for p in pts]
    elev    = [p.elevation_meters for p in pts]

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a2e")
    _style_ax(ax)

    ax.fill_between(dist_mi, elev, min(elev) - 5, alpha=0.4, color="#8b6914")
    ax.plot(dist_mi, elev, color="#ffd700", linewidth=1.5)
    ax.set_ylabel("Elevation (m)", color="#ffd700", fontsize=9)
    ax.set_xlabel("Distance (mi)", color="#aaaaaa", fontsize=8)

    for bonk in report.bonk_events:
        closest = min(pts, key=lambda p: abs(p.elapsed_seconds - bonk.elapsed_seconds_onset))
        x = closest.distance_meters / 1609.344
        ax.axvline(x, color="#ff4444", linewidth=2, linestyle="--", alpha=0.8)
        ax.text(x, max(elev) * 0.95, "⚡bonk", color="#ff4444",
                fontsize=8, ha="center")

    caption = f"Elevation Profile — {report.activity.name}"
    fig.suptitle(caption, color="white", fontsize=11, y=1.02)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read(), caption


# ─── Rep grouping ─────────────────────────────────────────────────────────────

def _group_rep_laps(lap_segs: List[LapSegment]) -> List[List[LapSegment]]:
    """
    Find groups of active laps with matching distances (interval reps).

    Only considers run_segment laps above MIN_LAP_DISPLAY_M.
    Groups require >= MIN_REPS_FOR_REFERENCE members.

    Returns list of groups, each group a list of LapSegment.
    """
    active = [
        s for s in lap_segs
        if s.split_type == "run_segment" and s.distance_meters >= MIN_LAP_DISPLAY_M
    ]
    if not active:
        return []

    # Cluster by distance within REP_DISTANCE_TOLERANCE
    groups: List[List[LapSegment]] = []
    for seg in active:
        placed = False
        for group in groups:
            ref_dist = group[0].distance_meters
            if abs(seg.distance_meters - ref_dist) / ref_dist <= REP_DISTANCE_TOLERANCE:
                group.append(seg)
                placed = True
                break
        if not placed:
            groups.append([seg])

    return [g for g in groups if len(g) >= MIN_REPS_FOR_REFERENCE]


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _pace_to_min_mi(pace_s_per_km: float) -> float:
    return pace_s_per_km * 1.60934 / 60.0


def _active_segment_paces(
    pace_min_mi: List[float],
    t_min: List[float],
    lap_segs: List[LapSegment],
) -> List[float]:
    """Return pace values from run_segment laps above MIN_LAP_DISPLAY_M.

    Excludes warmup, cooldown, walk, and tiny laps — these often contain very
    slow paces that blow out the Y-axis. Falls back to all points if no
    qualifying run segments exist.
    """
    run_windows = [
        (seg.start_elapsed_s / 60.0, seg.end_elapsed_s / 60.0)
        for seg in lap_segs
        if seg.split_type == "run_segment"
        and seg.distance_meters >= MIN_LAP_DISPLAY_M
    ]
    if not run_windows:
        return pace_min_mi  # no qualifying segments — use everything
    return [
        p for p, t in zip(pace_min_mi, t_min)
        if any(x0 <= t < x1 for x0, x1 in run_windows)
    ]


def _timeseries_pace(pts: List[TimeseriesPoint]):
    t, p = [], []
    for pt in pts:
        if pt.pace_seconds_per_km is not None and pt.pace_seconds_per_km > 0:
            t.append(pt.elapsed_seconds / 60.0)
            p.append(_pace_to_min_mi(pt.pace_seconds_per_km))
    return t, p


def _timeseries_hr(pts: List[TimeseriesPoint]):
    t, h = [], []
    for pt in pts:
        if pt.heart_rate is not None:
            t.append(pt.elapsed_seconds / 60.0)
            h.append(pt.heart_rate)
    return t, h


def _draw_segment_shading(ax_pace, ax_hr, lap_segs: List[LapSegment],
                          total_min: float) -> None:
    """Fill background of both panels by segment type. Tiny laps → 'Drills'."""
    drills_start: Optional[float] = None
    drills_end: Optional[float] = None

    for seg in lap_segs:
        x0 = seg.start_elapsed_s / 60.0
        x1 = seg.end_elapsed_s / 60.0

        if seg.distance_meters < MIN_LAP_DISPLAY_M:
            # Accumulate tiny laps into one drills block
            if drills_start is None:
                drills_start = x0
            drills_end = x1
            continue

        # Flush accumulated drills block before this real lap
        if drills_start is not None:
            _shade_region(ax_pace, ax_hr, drills_start, drills_end,
                          "#bb88ff", 0.10, "Drills")
            drills_start = drills_end = None

        color, alpha = SHADE.get(seg.split_type, ("#888888", 0.10))
        _shade_region(ax_pace, ax_hr, x0, x1, color, alpha)

    # Flush any trailing drills
    if drills_start is not None:
        _shade_region(ax_pace, ax_hr, drills_start, drills_end,
                      "#bb88ff", 0.10, "Drills")


def _shade_region(ax_pace, ax_hr, x0: float, x1: float,
                  color: str, alpha: float, label: Optional[str] = None) -> None:
    for ax in (ax_pace, ax_hr):
        ax.axvspan(x0, x1, color=color, alpha=alpha, zorder=1, linewidth=0)


def _draw_segment_labels(ax, lap_segs: List[LapSegment], total_min: float) -> None:
    """Draw segment name at the top of the pace panel.

    Run/warmup/cooldown (≥ 0.1 mi): name + distance + avg pace, teal text.
    Walk/recovery: name only (rotated, dim grey) — always shown, no crowding
      suppression, because these are narrow and the name is the key signal.
    Crowding suppression applies only to run-type segments.
    """
    trans = ax.get_xaxis_transform()
    prev_run_label_end_min = -999.0

    for seg in lap_segs:
        if seg.distance_meters < MIN_LAP_DISPLAY_M:
            continue

        seg_width_min = (seg.end_elapsed_s - seg.start_elapsed_s) / 60.0
        x_mid = seg.start_elapsed_s / 60.0 + seg_width_min / 2.0
        dist_mi = seg.distance_meters / 1609.344

        if seg.split_type == "walk_segment":
            # Walk labels: short name only, rotated, dimmer — always rendered
            ax.text(x_mid, 0.97, seg.label, transform=trans,
                    color="#888888", fontsize=5, ha="center", va="top",
                    rotation=90, clip_on=True)
        else:
            # Run-type labels: suppress if too close to previous run label
            min_gap = max(2.5, seg_width_min * 0.6)
            if x_mid - prev_run_label_end_min < min_gap:
                continue

            show_pace = dist_mi >= 0.1 and seg.avg_pace_s_per_km > 0
            if show_pace:
                lbl = f"{seg.label}\n{dist_mi:.2f}mi\n{format_pace(seg.avg_pace_s_per_km)}"
            elif dist_mi >= 0.1:
                lbl = f"{seg.label}\n{dist_mi:.2f}mi"
            else:
                lbl = seg.label

            ax.text(x_mid, 0.97, lbl, transform=trans,
                    color="#cccccc", fontsize=6, ha="center", va="top",
                    clip_on=True)
            prev_run_label_end_min = x_mid + seg_width_min / 2.0


def _draw_segment_median_lines(ax, lap_segs: List[LapSegment],
                                pts: List[TimeseriesPoint]) -> None:
    """
    Per-rep avg-pace lines, color-coded by rep index so reps are visually
    distinguishable. Each line gets a small inline label at its left edge
    with a dark background box so it doesn't clash with the pace line.
    Only run_segments above MIN_LAP_DISPLAY_M are drawn.
    """
    run_segs = [s for s in lap_segs
                if s.split_type == "run_segment"
                and s.distance_meters >= MIN_LAP_DISPLAY_M
                and s.avg_pace_s_per_km > 0]

    for i, seg in enumerate(run_segs):
        color = REP_COLORS[i % len(REP_COLORS)]
        x0 = seg.start_elapsed_s / 60.0
        x1 = seg.end_elapsed_s / 60.0
        med = _pace_to_min_mi(seg.avg_pace_s_per_km)
        ax.hlines(med, x0, x1,
                  colors=color, linewidths=1.0,
                  linestyles="--", alpha=0.65, zorder=4)
        # Inline label at left edge of segment, with bbox so it's readable
        ax.text(x0 + 0.1, med, format_pace(seg.avg_pace_s_per_km),
                color=color, fontsize=5, va="center", ha="left",
                zorder=5, clip_on=True,
                bbox=dict(boxstyle="round,pad=0.15", fc="#1a1a2e",
                          ec="none", alpha=0.7))


def _draw_rep_reference_lines(ax, rep_groups: List[List[LapSegment]],
                               pts: List[TimeseriesPoint]) -> None:
    """
    Cross-rep consistency line per rep group. Dashed, behind the pace line.
    Color-coded per group. Label anchored to the right margin (outside data
    area) so it never overlaps the pace trace, with a hairline connector from
    the label back to the line end.
    """
    for gi, group in enumerate(rep_groups):
        med_pace_s_km = median(seg.avg_pace_s_per_km for seg in group
                               if seg.avg_pace_s_per_km > 0)
        if med_pace_s_km <= 0:
            continue
        med_pace_min_mi = _pace_to_min_mi(med_pace_s_km)
        color = REP_COLORS[gi % len(REP_COLORS)]

        x0 = group[0].start_elapsed_s / 60.0
        x1 = group[-1].end_elapsed_s / 60.0

        # Dashed line behind the pace trace
        ax.hlines(med_pace_min_mi, x0, x1,
                  colors=color, linewidths=1.0,
                  linestyles=(0, (4, 3)),   # dash-gap pattern
                  alpha=0.50, zorder=2)

        # Label floats ON the line, at a staggered x position so labels
        # for different groups at similar paces don't land on each other.
        # Cycle through 4 x-positions spread across the span (25/40/55/70%).
        x_fracs = [0.25, 0.45, 0.62, 0.78]
        label_x = x0 + (x1 - x0) * x_fracs[gi % len(x_fracs)]
        ax.text(label_x, med_pace_min_mi, format_pace(med_pace_s_km),
                color=color, fontsize=5.5, fontweight="bold",
                va="bottom", ha="center", alpha=0.80,
                zorder=6, clip_on=True,
                bbox=dict(boxstyle="round,pad=0.15", fc="#1a1a2e",
                          ec="none", alpha=0.55))


def _draw_elevation_overlay(ax_pace, pts: List[TimeseriesPoint],
                             bonk_events: list) -> None:
    """
    Overlay elevation as a dim filled area on a right Y-axis of the pace panel.
    Bonk onset times are marked with vertical red dashed lines + a small label.
    Skipped silently if fewer than 10 elevation points are available.
    """
    elev_pts = [(p.elapsed_seconds / 60.0, p.elevation_meters)
                for p in pts if p.elevation_meters is not None]
    if len(elev_pts) < 10:
        return

    t_elev, elev = zip(*elev_pts)

    ax_elev = ax_pace.twinx()
    ax_elev.set_zorder(ax_pace.get_zorder() - 1)  # behind pace line
    ax_pace.set_frame_on(False)                     # let twin show through

    elev_min = min(elev)
    elev_max = max(elev)
    headroom = (elev_max - elev_min) * 0.1 + 1.0
    # Push elevation to the bottom third of the pace panel so it doesn't
    # obscure the pace line — set top well above data range
    ax_elev.set_ylim(elev_min - headroom, elev_max + (elev_max - elev_min) * 4)

    ax_elev.fill_between(t_elev, elev, elev_min - headroom,
                         color="#8b6914", alpha=0.18, zorder=1)
    ax_elev.plot(t_elev, elev, color="#c8a040", linewidth=0.8,
                 alpha=0.45, zorder=2)
    ax_elev.set_ylabel("Elev (m)", color="#c8a040", fontsize=7, alpha=0.7)
    ax_elev.tick_params(colors="#c8a040", labelsize=6, axis="y")
    ax_elev.spines["right"].set_color("#555544")
    ax_elev.spines["top"].set_visible(False)
    ax_elev.spines["left"].set_visible(False)
    ax_elev.spines["bottom"].set_visible(False)

    # Bonk markers
    for bonk in bonk_events:
        t_bonk = bonk.elapsed_seconds_onset / 60.0
        ax_pace.axvline(t_bonk, color="#ff4444", linewidth=1.5,
                        linestyle="--", alpha=0.8, zorder=5)
        ax_pace.text(t_bonk + 0.3, 0.03, "bonk",
                     transform=ax_pace.get_xaxis_transform(),
                     color="#ff4444", fontsize=6, va="bottom", alpha=0.9)


def _draw_hr_zone_lines(ax, max_hr: int = MAX_HR_DEFAULT) -> None:
    thresholds = [0.60, 0.70, 0.80, 0.90]
    labels = ["Z1/Z2", "Z2/Z3", "Z3/Z4", "Z4/Z5"]
    for thresh, lbl in zip(thresholds, labels):
        ax.axhline(max_hr * thresh, color="#555577", linewidth=0.6,
                   linestyle="--", alpha=0.7, zorder=2)


def _style_ax(ax) -> None:
    ax.set_facecolor("#2d2d4e")
    ax.tick_params(colors="white", labelsize=8)
    ax.spines["bottom"].set_color("#555577")
    ax.spines["left"].set_color("#555577")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _rolling_median(arr: np.ndarray, window: int) -> np.ndarray:
    result = np.empty(len(arr))
    half = window // 2
    for i in range(len(arr)):
        lo = max(0, i - half)
        hi = min(len(arr), i + half + 1)
        result[i] = np.median(arr[lo:hi])
    return result


def png_to_base64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("utf-8")
