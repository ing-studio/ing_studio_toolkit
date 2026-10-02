"""Contour lines ("horizontals") of a terrain raster: the level lines the Archicad terrain shows in 3D and the plan
draws in colour, as the survey's contour drawing does."""
import numpy as np
from scipy import ndimage
from shapely import contains_xy
from shapely.geometry import LineString


def eased_raster(z, valid, sigma_px):
    """z eased by a normalized Gaussian over the valid cells (no raster staircase in the lines); NaN elsewhere."""
    ok = valid & np.isfinite(z)
    w = ndimage.gaussian_filter(ok.astype(np.float64), sigma_px)
    s = ndimage.gaussian_filter(np.where(ok, z, 0.0), sigma_px)
    out = np.full(z.shape, np.nan)
    np.divide(s, w, out=out, where=ok & (w > 1e-6))
    return out


def refine_points(vertices, z, gt, mask, tol, spacing_m=2.0, rounds=12, max_add=40000):
    """Points added where the triangulation of `vertices` (x, y, z; lines and points alike) strays more than `tol`
    from z on the mask: the flat triangles a contour-line terrain gets in valleys, on ridges and on tops. Each round
    the worst cell of every spacing_m square that strays is added (its height from z). Returns the added points."""
    from scipy.interpolate import LinearNDInterpolator
    from scipy.spatial import Delaunay
    iy, ix = np.nonzero(mask & np.isfinite(z))
    if not len(ix):
        return np.zeros((0, 3))
    cx = gt[0] + (ix + 0.5) * gt[1]
    cy = gt[3] + (iy + 0.5) * gt[5]
    cz = z[iy, ix]
    added = []
    pts = np.asarray(vertices, dtype=np.float64)
    for _ in range(rounds):
        tri = Delaunay(pts[:, :2])
        err = np.abs(LinearNDInterpolator(tri, pts[:, 2])(cx, cy) - cz)
        bad = np.flatnonzero(np.nan_to_num(err, nan=0.0) > tol)
        if not len(bad):
            break
        cell = np.floor(cx[bad] / spacing_m).astype(np.int64) * 1_000_003 + np.floor(cy[bad] / spacing_m).astype(np.int64)
        order = np.lexsort((-err[bad], cell))
        first = np.r_[True, cell[order][1:] != cell[order][:-1]]
        pick = bad[order[first]]
        new = np.column_stack([cx[pick], cy[pick], cz[pick]])
        added.append(new)
        pts = np.vstack([pts, new])
        if sum(len(a) for a in added) >= max_add:
            break
    return np.vstack(added) if added else np.zeros((0, 3))


def contour_lines(z, gt, valid, interval, sigma_px=2.0, simplify_m=0.1, min_len_m=3.0, keep=None):
    """[(level, xyz array)] - the contours of z at every multiple of `interval` over the valid cells, each vertex at
    exactly its level. `keep` (a polygon) cuts them: only the runs inside it stay (a run needs two vertices; the
    lines are cut on the raster's dense vertices, then simplified within simplify_m)."""
    import contourpy
    zs = eased_raster(z, valid, sigma_px)
    if not np.isfinite(zs).any():
        return []
    h, w = z.shape
    xs = gt[0] + (np.arange(w) + 0.5) * gt[1]
    ys = gt[3] + (np.arange(h) + 0.5) * gt[5]
    gen = contourpy.contour_generator(xs, ys, np.ma.masked_invalid(zs), line_type="Separate")
    lo, hi = np.nanmin(zs), np.nanmax(zs)
    out = []
    for level in np.arange(np.ceil(lo / interval) * interval, hi + 1e-9, interval):
        for seg in gen.lines(float(level)):
            if len(seg) < 2:
                continue
            runs = [seg]
            if keep is not None:
                inside = contains_xy(keep, seg[:, 0], seg[:, 1])
                cut = np.flatnonzero(np.diff(inside.astype(np.int8)) != 0) + 1
                runs = [r for r, k in zip(np.split(seg, cut), np.split(inside, cut)) if k[0] and len(r) >= 2]
            for r in runs:
                line = LineString(r).simplify(simplify_m)
                if line.length < min_len_m:
                    continue
                xy = np.asarray(line.coords)
                out.append((float(level), np.column_stack([xy, np.full(len(xy), float(level))])))
    return out
