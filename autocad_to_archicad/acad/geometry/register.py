"""Rigid 2D matching of two point sets (rotation + shift, no scale): a rotation search with FFT cross-correlation of
rasterised points, then trimmed ICP.

The moving points are rotated about their centroid; for each angle the correlation gives the best shift, so the
result is  p -> R(angle) (p - centroid) + T.  A match is trusted when the best angle scores clearly above the typical
angle (peak ratio): a false match scores like any other angle.
"""
import math

import numpy as np
from scipy import fft as sfft
from scipy import ndimage
from scipy.spatial import cKDTree

from .crs import Rigid2D


def densify_polylines(lines, step):
    """Points every `step` along a list of (N, 2) polylines."""
    out = []
    for xy in lines:
        xy = np.asarray(xy, dtype=np.float64)
        if len(xy) < 2:
            continue
        for a, b in zip(xy[:-1], xy[1:]):
            n = max(1, int(np.hypot(*(b - a)) / step))
            t = np.linspace(0.0, 1.0, n + 1)[:-1, None]
            out.append(a + (b - a) * t)
        out.append(xy[-1:])
    return np.vstack(out) if out else np.zeros((0, 2))


def rasterise(pts, x0, y0, shape, res, sigma_px=1.0, weights=None):
    """Image [iy, ix] (rows increase with y) with pixel (0, 0) at (x0, y0); blurred."""
    g = np.zeros(shape, np.float32)
    ix = np.floor((pts[:, 0] - x0) / res).astype(np.int64)
    iy = np.floor((pts[:, 1] - y0) / res).astype(np.int64)
    ok = (ix >= 0) & (ix < shape[1]) & (iy >= 0) & (iy < shape[0])
    np.add.at(g, (iy[ok], ix[ok]), 1.0 if weights is None else weights[ok])
    g = np.minimum(g, 1.0)
    return ndimage.gaussian_filter(g, sigma_px) if sigma_px else g


def _subpixel(cc, iy, ix):
    def para(m, c, p):
        d = m - 2 * c + p
        return 0.0 if d == 0 else 0.5 * (m - p) / d
    H, W = cc.shape
    dy = para(cc[(iy - 1) % H, ix], cc[iy, ix], cc[(iy + 1) % H, ix])
    dx = para(cc[iy, (ix - 1) % W], cc[iy, ix], cc[iy, (ix + 1) % W])
    return float(np.clip(dy, -0.5, 0.5)), float(np.clip(dx, -0.5, 0.5))


def rotation_search(moving, fixed, res, angles_deg, expected=None, radius=None, sigma_px=1.0, fixed_image=None):
    """Best rigid placement of `moving` points onto `fixed` points (or a prepared fixed image).

    fixed_image: optional (image, x0, y0) instead of fixed points. expected/radius: the moved centroid must land within
    `radius` of `expected`. Returns dict(angle_deg, T, score, peak_ratio, scores[(angle, score)], centroid)."""
    moving = np.asarray(moving, dtype=np.float64)
    cm = moving.mean(axis=0)
    if fixed_image is None:
        fx0, fy0 = fixed.min(axis=0) - 5 * res
        fshape = (int((fixed[:, 1].max() - fy0) / res) + 6, int((fixed[:, 0].max() - fx0) / res) + 6)
        F = rasterise(fixed, fx0, fy0, fshape, res, sigma_px)
    else:
        F, fx0, fy0 = fixed_image
        fshape = F.shape
    rmax = float(np.max(np.hypot(*(moving - cm).T))) + 5 * res
    mside = int(2 * rmax / res) + 4
    H = sfft.next_fast_len(fshape[0] + mside)
    W = sfft.next_fast_len(fshape[1] + mside)
    Fp = np.zeros((H, W), np.float32)
    Fp[:fshape[0], :fshape[1]] = F - F.mean()
    FF = sfft.rfft2(Fp, workers=-1)
    dyv = np.where(np.arange(H) > H // 2, np.arange(H) - H, np.arange(H))
    dxv = np.where(np.arange(W) > W // 2, np.arange(W) - W, np.arange(W))
    rows = []
    for ang in angles_deg:
        a = math.radians(ang)
        R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        q = (moving - cm) @ R.T
        mx0 = my0 = -rmax
        M = np.zeros((H, W), np.float32)
        M[:mside, :mside] = rasterise(q, mx0, my0, (mside, mside), res, sigma_px)
        norm = float(np.linalg.norm(M)) or 1.0
        cc = sfft.irfft2(FF * np.conj(sfft.rfft2(M, workers=-1)), s=(H, W), workers=-1)
        Tx = fx0 - mx0 + dxv[None, :] * res
        Ty = fy0 - my0 + dyv[:, None] * res
        if expected is not None and radius is not None:
            mask = (np.abs(Tx - expected[0]) <= radius) & (np.abs(Ty - expected[1]) <= radius)
            cc = np.where(mask, cc, -np.inf)
        k = int(np.argmax(cc))
        iy, ix = divmod(k, W)
        sy, sx = _subpixel(np.where(np.isfinite(cc), cc, 0.0), iy, ix)
        T = np.array([fx0 - mx0 + (dxv[ix] + sx) * res, fy0 - my0 + (dyv[iy] + sy) * res])
        rows.append((float(cc[iy, ix]) / norm, float(ang), T))
    rows.sort(key=lambda r: -r[0])
    scores = np.array([r[0] for r in rows])
    best = rows[0]
    typical = float(np.median(scores)) if len(scores) > 2 else float("nan")
    return {"angle_deg": best[1], "T": best[2], "score": best[0], "centroid": cm,
            "peak_ratio": best[0] / typical if typical and typical > 0 else float("inf"),
            "scores": [(r[1], r[0]) for r in rows]}


def peak_angle(result, within=0.03):
    """Rotation at the top of the score curve (parabola through the angles scoring within `within` of the best):
    steadier than the single best angle when neighbouring angles score almost the same."""
    a = np.array([s[0] for s in result["scores"]])
    v = np.array([s[1] for s in result["scores"]])
    top = v >= v.max() * (1.0 - within)
    if top.sum() < 3:
        return result["angle_deg"]
    c2, c1, _ = np.polyfit(a[top], v[top], 2)
    if c2 >= 0:
        return result["angle_deg"]
    return float(np.clip(-c1 / (2 * c2), a[top].min(), a[top].max()))


def to_rigid(result):
    """p -> R (p - c) + T  as a Rigid2D (p' = R p + t)."""
    a = math.radians(result["angle_deg"])
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    t = result["T"] - R @ result["centroid"]
    return Rigid2D(a, *t)


def icp(moving, fixed, start, limits=(5.0,) * 10 + (2.0,) * 15 + (1.0,) * 15):
    """Trimmed rigid ICP from a Rigid2D start; returns (Rigid2D, stats)."""
    tree = cKDTree(fixed)
    cur = start.apply(moving)
    for lim in limits:
        d, i = tree.query(cur, distance_upper_bound=lim)
        ok = np.isfinite(d)
        if ok.sum() < 10:
            break
        src, dst = cur[ok], fixed[i[ok]]
        ms, md = src.mean(axis=0), dst.mean(axis=0)
        U, _, Vt = np.linalg.svd((src - ms).T @ (dst - md))
        Rr = (U @ Vt).T
        if np.linalg.det(Rr) < 0:
            Vt[-1] *= -1
            Rr = (U @ Vt).T
        cur = (cur - ms) @ Rr.T + md
    A = np.c_[moving, np.ones(len(moving))]
    sol, *_ = np.linalg.lstsq(A, cur, rcond=None)
    lin = sol[:2].T
    ang = math.atan2(lin[1, 0] - lin[0, 1], lin[0, 0] + lin[1, 1])
    R = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
    t = (cur - moving @ R.T).mean(axis=0)
    result = Rigid2D(ang, *t)
    d, _ = tree.query(result.apply(moving))
    return result, {"within_0_5m_pct": round(100 * float(np.mean(d < 0.5)), 1),
                    "within_1m_pct": round(100 * float(np.mean(d < 1.0)), 1),
                    "within_2m_pct": round(100 * float(np.mean(d < 2.0)), 1), "median_m": round(float(np.median(d)), 2)}
