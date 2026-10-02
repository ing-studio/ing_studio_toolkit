"""Contour smoothing: Reduce -> cull short lines -> NURBS -> Simplify, applied to every line cut from the mesh."""
import numpy as np
from scipy.interpolate import BSpline

from .polyline import arc_length, catmull_rom, control_points, max_deviation, rdp_mask


def clamped_nurbs(ctrl, degree, samples_per_span=8):
    """Non-periodic B-spline with uniform clamped knots and the points as control points: the curve starts and ends
    on the first/last point and is pulled towards - not through - the others. The degree drops when there are too
    few points."""
    n = len(ctrl)
    k = max(1, min(int(degree), n - 1))
    inner = np.linspace(0.0, 1.0, n - k + 1)[1:-1]
    knots = np.concatenate([np.zeros(k + 1), inner, np.ones(k + 1)])
    u = np.linspace(0.0, 1.0, max(2, (n - 1) * samples_per_span + 1))
    return BSpline(knots, ctrl, k)(u)


def smooth_contour(pts, closed, s):
    """One cut line through the smoothing chain (settings `s` = config contours.smoothing).

    Returns None when the line is culled, else dict(ctrl, curve): ctrl are the Archicad spline points, curve is the
    line Archicad draws through them (within simplify_tolerance_m of the NURBS)."""
    reduced = pts[rdp_mask(pts, max(float(s["reduce_tolerance_m"]), 1e-6))]  # 0.0 -> collinear vertices only
    if arc_length(reduced)[-1] <= float(s["min_length_m"]):
        return None
    nurbs = clamped_nurbs(reduced, s["nurbs_degree"])
    if closed:
        nurbs[-1] = nurbs[0]  # the clamped ends of a closed input meet exactly
    simplify = float(s["simplify_tolerance_m"])
    tol = simplify
    for _ in range(4):  # tighten until the Archicad spline stays within the tolerance of the NURBS
        ctrl = control_points(nurbs, closed, tol, float(s["max_control_spacing_m"]))
        curve = catmull_rom(ctrl, closed, 8)
        if max_deviation(curve, nurbs) <= simplify:
            break
        tol *= 0.5
    return {"ctrl": ctrl, "curve": curve}
