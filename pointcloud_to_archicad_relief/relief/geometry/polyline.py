"""2D polyline helpers: simplification, spline control points, the Archicad spline curve, checks."""
import numpy as np
import shapely
from shapely import STRtree
from shapely.geometry import LineString


def arc_length(curve):
    """Cumulative length along the polyline, starting at 0."""
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(curve, axis=0).T))])


def rdp_mask(pts, tol):
    """Douglas-Peucker keeping original vertices; `tol` is a scalar or one value per vertex. Returns a keep mask."""
    n = len(pts)
    tol = np.broadcast_to(np.asarray(tol, dtype=np.float64), (n,))
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        seg = pts[i + 1:j]
        ab = b - a
        length = np.hypot(*ab)
        if length < 1e-12:
            d = np.hypot(*(seg - a).T)
        else:
            d = np.abs(ab[0] * (seg[:, 1] - a[1]) - ab[1] * (seg[:, 0] - a[0])) / length
        ratio = d / tol[i + 1:j]
        k = int(np.argmax(ratio))
        if ratio[k] > 1.0:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return keep


def control_points(pts, closed, tol, spacing):
    """Spline points: Douglas-Peucker vertices of the curve, at most `spacing` apart. A closed ring loses its
    repeated last point (Archicad closes the spline itself)."""
    keep = rdp_mask(pts, tol)
    s = arc_length(pts)
    idx = np.nonzero(keep)[0]
    extra = []
    for i, j in zip(idx[:-1], idx[1:]):
        if s[j] - s[i] > spacing:
            targets = np.arange(s[i] + spacing, s[j] - spacing * 0.5, spacing)
            extra += list(np.clip(np.searchsorted(s, targets), i + 1, j - 1))
    keep[extra] = True
    ctrl = pts[keep]
    if closed:
        ctrl = ctrl[:-1]
        if len(ctrl) < 4:
            ctrl = pts[:-1][np.linspace(0, len(pts) - 2, 6).astype(int)]
    elif len(ctrl) < 3:
        ctrl = pts[np.unique(np.linspace(0, len(pts) - 1, 3).astype(int))]
    return ctrl


def catmull_rom(points, closed=False, samples_per_segment=8):
    """Centripetal Catmull-Rom curve through the points: how an Archicad spline made from them is drawn."""
    p = np.asarray(points, dtype=np.float64)
    if closed:
        p = np.vstack([p[-1:], p, p[:2]])
    else:
        p = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = []
    t = np.linspace(0.0, 1.0, samples_per_segment, endpoint=False)[:, None]
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        d01 = max(np.linalg.norm(p1 - p0) ** 0.5, 1e-9)
        d12 = max(np.linalg.norm(p2 - p1) ** 0.5, 1e-9)
        d23 = max(np.linalg.norm(p3 - p2) ** 0.5, 1e-9)
        m1 = (p2 - p1 + d12 * ((p1 - p0) / d01 - (p2 - p0) / (d01 + d12)))
        m2 = (p2 - p1 + d12 * ((p3 - p2) / d23 - (p3 - p1) / (d12 + d23)))
        h00 = 2 * t ** 3 - 3 * t ** 2 + 1
        h10 = t ** 3 - 2 * t ** 2 + t
        h01 = -2 * t ** 3 + 3 * t ** 2
        h11 = t ** 3 - t ** 2
        out.append(h00 * p1 + h10 * m1 + h01 * p2 + h11 * m2)
    curve = np.vstack(out)
    return np.vstack([curve, curve[:1]]) if closed else np.vstack([curve, p[-2:-1]])


def max_deviation(a, b):
    """Largest distance from the points of curve `a` to polyline `b`."""
    return float(shapely.distance(shapely.points(a), LineString(b)).max())


def crossing_pairs(curves):
    """Number of pairs of curves that touch or cross."""
    if len(curves) < 2:
        return 0
    geoms = np.array([LineString(cv) for cv in curves], dtype=object)
    a, b = STRtree(geoms).query(geoms, predicate="intersects")
    return int((a < b).sum())
