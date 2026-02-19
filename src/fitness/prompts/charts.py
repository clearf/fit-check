"""
Chart generation for run analysis.

Produces matplotlib figures as PNG bytes (for Telegram photo messages)
or base64 strings (for embedding in text).

Each chart function returns (png_bytes, caption) so the bot layer can
send them directly with send_photo().
"""
import io
import base64
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

from fitness.analysis.run_report import RunReport
from fitness.analysis.segments import RunSegment
from fitness.analysis.timeseries import TimeseriesPoint
from fitness.analysis.pace import format_pace

# Zone colours matching typical Garmin/Strava conventions
ZONE_COLORS = {1: "#5b9bd5", 2: "#70ad47", 3: "#ffc000", 4: "#ed7d31", 5: "#c00000"}


def _pace_to_display(pace_s_per_km: float, unit: str = "mi") -> float:
    """Convert s/km pace to minutes/mile (or /km) float for axis labels."""
    if unit == "mi":
        return pace_s_per_km * 1.60934 / 60.0
    return pace_s_per_km / 60.0


def make_run_overview_chart(report: RunReport) -> Tuple[bytes, str]:
    """
    Four-panel overview chart:
      Top-left:  Pace over distance (with GAP overlay)
      Top-right: HR over distance (with zone bands)
      Bottom-left: Per-mile pace bar chart
      Bottom-right: Per-mile HR zone distribution stacked bar
    Returns (png_bytes, caption).
    """
    pts = report.timeseries
    segs = report.mile_segments

    # Build distance-indexed arrays from timeseries
    dist_km = [p.distance_meters / 1000.0 for p in pts if p.distance_meters is not None]
    pace_min_mi = [
        _pace_to_display(p.pace_seconds_per_km)
        for p in pts
        if p.distance_meters is not None and p.pace_seconds_per_km is not None
    ]
    hr_vals = [
        p.heart_rate for p in pts
        if p.distance_meters is not None and p.heart_rate is not None
    ]
    dist_km_hr = [
        p.distance_meters / 1000.0 for p in pts
        if p.distance_meters is not None and p.heart_rate is not None
    ]

    mile_labels = [s.label.replace("Mile ", "M") for s in segs]
    seg_pace = [_pace_to_display(s.avg_pace_s_per_km) for s in segs]
    seg_gap = [_pace_to_display(s.gap_s_per_km) for s in segs]
    seg_hr = [s.avg_hr for s in segs]

    fig = plt.figure(figsize=(12, 8))
    fig.patch.set_facecolor("#1a1a2e")
    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

    ax_pace = fig.add_subplot(gs[0, 0])
    ax_hr = fig.add_subplot(gs[0, 1])
    ax_seg_pace = fig.add_subplot(gs[1, 0])
    ax_zone = fig.add_subplot(gs[1, 1])

    _style_ax(ax_pace)
    _style_ax(ax_hr)
    _style_ax(ax_seg_pace)
    _style_ax(ax_zone)

    # ── Pace over distance ────────────────────────────────────────────────────
    if dist_km and pace_min_mi:
        # Smooth with rolling median to reduce GPS noise
        pace_arr = np.array(pace_min_mi)
        smooth_pace = _rolling_median(pace_arr, window=12)
        ax_pace.plot(dist_km[:len(smooth_pace)], smooth_pace,
                     color="#4ecdc4", linewidth=1.5, label="Pace")
        # GAP overlay per segment
        for i, seg in enumerate(segs):
            seg_dist_km = (i + 0.5) * 1.60934
            ax_pace.scatter([seg_dist_km], [_pace_to_display(seg.gap_s_per_km)],
                            color="#ffd700", s=40, zorder=5, label="GAP" if i == 0 else "")
        ax_pace.invert_yaxis()  # lower min/mile = faster = top of chart
        ax_pace.set_title("Pace (min/mi)", color="white", fontsize=10)
        ax_pace.set_xlabel("Distance (km)", color="#aaaaaa", fontsize=8)
        ax_pace.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{int(v)}:{int((v % 1)*60):02d}")
        )
        ax_pace.legend(fontsize=7, facecolor="#2d2d4e", labelcolor="white")

    # ── HR over distance ──────────────────────────────────────────────────────
    if dist_km_hr and hr_vals:
        ax_hr.plot(dist_km_hr, hr_vals, color="#ff6b6b", linewidth=1.0, alpha=0.8)
        # Zone threshold lines
        max_hr = 185
        thresholds = [0.60, 0.70, 0.80, 0.90]
        zone_labels = ["Z1/Z2", "Z2/Z3", "Z3/Z4", "Z4/Z5"]
        for thresh, zlabel in zip(thresholds, zone_labels):
            ax_hr.axhline(max_hr * thresh, color="#555577", linewidth=0.5,
                          linestyle="--", alpha=0.6)
        ax_hr.set_title("Heart Rate (bpm)", color="white", fontsize=10)
        ax_hr.set_xlabel("Distance (km)", color="#aaaaaa", fontsize=8)
        ax_hr.set_ylim(bottom=max(0, min(hr_vals) - 10))

    # ── Per-mile pace bars ────────────────────────────────────────────────────
    if segs:
        x = np.arange(len(segs))
        bars = ax_seg_pace.bar(x, seg_pace, color="#4ecdc4", alpha=0.8, label="Pace")
        ax_seg_pace.bar(x, seg_gap, width=0.4, color="#ffd700", alpha=0.7, label="GAP")
        ax_seg_pace.set_xticks(x)
        ax_seg_pace.set_xticklabels(mile_labels, color="white", fontsize=8)
        ax_seg_pace.invert_yaxis()
        ax_seg_pace.set_title("Per-Mile Pace", color="white", fontsize=10)
        ax_seg_pace.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{int(v)}:{int((v % 1)*60):02d}")
        )
        ax_seg_pace.legend(fontsize=7, facecolor="#2d2d4e", labelcolor="white")

    # ── HR zone distribution stacked bars ────────────────────────────────────
    if segs:
        x = np.arange(len(segs))
        bottom = np.zeros(len(segs))
        for zone in range(1, 6):
            vals = np.array([s.hr_zone_distribution.get(zone, 0) for s in segs])
            ax_zone.bar(x, vals, bottom=bottom, color=ZONE_COLORS[zone],
                        label=f"Z{zone}", alpha=0.85)
            bottom += vals
        ax_zone.set_xticks(x)
        ax_zone.set_xticklabels(mile_labels, color="white", fontsize=8)
        ax_zone.set_title("HR Zone Distribution", color="white", fontsize=10)
        ax_zone.set_ylim(0, 1)
        ax_zone.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{int(v * 100)}%")
        )
        ax_zone.legend(fontsize=7, facecolor="#2d2d4e", labelcolor="white",
                       ncol=5, loc="upper right")

    # Overall title
    act = report.activity
    dist_mi = act.distance_meters / 1609.344
    duration_min = int(act.duration_seconds // 60)
    duration_sec = int(act.duration_seconds % 60)
    title = (
        f"{act.name}  ·  {act.start_time_utc.strftime('%b %d %Y')}  ·  "
        f"{dist_mi:.1f} mi  ·  {duration_min}:{duration_sec:02d}"
    )
    fig.suptitle(title, color="white", fontsize=12, fontweight="bold", y=0.98)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read(), title


def make_elevation_chart(report: RunReport) -> Optional[Tuple[bytes, str]]:
    """Elevation profile with pace overlay. Returns None if no elevation data."""
    pts = [p for p in report.timeseries if p.elevation_meters is not None
           and p.distance_meters is not None]
    if len(pts) < 10:
        return None

    dist_km = [p.distance_meters / 1000.0 for p in pts]
    elev = [p.elevation_meters for p in pts]

    fig, ax1 = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a2e")
    _style_ax(ax1)

    # Elevation fill
    ax1.fill_between(dist_km, elev, min(elev) - 5,
                     alpha=0.4, color="#8b6914", label="Elevation")
    ax1.plot(dist_km, elev, color="#ffd700", linewidth=1.5)
    ax1.set_ylabel("Elevation (m)", color="#ffd700", fontsize=9)
    ax1.set_xlabel("Distance (km)", color="#aaaaaa", fontsize=8)

    # Bonk event markers
    for bonk in report.bonk_events:
        # find closest point by elapsed time
        closest = min(pts, key=lambda p: abs(p.elapsed_seconds - bonk.elapsed_seconds_onset))
        ax1.axvline(closest.distance_meters / 1000.0,
                    color="#ff4444", linewidth=2, linestyle="--", alpha=0.8)
        ax1.text(closest.distance_meters / 1000.0, max(elev) * 0.95,
                 "⚡bonk", color="#ff4444", fontsize=8, ha="center")

    caption = f"Elevation Profile — {report.activity.name}"
    fig.suptitle(caption, color="white", fontsize=11, y=1.02)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read(), caption


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _style_ax(ax) -> None:
    """Apply dark theme styling to a matplotlib Axes."""
    ax.set_facecolor("#2d2d4e")
    ax.tick_params(colors="white", labelsize=8)
    ax.spines["bottom"].set_color("#555577")
    ax.spines["left"].set_color("#555577")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _rolling_median(arr: np.ndarray, window: int) -> np.ndarray:
    """Simple rolling median — edges use partial windows."""
    result = np.empty(len(arr))
    half = window // 2
    for i in range(len(arr)):
        lo = max(0, i - half)
        hi = min(len(arr), i + half + 1)
        result[i] = np.median(arr[lo:hi])
    return result


def png_to_base64(png_bytes: bytes) -> str:
    """Encode PNG bytes as base64 string for embedding in text/HTML."""
    return base64.b64encode(png_bytes).decode("utf-8")
