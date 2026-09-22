"""Stage qa: accuracy numbers, preview images and report.md in <pln work folder>/qa."""
import json
import math
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

from ..config import cut_sizes  # noqa: E402
from ..geometry.raster import read_raster, sample_raster  # noqa: E402
from ..io.relief_data import read_relief  # noqa: E402
from ..util import load_json, log, save_json  # noqa: E402
from .names import ARCHICAD_RESULT, CONTOURS_SUMMARY, RELIEF_FILE  # noqa: E402


def _hillshade(arr, gt):
    dx, dy = gt[1], -gt[5]
    z = np.where(np.isfinite(arr), arr, np.nanmean(arr))
    gy, gx = np.gradient(z, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315.0), math.radians(45.0)
    hs = np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)
    hs[~np.isfinite(arr)] = np.nan
    return hs, np.degrees(slope)


def _stats(d):
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return {"n": 0}
    core = d[np.abs(d) < 2.0]
    med = float(np.median(d))
    return {"n": int(len(d)), "median_m": round(med, 3), "mean_m": round(float(d.mean()), 3),
            "rmse_m": round(float(np.sqrt(np.mean(d ** 2))), 3),
            "rmse_within_2m": round(float(np.sqrt(np.mean(core ** 2))), 3) if len(core) else None,
            "nmad_m": round(float(1.4826 * np.median(np.abs(d - med))), 3),
            "p95_abs_m": round(float(np.percentile(np.abs(d), 95)), 3),
            "share_abs_gt_0_5m_pct": round(100.0 * float(np.mean(np.abs(d) > 0.5)), 2)}


def _cut_layers(job):
    """{label: [(pts, elev_abs)]} of the contour layers, finest first."""
    _, layers = read_relief(job.p(RELIEF_FILE), list(cut_sizes(job.cfg)))
    return {label: [(c["curve"], c["elev_abs"]) for c in lines] for label, lines in layers.items()}


def _extent(arr, gt):
    return [gt[0], gt[0] + gt[1] * arr.shape[1], gt[3] + gt[5] * arr.shape[0], gt[3]]


def _plot_hillshade(ax, hs, gt, window, title):
    ax.imshow(hs, cmap="gray", extent=_extent(hs, gt), vmin=0, vmax=1, interpolation="bilinear")
    if window:
        ax.set_xlim(window[0], window[2])
        ax.set_ylim(window[1], window[3])
    ax.set_title(title, fontsize=10)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=7)


def _zoom_windows(cfg, dem, gt):
    """Configured zoom windows that are mostly on data; otherwise the four quadrants of the data extent."""
    valid = np.isfinite(dem)
    rows, cols = np.nonzero(valid.any(axis=1))[0], np.nonzero(valid.any(axis=0))[0]
    xmin, xmax = gt[0] + cols[0] * gt[1], gt[0] + (cols[-1] + 1) * gt[1]
    ymax, ymin = gt[3] + rows[0] * gt[5], gt[3] + (rows[-1] + 1) * gt[5]
    wins = {}
    for name, (x0, y0, x1, y1) in (cfg["qa"].get("zooms") or {}).items():
        c0, c1 = sorted((int((x0 - gt[0]) / gt[1]), int((x1 - gt[0]) / gt[1])))
        r0, r1 = sorted((int((y1 - gt[3]) / gt[5]), int((y0 - gt[3]) / gt[5])))
        sub = valid[max(r0, 0):max(r1, 0), max(c0, 0):max(c1, 0)]
        if sub.size and sub.sum() > 0.3 * (r1 - r0) * (c1 - c0):
            wins[name] = (x0, y0, x1, y1)
    if not wins:
        xm, ym = (xmin + xmax) / 2, (ymin + ymax) / 2
        wins = {"quadrant_nw": (xmin, ym, xm, ymax), "quadrant_ne": (xm, ym, xmax, ymax),
                "quadrant_sw": (xmin, ymin, xm, ym), "quadrant_se": (xm, ymin, xmax, ym)}
    return wins


def _ground_points_check(job, dem, gt):
    """Independent check against a reference ground point export (paths.qa_ground_points_txt)."""
    path = job.cfg["paths"].get("qa_ground_points_txt")
    if not path:
        raise RuntimeError("no reference ground points configured (paths.qa_ground_points_txt)")
    q = job.cfg["qa"]
    log("qa: reading reference ground points sample ...")
    df = pd.read_csv(path, sep=r"\s+", header=None, usecols=[0, 1, 2], nrows=int(q["ground_points_max_lines"]),
                     dtype=np.float64, engine="c")
    pts = df.values[:: int(q["ground_points_sample_every"])]
    clip = job.cfg["cloud"].get("clip_source")
    if clip:
        pts = pts[(pts[:, 0] >= clip[0]) & (pts[:, 0] <= clip[2]) & (pts[:, 1] >= clip[1]) & (pts[:, 1] <= clip[3])]
    zd = sample_raster(dem, gt, pts[:, :2])
    on = np.isfinite(zd)
    if on.sum() < 200:
        raise RuntimeError("reference ground points do not overlap this point cloud")
    pts, zd = pts[on], zd[on]
    d = zd - pts[:, 2]
    sl = sample_raster(_hillshade(dem, gt)[1], gt, pts[:, :2])
    return {"all": _stats(d), "slope_lt_15deg": _stats(d[sl < 15]), "slope_ge_15deg": _stats(d[sl >= 15])}


def run(job, force=False):
    qa = job.p("qa")
    qa.mkdir(parents=True, exist_ok=True)
    dem, gt, _ = read_raster(job.c("dem_clean.tif"))
    dem_raw, _, _ = read_raster(job.c("dem_raw.tif"))
    dsm, _, _ = read_raster(job.c("dsm_raw.tif"))
    archicad = load_json(job.p(ARCHICAD_RESULT)) or {}
    report = {"inputs": {"clouds": job.clouds, "pln": job.pln, "output_pln": job.output_pln},
              "cloud": load_json(job.c("cloud_summary.json")), "ground": load_json(job.c("ground_summary.json")),
              "dem": load_json(job.c("dem_summary.json")), "contours": load_json(job.p(CONTOURS_SUMMARY)),
              "transform": (load_json(job.p("transform.json")) or {}).get("best"),
              "archicad": {k: v for k, v in archicad.items() if k not in ("created", "settings")}}

    both = np.isfinite(dem) & np.isfinite(dem_raw)
    report["clean_vs_raw_ground_raster"] = _stats((dem - dem_raw)[both])
    try:
        report["vs_ground_points_txt"] = _ground_points_check(job, dem, gt)
    except Exception as e:
        report["vs_ground_points_txt"] = {"error": str(e)}
        log(f"qa: ground points comparison skipped: {e}")
    save_json(qa / "qa_summary.json", report)

    log("qa: rendering previews ...")
    for old in qa.glob("*.png"):
        old.unlink()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    to_sea = (load_json(job.p("elevation_reference.json")) or {}).get("source_to_sea_level", 0.0)
    hs_dem, _ = _hillshade(dem, gt)
    hs_raw, _ = _hillshade(dsm, gt)
    cut = _cut_layers(job)
    names = list(cut)
    style = {n: (w, col) for n, w, col in zip(names, (0.3, 0.6, 1.1), ("#8a5a3c", "#5a2d0c", "#1a0a02"))}

    fig, axs = plt.subplots(1, 2, figsize=(16, 8), dpi=150)
    _plot_hillshade(axs[0], hs_raw, gt, None, "BEFORE: raw point cloud surface (all points incl. noise)")
    _plot_hillshade(axs[1], hs_dem, gt, None, f"AFTER: clean bare-earth relief ({stamp})")
    fig.tight_layout()
    fig.savefig(qa / "01_before_after.png")
    plt.close(fig)

    def elevation_map(ax, window, title, shown, labels):
        ext = _extent(dem, gt)
        im = ax.imshow(dem + to_sea, cmap="terrain", extent=ext, interpolation="bilinear")
        ax.imshow(hs_dem, cmap="gray", extent=ext, alpha=0.35, vmin=0, vmax=1)
        for n in shown:
            w, col = style[n]
            ax.add_collection(LineCollection([p for p, _ in cut[n]], colors=col, linewidths=w))
        if labels:
            for p, e in cut[names[-1]]:
                q = p[len(p) // 2]
                if len(p) > 2 and (window is None or (window[0] <= q[0] <= window[2] and window[1] <= q[1] <= window[3])):
                    ax.text(q[0], q[1], f"{e:.0f}", fontsize=6, color="#1a0a02", ha="center", va="center",
                            bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.8))
        if window:
            ax.set_xlim(window[0], window[2])
            ax.set_ylim(window[1], window[3])
        ax.set_aspect("equal")
        ax.set_title(title, fontsize=10)
        ax.tick_params(labelsize=7)
        return im

    fig, ax = plt.subplots(figsize=(15, 14), dpi=200)
    im = elevation_map(ax, None, f"contours cut from the mesh: {', '.join(names)} - m a.s.l. ({stamp})", names, False)
    fig.colorbar(im, ax=ax, shrink=0.6, label="m above sea level")
    fig.tight_layout()
    fig.savefig(qa / "02_contours_elevation_full.png")
    plt.close(fig)

    for name, win in _zoom_windows(job.cfg, dem, gt).items():
        fig, axs = plt.subplots(1, len(names), figsize=(8 * len(names), 8), dpi=160)
        for ax, n in zip(np.atleast_1d(axs), names):
            elevation_map(ax, win, f"{name}: layer {n}", [n], n == names[-1])
        fig.tight_layout()
        fig.savefig(qa / f"03_zoom_{name}.png")
        plt.close(fig)

    lines = ["# Relief pipeline QA report", "", f"Generated {stamp}", ""]
    for section, data in report.items():
        lines += [f"## {section}", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```", ""]
    lines.append("Images: " + ", ".join(f"`{p.name}`" for p in sorted(qa.glob("*.png"))))
    (qa / "report.md").write_text("\n".join(lines), encoding="utf-8")
    log(f"qa: report written to {qa / 'report.md'}")
