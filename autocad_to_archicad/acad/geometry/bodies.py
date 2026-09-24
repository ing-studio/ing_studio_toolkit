"""Closed 3D bodies for Archicad Morphs: (vertices [(x, y, z)], faces), faces facing outwards. A face is a list of
vertex ids (counter-clockwise seen from outside), or (outer ids, [hole ids]) for a flat face with holes.

  prism         a footprint (holes allowed) from z0 to z1: one flat face on top and one below, a quad per side
  surface_body  a paved surface that follows a height function (a street on its profile, with its cross fall):
                the area cut into grid cells, each triangulated, the same surface `depth` lower, and the sides
"""
import math

import numpy as np
from shapely import constrained_delaunay_triangles, intersection
from shapely.geometry import box
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree


class _Verts:
    def __init__(self, nd=4):
        self.index, self.xyz, self.nd = {}, [], nd

    def __call__(self, x, y, z):
        k = (round(float(x), self.nd), round(float(y), self.nd), round(float(z), self.nd))
        if k not in self.index:
            self.index[k] = len(self.xyz)
            self.xyz.append(k)
        return self.index[k]


def prism(poly, z0, z1):
    """Closed prism of a polygon (holes allowed) from z0 to z1."""
    poly = orient(poly, 1.0)  # exterior counter-clockwise, holes clockwise
    vid = _Verts()
    faces = []
    rings = [np.asarray(r.coords)[:-1] for r in [poly.exterior] + list(poly.interiors)]
    for c in rings:
        n = len(c)
        for i in range(n):
            a, b = c[i], c[(i + 1) % n]
            faces.append([vid(a[0], a[1], z0), vid(b[0], b[1], z0), vid(b[0], b[1], z1), vid(a[0], a[1], z1)])
    top = [[vid(x, y, z1) for x, y in c] for c in rings]
    bottom = [[vid(x, y, z0) for x, y in c[::-1]] for c in rings]
    faces.append((top[0], top[1:]))            # seen from above: outer counter-clockwise, holes clockwise
    faces.append((bottom[0], bottom[1:]))      # seen from below: the other way round
    return vid.xyz, faces


def _triangles(poly, cell):
    """Triangles covering the polygon, with vertices on a `cell` grid inside it (so a height function is followed)."""
    x0, y0, x1, y1 = poly.bounds
    xs = np.arange(math.floor(x0 / cell) * cell, x1 + cell, cell)
    ys = np.arange(math.floor(y0 / cell) * cell, y1 + cell, cell)
    cells = [box(x, y, x + cell, y + cell) for x in xs[:-1] for y in ys[:-1]]
    hit = STRtree(cells).query(poly, predicate="intersects")
    out = []
    for piece in intersection(poly, [cells[i] for i in hit]):
        for part in getattr(piece, "geoms", [piece]):
            if part.geom_type == "Polygon" and part.area > 1e-6:
                out += [orient(t, 1.0) for t in constrained_delaunay_triangles(part).geoms if t.area > 1e-8]
    return out


def surface_body(poly, zfun, depth, cell=2.0):
    """A slab `depth` thick whose top follows zfun(xy array) -> z over the polygon (holes allowed); closed."""
    tris = _triangles(poly, cell)
    if not tris:
        return [], []
    key = lambda x, y: (round(float(x), 3), round(float(y), 3))
    index, xy = {}, []
    tri_ids = []
    for t in tris:
        ids = []
        for x, y in np.asarray(t.exterior.coords)[:-1]:
            k = key(x, y)
            if k not in index:
                index[k] = len(xy)
                xy.append(k)
            ids.append(index[k])
        if len(set(ids)) == 3:
            tri_ids.append(ids)
    xy = np.array(xy)
    z = np.asarray(zfun(xy), dtype=np.float64)
    n = len(xy)
    verts = [(x, y, round(float(zz), 4)) for (x, y), zz in zip(xy, z)] + \
            [(x, y, round(float(zz) - depth, 4)) for (x, y), zz in zip(xy, z)]
    faces = []
    edges = {}
    for a, b, c in tri_ids:
        faces.append([a, b, c])                 # top, counter-clockwise from above
        faces.append([c + n, b + n, a + n])     # bottom, seen from below
        for p, q in ((a, b), (b, c), (c, a)):
            edges[(p, q)] = edges.get((p, q), 0) + 1
    # the outline: triangle edges not shared with another triangle (inside on their left)
    for (p, q), k in edges.items():
        if (q, p) not in edges:
            faces.append([p + n, q + n, q, p])
    return verts, faces


def is_closed(faces):
    """Every edge used by exactly two faces, once in each direction (a watertight, consistently oriented body)."""
    count = {}
    for f in faces:
        loops = [f[0]] + list(f[1]) if isinstance(f, tuple) else [f]
        for loop in loops:
            for a, b in zip(loop, loop[1:] + loop[:1]):
                count[(a, b)] = count.get((a, b), 0) + 1
    return all(v == 1 and count.get((b, a)) == 1 for (a, b), v in count.items())
