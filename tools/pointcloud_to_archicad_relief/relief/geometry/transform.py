"""Point cloud (source) coordinates -> coordinates of the Archicad project."""
import math

import numpy as np


def apply_transform(t, pts):
    """source (x, y, z) -> PLN absolute (x, y, z); `t` as stored in transform.json by the reference stage."""
    pts = np.asarray(pts, dtype=np.float64)
    lx, ly = pts[:, 0] - t["sx"], pts[:, 1] - t["sy"]
    c, s = math.cos(t["angle"]), math.sin(t["angle"])
    out = np.empty((len(pts), 3))
    out[:, 0] = t["ox"] + c * lx - s * ly
    out[:, 1] = t["oy"] + s * lx + c * ly
    out[:, 2] = t["oz"] + (pts[:, 2] - t["sz"])
    return out


def xy_to_pln(t, xy):
    """2D source points -> PLN x/y."""
    xy = np.asarray(xy, dtype=np.float64)
    return apply_transform(t, np.column_stack([xy, np.zeros(len(xy))]))[:, :2]
