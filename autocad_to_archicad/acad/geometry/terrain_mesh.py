"""The terrain mesh: one outline + adaptive points of the DEM, its triangulation, and cutting it with levels."""
import json
import math
from collections import defaultdict
from functools import reduce

import numpy as np
from osgeo import gdal, ogr
from scipy.spatial import Delaunay
from shapely import contains_xy, segmentize
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from ..util import warn
from .raster import nearest_fill, quadtree_points, sample_raster

gdal.UseExceptions()
ogr.UseExceptions()


# --------------------------------------------------------------------------- building the mesh
def footprint_polygon(footprint_tif, simplify_m):
    """The mesh outline: the survey footprint as ONE polygon (holes > 100 m2 kept). A mesh has one outline, so
    when the footprint falls apart only the largest part is used, and that is logged."""
    ds = gdal.Open(str(footprint_tif))
    band = ds.GetRasterBand(1)
    vds = (ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")).CreateDataSource("fp")
    lyr = vds.CreateLayer("fp", geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, band, lyr, 0)
    polys = [shape(json.loads(f.GetGeometryRef().ExportToJson())) for f in lyr if f.GetField("v") == 1]
    geom = unary_union(polys).buffer(0).simplify(simplify_m, preserve_topology=True).buffer(0)
    parts = sorted(list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom], key=lambda p: -p.area)
    if len(parts) > 1:
        warn(f"contours: the footprint has {len(parts)} separate parts; only the largest "
            f"({parts[0].area:,.0f} m2) is used, {sum(p.area for p in parts[1:]):,.0f} m2 left out")
    poly = parts[0]
    return Polygon(poly.exterior, [r for r in poly.interiors if Polygon(r).area > 100.0])


def adaptive_points(z, gt, valid, m):
    """Adaptive terrain points: the smallest vertical tolerance (min_tolerance_m .. max_tolerance_m) whose point
    count stays within target_points. Returns (tolerance, (N, 3) points)."""
    res = gt[1]
    kw = dict(min_px=max(1, int(round(1.0 / res))), max_px=int(round(32.0 / res)))
    lo, hi, target = float(m["min_tolerance_m"]), float(m["max_tolerance_m"]), int(m["target_points"])
    pts = quadtree_points(z, gt, valid, lo, **kw)
    if len(pts) <= target:
        return lo, pts
    best = (hi, quadtree_points(z, gt, valid, hi, **kw))
    if len(best[1]) > target:
        warn(f"contours: even {hi} m tolerance gives {len(best[1]):,} points > target {target:,}")
        return best
    for _ in range(7):  # geometric bisection: tolerance within ~5 %
        mid = math.sqrt(lo * hi)
        p = quadtree_points(z, gt, valid, mid, **kw)
        if len(p) <= target:
            hi, best = mid, (mid, p)
        else:
            lo = mid
    return best


def build_mesh(z, gt, valid, footprint_tif, m):
    """Vertices of the single mesh: outline (and holes) every outline_step_m, plus the adaptive interior points.
    Returns dict(polygon, outline, holes, points, tolerance); rings and points are (N, 3) source coordinates."""
    zf = nearest_fill(z, np.isfinite(z))
    poly = footprint_polygon(footprint_tif, float(m["outline_simplify_m"]))
    dense = segmentize(poly, float(m["outline_step_m"]))

    def ring3(r):
        xy = np.asarray(r.coords)[:-1, :2]
        return np.column_stack([xy, sample_raster(zf, gt, xy, nan_outside=False)])

    tol, pts = adaptive_points(z, gt, valid, m)
    pts = pts[contains_xy(poly.buffer(-0.3), pts[:, 0], pts[:, 1])]
    return {"polygon": poly, "outline": ring3(dense.exterior), "holes": [ring3(r) for r in dense.interiors],
            "points": pts, "tolerance": tol}


def triangulate(mesh):
    """Delaunay triangulation of exactly the mesh vertices, without triangles outside the outline or in holes.
    Returns (vertices (N, 3), Delaunay object, kept triangles (M, 3))."""
    v = np.vstack([mesh["outline"]] + list(mesh["holes"]) + [mesh["points"]])
    tri = Delaunay(v[:, :2])
    centre = v[tri.simplices, :2].mean(axis=1)
    inside = contains_xy(Polygon(mesh["outline"][:, :2], [h[:, :2] for h in mesh["holes"]]), centre[:, 0], centre[:, 1])
    return v, tri, tri.simplices[inside]


# --------------------------------------------------------------------------- cutting the mesh
def cut_levels(zmin, zmax, sizes):
    """Levels (m a.s.l.) at which every cut size is served: multiples of the common step of all sizes."""
    cm = [int(round(s * 100)) for s in sizes]
    step = reduce(math.gcd, cm) / 100.0
    return np.round(np.arange(math.ceil(zmin / step) * step, zmax + 1e-9, step), 6)


def on_size(level, size):
    return abs(level / size - round(level / size)) < 1e-6


def cut(v, triangles, level):
    """Intersection of the triangulated mesh with the plane z = level: list of (N, 2) polylines, exact on the
    triangle edges. Lines end on the mesh outline or close on themselves (first point == last point)."""
    zr = v[:, 2] - level
    zr = np.where(zr == 0.0, 1e-9, zr)  # a vertex exactly on the level counts as just above it
    above = zr[triangles] > 0
    crossing = above.any(axis=1) & ~above.all(axis=1)
    t = triangles[crossing].astype(np.int64)  # edge keys i * n + j overflow int32
    if not len(t):
        return []
    n = len(v)
    on, key = [], []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        ia, ib = t[:, a], t[:, b]
        on.append((zr[ia] > 0) != (zr[ib] > 0))
        key.append(np.minimum(ia, ib) * n + np.maximum(ia, ib))
    # every crossing triangle has exactly two crossed edges -> one segment between the two edge keys
    keys = np.where(np.stack(on, axis=1), np.stack(key, axis=1), -1)
    keys.sort(axis=1)
    uniq, inv = np.unique(keys[:, 1:], return_inverse=True)  # the -1 of the uncrossed edge sorts first
    inv = inv.reshape(-1, 2)
    i0, i1 = uniq // n, uniq % n
    w = zr[i0] / (zr[i0] - zr[i1])
    xy = v[i0, :2] + (v[i1, :2] - v[i0, :2]) * w[:, None]

    adj = defaultdict(list)
    for s, (p, q) in enumerate(inv):
        adj[p].append(s)
        adj[q].append(s)
    used = np.zeros(len(inv), bool)

    def walk(start):
        chain, k = [start], start
        while True:
            nxt = next((s for s in adj[k] if not used[s]), None)
            if nxt is None:
                return chain
            used[nxt] = True
            p, q = inv[nxt]
            k = q if p == k else p
            chain.append(k)

    lines = [walk(k) for k, segs in adj.items() if len(segs) == 1 and not used[segs[0]]]  # open: end on the outline
    for s in range(len(inv)):
        if not used[s]:
            lines.append(walk(inv[s][0]))  # closed loops
    return [xy[ch] for ch in lines if len(ch) >= 2]
