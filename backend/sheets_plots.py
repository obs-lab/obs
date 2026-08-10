import io
import math
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Polygon
from scipy import stats

from sheets_compute import ComputeError, clean, clean_pair

PALETTE = [
    "#3d5a80",
    "#98544d",
    "#5c6b73",
    "#2f4858",
    "#7a6a4f",
    "#6b7a80",
    "#455a64",
    "#57708c",
]

CLIENT_PLOTS = {
    "line": "Line",
    "scatter": "Scatter",
    "line_symbol": "Line and symbols",
    "column": "Columns",
    "bar": "Bars",
    "column_stacked": "Stacked columns",
    "column_grouped": "Grouped columns",
    "area": "Area",
    "area_stacked": "Stacked area",
    "pie": "Pie",
    "doughnut": "Doughnut",
    "histogram": "Histogram",
    "box": "Box chart",
    "violin": "Violin",
    "heatmap": "Heatmap",
    "contour": "Contour",
    "surface3d": "3D surface",
    "scatter3d": "3D scatter",
    "polar": "Polar",
    "bubble": "Bubble",
}

SERVER_PLOTS = {
    "qq": "Q-Q plot",
    "probability": "Probability plot",
    "pareto": "Pareto",
    "bland_altman": "Bland-Altman",
    "control_xbar": "X control chart",
    "ternary": "Ternary",
    "piper": "Piper",
    "stiff": "Stiff",
    "wind_rose": "Wind rose",
    "radar": "Radar",
    "poincare": "Poincare",
    "forest": "Forest plot",
}


def plot_catalog() -> Dict[str, Any]:
    return {
        "client": [{"id": k, "label": v} for k, v in CLIENT_PLOTS.items()],
        "server": [{"id": k, "label": v} for k, v in SERVER_PLOTS.items()],
    }


def _figure(width: float = 7.2, height: float = 5.0):
    fig, ax = plt.subplots(figsize=(width, height), dpi=100)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.tick_params(labelsize=9)
    ax.grid(True, color="#e2e2e2", linewidth=0.6)
    ax.set_axisbelow(True)
    return fig, ax


def _to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _label(name: str, units: str = "") -> str:
    return name + (" (" + units + ")" if units else "")


def _qq(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    key = cfg.get("y") or list(series)[0]
    d = clean(series[key])
    if d.size < 3:
        raise ComputeError("At least 3 values are required.")
    fig, ax = _figure()
    (osm, osr), (slope, inter, r) = stats.probplot(d, dist="norm")
    ax.plot(osm, osr, "o", color=PALETTE[0], markersize=4, alpha=0.8)
    ax.plot(osm, slope * osm + inter, "-", color=PALETTE[1], linewidth=1.4)
    ax.set_xlabel("Quantili teorici", fontsize=10)
    ax.set_ylabel("Sample quantiles", fontsize=10)
    ax.set_title("Q-Q plot normale, " + key + "  (R = " + str(round(r, 4)) + ")",
                 fontsize=11)
    return fig


def _probability(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    key = cfg.get("y") or list(series)[0]
    d = np.sort(clean(series[key]))
    if d.size < 3:
        raise ComputeError("At least 3 values are required.")
    probs = (np.arange(1, d.size + 1) - 0.5) / d.size
    fig, ax = _figure()
    ax.plot(d, stats.norm.ppf(probs), "o", color=PALETTE[0], markersize=4)
    mu, sd = float(np.mean(d)), float(np.std(d, ddof=1))
    xs = np.linspace(float(d[0]), float(d[-1]), 100)
    ax.plot(xs, (xs - mu) / sd, "-", color=PALETTE[1], linewidth=1.4)
    ax.set_xlabel(key, fontsize=10)
    ax.set_ylabel("Punteggio normale", fontsize=10)
    ax.set_title("Probability plot, " + key, fontsize=11)
    return fig


def _pareto(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    key = cfg.get("y") or list(series)[0]
    values = clean(series[key])
    labels = cfg.get("labels") or [str(i + 1) for i in range(values.size)]
    order = np.argsort(values)[::-1]
    values = values[order]
    labels = [labels[i] if i < len(labels) else str(i) for i in order]
    total = float(np.sum(values)) or 1.0
    cumulative = np.cumsum(values) / total * 100.0
    fig, ax = _figure(8.0, 5.0)
    positions = np.arange(values.size)
    ax.bar(positions, values, color=PALETTE[0], width=0.7)
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel(key, fontsize=10)
    ax2 = ax.twinx()
    ax2.plot(positions, cumulative, "o-", color=PALETTE[1], linewidth=1.4, markersize=4)
    ax2.axhline(80.0, color="#999999", linestyle="--", linewidth=0.9)
    ax2.set_ylim(0, 105)
    ax2.set_ylabel("Cumulative percentage", fontsize=10)
    ax2.grid(False)
    ax.set_title("Pareto chart", fontsize=11)
    return fig


def _bland_altman(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    keys = list(series)
    a_key = cfg.get("x") or keys[0]
    b_key = cfg.get("y") or (keys[1] if len(keys) > 1 else keys[0])
    a, b = clean_pair(series[a_key], series[b_key])
    if a.size < 3:
        raise ComputeError("At least 3 valid pairs are required.")
    mean = (a + b) / 2.0
    diff = a - b
    md, sd = float(np.mean(diff)), float(np.std(diff, ddof=1))
    fig, ax = _figure()
    ax.plot(mean, diff, "o", color=PALETTE[0], markersize=5, alpha=0.8)
    ax.axhline(md, color=PALETTE[1], linewidth=1.4)
    ax.axhline(md + 1.96 * sd, color="#999999", linestyle="--", linewidth=1.0)
    ax.axhline(md - 1.96 * sd, color="#999999", linestyle="--", linewidth=1.0)
    ax.text(0.99, 0.95, "mean " + str(round(md, 4)), transform=ax.transAxes,
            ha="right", fontsize=8, color=PALETTE[1])
    ax.set_xlabel("Mean of the two methods", fontsize=10)
    ax.set_ylabel("Difference " + a_key + " minus " + b_key, fontsize=10)
    ax.set_title("Bland-Altman", fontsize=11)
    return fig


def _control_chart(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    key = cfg.get("y") or list(series)[0]
    d = clean(series[key])
    if d.size < 5:
        raise ComputeError("At least 5 observations are required.")
    mean, sd = float(np.mean(d)), float(np.std(d, ddof=1))
    ucl, lcl = mean + 3 * sd, mean - 3 * sd
    fig, ax = _figure(8.0, 4.6)
    idx = np.arange(1, d.size + 1)
    ax.plot(idx, d, "o-", color=PALETTE[0], linewidth=1.2, markersize=4)
    ax.axhline(mean, color=PALETTE[2], linewidth=1.3)
    ax.axhline(ucl, color=PALETTE[1], linestyle="--", linewidth=1.1)
    ax.axhline(lcl, color=PALETTE[1], linestyle="--", linewidth=1.1)
    out = (d > ucl) | (d < lcl)
    if out.any():
        ax.plot(idx[out], d[out], "o", color="#b03030", markersize=8,
                markerfacecolor="none", markeredgewidth=1.6)
    ax.set_xlabel("Observation", fontsize=10)
    ax.set_ylabel(key, fontsize=10)
    ax.set_title("Individual control chart, out of control: "
                 + str(int(out.sum())), fontsize=11)
    return fig


def _ternary_axes(ax, labels: List[str]):
    tri = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, math.sqrt(3) / 2.0]])
    ax.add_patch(Polygon(tri, closed=True, fill=False, edgecolor="#555555",
                         linewidth=1.2))
    for f in (0.2, 0.4, 0.6, 0.8):
        for i in range(3):
            p1 = tri[i] + (tri[(i + 1) % 3] - tri[i]) * f
            p2 = tri[i] + (tri[(i + 2) % 3] - tri[i]) * f
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color="#e2e2e2",
                    linewidth=0.6, zorder=0)
    offsets = [(-0.04, -0.05), (0.04, -0.05), (0.0, 0.04)]
    for i, lab in enumerate(labels[:3]):
        ax.text(tri[i][0] + offsets[i][0], tri[i][1] + offsets[i][1], lab,
                ha="center", fontsize=9)
    ax.set_xlim(-0.12, 1.12)
    ax.set_ylim(-0.12, 1.02)
    ax.set_aspect("equal")
    ax.axis("off")


def _ternary_xy(a: np.ndarray, b: np.ndarray, c: np.ndarray):
    total = a + b + c
    total[total == 0] = 1.0
    a, b, c = a / total, b / total, c / total
    return b + c * 0.5, c * math.sqrt(3) / 2.0


def _ternary(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    keys = cfg.get("components") or list(series)[:3]
    if len(keys) < 3:
        raise ComputeError("The ternary diagram requires three columns.")
    a, b, c = (np.asarray(series[k], dtype=float) for k in keys[:3])
    mask = np.isfinite(a) & np.isfinite(b) & np.isfinite(c)
    a, b, c = a[mask], b[mask], c[mask]
    if a.size == 0:
        raise ComputeError("No valid triplet.")
    fig, ax = plt.subplots(figsize=(6.4, 5.8), dpi=100)
    fig.patch.set_facecolor("white")
    _ternary_axes(ax, keys[:3])
    xs, ys = _ternary_xy(a, b, c)
    ax.scatter(xs, ys, s=34, color=PALETTE[0], alpha=0.85, edgecolors="white",
               linewidths=0.5, zorder=3)
    ax.set_title("Ternary diagram", fontsize=11)
    return fig


def _piper(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    need = ["ca", "mg", "na_k", "hco3", "so4", "cl"]
    mapping = cfg.get("components") or {}
    keys = [mapping.get(k) for k in need]
    if any(k is None or k not in series for k in keys):
        raise ComputeError(
            "The Piper diagram requires six columns: Ca, Mg, Na+K, HCO3, SO4, Cl."
        )
    vals = [np.asarray(series[k], dtype=float) for k in keys]
    mask = np.all([np.isfinite(v) for v in vals], axis=0)
    ca, mg, nak, hco3, so4, cl = (v[mask] for v in vals)
    if ca.size == 0:
        raise ComputeError("No valid sample.")
    fig, ax = plt.subplots(figsize=(7.6, 6.8), dpi=100)
    fig.patch.set_facecolor("white")
    ax.set_aspect("equal")
    ax.axis("off")
    h = math.sqrt(3) / 2.0
    gap = 0.28
    left = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, h]])
    right = left + np.array([1.0 + gap, 0.0])
    dx, dy = (1.0 + gap) / 2.0, h + gap / 2.0
    diamond = np.array([[dx, dy], [dx + 0.5, dy + h], [dx + 1.0, dy],
                        [dx + 0.5, dy - h]])
    for shape in (left, right, diamond):
        ax.add_patch(Polygon(shape, closed=True, fill=False,
                             edgecolor="#555555", linewidth=1.1))
    cx, cy = _ternary_xy(mg.copy(), ca.copy(), nak.copy())
    ax.scatter(cx, cy, s=26, color=PALETTE[0], alpha=0.85, zorder=3,
               edgecolors="white", linewidths=0.4)
    ax_, ay_ = _ternary_xy(hco3.copy(), cl.copy(), so4.copy())
    ax.scatter(ax_ + 1.0 + gap, ay_, s=26, color=PALETTE[1], alpha=0.85,
               zorder=3, edgecolors="white", linewidths=0.4)
    cat = ca + mg + nak
    cat[cat == 0] = 1.0
    ani = hco3 + so4 + cl
    ani[ani == 0] = 1.0
    px = nak / cat
    py = (so4 + cl) / ani
    dxp = dx + 0.5 + (px - py) * 0.5
    dyp = dy + (px + py - 1.0) * h
    ax.scatter(dxp, dyp, s=30, color=PALETTE[3], alpha=0.9, zorder=3,
               edgecolors="white", linewidths=0.4)
    ax.text(0.5, -0.09, "Cationi", ha="center", fontsize=9)
    ax.text(1.5 + gap, -0.09, "Anioni", ha="center", fontsize=9)
    ax.set_xlim(-0.15, 2.0 + gap + 0.15)
    ax.set_ylim(-0.18, dy + h + 0.15)
    ax.set_title("Piper diagram", fontsize=11)
    return fig


def _stiff(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    mapping = cfg.get("components") or {}
    cations = ["na_k", "ca", "mg"]
    anions = ["cl", "hco3", "so4"]
    keys = [mapping.get(k) for k in cations + anions]
    if any(k is None or k not in series for k in keys):
        raise ComputeError(
            "The Stiff diagram requires six columns: Na+K, Ca, Mg, Cl, HCO3, SO4."
        )
    row = int(cfg.get("row", 0))
    vals = []
    for k in keys:
        arr = np.asarray(series[k], dtype=float)
        if row >= arr.size or not np.isfinite(arr[row]):
            raise ComputeError("Selected row has no valid values.")
        vals.append(float(arr[row]))
    fig, ax = plt.subplots(figsize=(5.6, 4.4), dpi=100)
    fig.patch.set_facecolor("white")
    levels = [1.0, 0.0, -1.0]
    pts = [(-vals[i], levels[i]) for i in range(3)]
    pts += [(vals[i + 3], levels[2 - i]) for i in range(3)]
    ax.add_patch(Polygon(np.array(pts), closed=True, facecolor=PALETTE[0],
                         alpha=0.45, edgecolor=PALETTE[0], linewidth=1.3))
    ax.axvline(0.0, color="#555555", linewidth=1.0)
    lim = max(max(vals) * 1.25, 1.0)
    for i, lab in enumerate(["Na+K", "Ca", "Mg"]):
        ax.text(-lim * 0.97, levels[i], lab, ha="left", va="center", fontsize=9)
    for i, lab in enumerate(["Cl", "HCO3", "SO4"]):
        ax.text(lim * 0.97, levels[2 - i], lab, ha="right", va="center", fontsize=9)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-1.7, 1.7)
    ax.set_yticks([])
    ax.set_xlabel("meq/l", fontsize=10)
    ax.set_title("Stiff diagram, row " + str(row + 1), fontsize=11)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    return fig


def _wind_rose(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    dir_key = cfg.get("direction") or cfg.get("x")
    spd_key = cfg.get("speed") or cfg.get("y")
    if not dir_key or dir_key not in series:
        raise ComputeError("A direction column in degrees is required.")
    direction = np.asarray(series[dir_key], dtype=float)
    if spd_key and spd_key in series:
        speed = np.asarray(series[spd_key], dtype=float)
    else:
        speed = np.ones_like(direction)
    mask = np.isfinite(direction) & np.isfinite(speed)
    direction, speed = direction[mask] % 360.0, speed[mask]
    if direction.size == 0:
        raise ComputeError("No valid data.")
    nsect = int(cfg.get("sectors", 16))
    edges = np.linspace(0, 360, nsect + 1)
    sector = np.digitize(direction, edges) - 1
    sector[sector == nsect] = 0
    bands = [0, 2, 4, 6, 8, np.inf]
    fig = plt.figure(figsize=(6.2, 6.0), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    theta = np.deg2rad(edges[:-1] + 360.0 / nsect / 2.0)
    width = np.deg2rad(360.0 / nsect) * 0.9
    bottom = np.zeros(nsect)
    for bi in range(len(bands) - 1):
        counts = np.zeros(nsect)
        sel = (speed >= bands[bi]) & (speed < bands[bi + 1])
        for s in sector[sel]:
            counts[int(s)] += 1
        counts = counts / max(direction.size, 1) * 100.0
        upper = "+" if math.isinf(bands[bi + 1]) else str(bands[bi + 1])
        ax.bar(theta, counts, width=width, bottom=bottom,
               color=PALETTE[bi % len(PALETTE)], edgecolor="white",
               linewidth=0.5, label=str(bands[bi]) + " - " + upper)
        bottom += counts
    ax.set_title("Wind rose, percentage", fontsize=11, pad=18)
    ax.legend(loc="upper right", bbox_to_anchor=(1.24, 1.10), fontsize=8,
              frameon=False)
    return fig


def _radar(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    keys = cfg.get("values") or [k for k in series][:8]
    if len(keys) < 3:
        raise ComputeError("The radar requires at least three columns.")
    rows = int(cfg.get("rows", 1))
    fig = plt.figure(figsize=(6.2, 5.8), dpi=100)
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111, projection="polar")
    angles = np.linspace(0, 2 * np.pi, len(keys), endpoint=False).tolist()
    angles += angles[:1]
    maxima = []
    for k in keys:
        arr = clean(np.asarray(series[k], dtype=float))
        maxima.append(float(np.max(np.abs(arr))) if arr.size else 1.0)
    scale = [m or 1.0 for m in maxima]
    for r in range(max(1, min(rows, 6))):
        vals = []
        for i, k in enumerate(keys):
            arr = np.asarray(series[k], dtype=float)
            v = arr[r] if r < arr.size and np.isfinite(arr[r]) else 0.0
            vals.append(float(v) / scale[i])
        vals += vals[:1]
        color = PALETTE[r % len(PALETTE)]
        ax.plot(angles, vals, linewidth=1.5, color=color, label="Row " + str(r + 1))
        ax.fill(angles, vals, color=color, alpha=0.18)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(keys, fontsize=9)
    ax.set_title("Radar, normalized values", fontsize=11, pad=18)
    if rows > 1:
        ax.legend(loc="upper right", bbox_to_anchor=(1.22, 1.10), fontsize=8,
                  frameon=False)
    return fig


def _poincare(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    key = cfg.get("y") or list(series)[0]
    d = clean(np.asarray(series[key], dtype=float))
    if d.size < 4:
        raise ComputeError("At least 4 values are required.")
    x, y = d[:-1], d[1:]
    diff = y - x
    sd1 = float(np.std(diff, ddof=1) / math.sqrt(2))
    sd2 = float(math.sqrt(max(2 * np.var(d, ddof=1) - sd1 ** 2, 0.0)))
    fig, ax = _figure(6.0, 5.6)
    ax.plot(x, y, "o", color=PALETTE[0], markersize=4, alpha=0.7)
    cx, cy = float(np.mean(x)), float(np.mean(y))
    from matplotlib.patches import Ellipse

    ax.add_patch(
        Ellipse((cx, cy), 2 * sd2, 2 * sd1, angle=45.0, fill=False,
                edgecolor=PALETTE[1], linewidth=1.5)
    )
    lo, hi = float(min(d.min(), d.min())), float(max(d.max(), d.max()))
    ax.plot([lo, hi], [lo, hi], "--", color="#999999", linewidth=0.9)
    ax.set_xlabel(key + " (n)", fontsize=10)
    ax.set_ylabel(key + " (n+1)", fontsize=10)
    ax.set_aspect("equal")
    ax.set_title("Poincare, SD1 = " + str(round(sd1, 4)) + ", SD2 = "
                 + str(round(sd2, 4)), fontsize=11)
    return fig


def _forest(series: Dict[str, np.ndarray], cfg: Dict[str, Any]):
    est_key = cfg.get("y") or list(series)[0]
    est = np.asarray(series[est_key], dtype=float)
    lo_key, hi_key = cfg.get("lower"), cfg.get("upper")
    err_key = cfg.get("error")
    if lo_key in series and hi_key in series:
        lo = np.asarray(series[lo_key], dtype=float)
        hi = np.asarray(series[hi_key], dtype=float)
    elif err_key in series:
        err = np.asarray(series[err_key], dtype=float)
        lo, hi = est - err, est + err
    else:
        raise ComputeError("Confidence limits or an error column are required.")
    labels = cfg.get("labels") or [str(i + 1) for i in range(est.size)]
    mask = np.isfinite(est) & np.isfinite(lo) & np.isfinite(hi)
    est, lo, hi = est[mask], lo[mask], hi[mask]
    labels = [labels[i] for i in range(len(labels)) if i < mask.size and mask[i]]
    if est.size == 0:
        raise ComputeError("No valid estimate.")
    weights = 1.0 / np.maximum(((hi - lo) / 3.92) ** 2, 1e-12)
    pooled = float(np.sum(weights * est) / np.sum(weights))
    fig, ax = _figure(7.4, max(3.0, 0.42 * est.size + 1.6))
    ypos = np.arange(est.size)[::-1]
    ax.errorbar(est, ypos, xerr=[est - lo, hi - est], fmt="s", color=PALETTE[0],
                markersize=6, capsize=3, linewidth=1.2)
    ax.axvline(pooled, color=PALETTE[1], linestyle="--", linewidth=1.2)
    ax.axvline(0.0, color="#999999", linewidth=0.8)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel(est_key, fontsize=10)
    ax.set_title("Forest plot, pooled estimate " + str(round(pooled, 4)), fontsize=11)
    ax.grid(True, axis="x", color="#e2e2e2", linewidth=0.6)
    return fig


_RENDERERS = {
    "qq": _qq,
    "probability": _probability,
    "pareto": _pareto,
    "bland_altman": _bland_altman,
    "control_xbar": _control_chart,
    "ternary": _ternary,
    "piper": _piper,
    "stiff": _stiff,
    "wind_rose": _wind_rose,
    "radar": _radar,
    "poincare": _poincare,
    "forest": _forest,
}


def render(plot_type: str, series: Dict[str, np.ndarray], config: Dict[str, Any]) -> str:
    renderer = _RENDERERS.get(plot_type)
    if renderer is None:
        raise ComputeError("Chart type not handled by the server: " + str(plot_type))
    fig = renderer(series, config or {})
    title = (config or {}).get("title")
    if title:
        fig.axes[0].set_title(str(title)[:120], fontsize=11)
    return _to_svg(fig)
