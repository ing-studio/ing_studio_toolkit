"""Checks of the new streets against ՀՀՇՆ 30-01-2023, beyond the profile (reported, not changed):

  kerb radius     the carriageway edge rounds each junction corner with a radius of at least 12 m (6 m where the
                  place is constrained or rebuilt)
  dead ends       a street that ends without joining another needs a turning place at least 15 m across
  sidewalks       at least the class's sidewalk width (Table 29)
  wheelchairs     sidewalks for wheelchair users: grade at most 83 per mille (1:12); steeper than 30 per mille needs
                  a level landing of 5 m every 100 m
  serpentines     bends tighter than the serpentine radius need at least serpentine_min_radius_m
"""
import math

import numpy as np
from shapely import contains_xy

from .geometry import normals


def kerb_radii(car, nodes, degree, reach=25.0, step=0.5, min_turn_deg=45.0):
    """Radius of the tightest kerb corner at every junction: [(node, xy, radius m or None)].

    Walking along the carriageway outline (the carriageway always on the left), a kerb corner is where the outline
    turns right - into the carriageway - between two streets. A run of right turns adding up to at least
    min_turn_deg is one corner; its radius = its length / its turn (a sharp drawn corner gives almost 0)."""
    from shapely.geometry.polygon import orient
    rings = []
    for poly in getattr(car, "geoms", [car]):
        poly = orient(poly, 1.0)
        for ring in [poly.exterior] + list(poly.interiors):
            n = max(int(ring.length / step), 8)
            pts = np.array([ring.interpolate(i * ring.length / n).coords[0] for i in range(n)])
            d = np.diff(np.vstack([pts, pts[:1]]), axis=0)
            th = np.arctan2(d[:, 1], d[:, 0])
            turn = (np.roll(th, -1) - th + np.pi) % (2 * np.pi) - np.pi   # at the end of segment i
            rings.append((pts, turn, ring.length / n))
    out = []
    w = 4  # turns are judged over w samples (an arc drawn as a polygon turns at its vertices only)
    for j in np.nonzero(degree >= 3)[0]:
        c = nodes[j]
        best = math.inf
        for pts, turn, st in rings:
            near = np.hypot(*(pts - c).T) <= reach
            smooth = np.convolve(np.r_[turn[-w:], turn, turn[:w]], np.ones(w) / w, mode="same")[w:-w]
            right = (smooth < -np.radians(0.8)) & near
            i, n = 0, len(pts)
            while i < n:
                if right[i]:
                    k = i
                    while k < n and right[k]:
                        k += 1
                    total = float(-turn[i:k][turn[i:k] < 0].sum())
                    if total >= np.radians(min_turn_deg):
                        best = min(best, max(0.0, (k - i - (w - 1)) * st) / total)
                    i = k
                else:
                    i += 1
        out.append((int(j), c.tolist(), round(best, 1) if math.isfinite(best) else None))
    return out


def dead_ends(car, nodes, degree, tied, boundary_tree, reach=15.0):
    """Street ends that join nothing: [(node, xy, widest turning place across m)]."""
    out = []
    for j in np.nonzero(degree == 1)[0]:
        if int(j) in tied:
            continue
        c = nodes[j]
        xs = np.linspace(-reach, reach, 31)
        X, Y = np.meshgrid(c[0] + xs, c[1] + xs)
        inside = contains_xy(car, X, Y)
        if not inside.any():
            continue
        d, _ = boundary_tree.query(np.column_stack([X[inside], Y[inside]]))
        out.append((int(j), c.tolist(), round(2.0 * float(d.max()), 1)))
    return out


def sidewalk_widths(e, sw, step=0.1, max_w=8.0):
    """Median sidewalk width on the left and right of a street (m, None where there is none)."""
    if sw is None or sw.is_empty:
        return None, None
    n = normals(e["xy"])
    out = []
    for side in (1.0, -1.0):
        widths = []
        for p, nn, hw in zip(e["xy"][::2], n[::2], e["half_w"][::2]):
            t = np.arange(hw + 0.2, hw + max_w, step)
            q = p[None, :] + side * nn[None, :] * t[:, None]
            inside = contains_xy(sw, q[:, 0], q[:, 1])
            if inside[:5].any():
                first = int(np.argmax(inside))
                run = inside[first:]
                w = (int(np.argmin(run)) if not run.all() else len(run)) * step
                widths.append(w)
        out.append(round(float(np.median(widths)), 2) if len(widths) >= max(3, 0.3 * len(e["xy"][::2])) else None)
    return tuple(out)


def accessibility(e, max_g, landing_g, spacing=100.0, landing=5.0):
    """(metres steeper than max_g, metres steeper than landing_g, landings of `landing` m needed there)."""
    g = np.abs(np.nan_to_num(e["grade"], nan=0.0))
    ds = np.r_[np.diff(e["s"]), 0.0]
    over = float(ds[g > max_g].sum())
    steep = float(ds[g > landing_g].sum())
    return round(over, 1), round(steep, 1), int(steep // spacing)
