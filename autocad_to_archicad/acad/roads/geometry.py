"""Street geometry: resampling, normals and bend radii of centre lines, centre lines of street areas (skeleton),
and surfaces built from a centre line (crowned carriageway, sidewalks)."""
from collections import defaultdict

import numpy as np
from scipy import ndimage
from scipy.spatial import Voronoi, cKDTree
from shapely import contains_xy
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union


def resample(xy, step):
    """Points every `step` along a polyline (both ends kept); returns (points, chainage)."""
    xy = np.asarray(xy, dtype=np.float64)
    seg = np.hypot(*np.diff(xy, axis=0).T)
    keep = np.r_[True, seg > 1e-9]
    xy = xy[keep]
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    if len(xy) < 2 or s[-1] <= 0:
        return xy, s
    n = max(1, int(round(s[-1] / step)))
    si = np.linspace(0.0, s[-1], n + 1)
    return np.column_stack([np.interp(si, s, xy[:, 0]), np.interp(si, s, xy[:, 1])]), si


def normals(xy):
    """Unit left normals at each point (central differences)."""
    d = np.gradient(xy, axis=0)
    n = np.column_stack([-d[:, 1], d[:, 0]])
    return n / np.maximum(np.hypot(*n.T), 1e-12)[:, None]


def bend_radius(xy, s, span=10.0):
    """Horizontal radius at each point from the circle through the points `span` metres before and after."""
    r = np.full(len(xy), np.inf)
    for i in range(len(xy)):
        a = np.searchsorted(s, s[i] - span)
        b = min(len(xy) - 1, np.searchsorted(s, s[i] + span))
        if a >= i or b <= i:
            continue
        p, q, t = xy[a], xy[i], xy[b]
        ab, bc, ca = np.hypot(*(q - p)), np.hypot(*(t - q)), np.hypot(*(p - t))
        area2 = abs((q[0] - p[0]) * (t[1] - p[1]) - (q[1] - p[1]) * (t[0] - p[0]))
        if area2 > 1e-9:
            r[i] = ab * bc * ca / (2.0 * area2)
    return r


def smooth(v, sigma_pts):
    if sigma_pts <= 0 or len(v) < 3:
        return v
    return ndimage.gaussian_filter1d(v, sigma_pts, mode="nearest")


def as_polygons(geom):
    if geom.is_empty:
        return []
    return list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom] if isinstance(geom, Polygon) else \
        [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def area_of(prims):
    """The area the hatches / closed outlines of a set of primitives cover (one geometry), or None."""
    parts = [rings_to_polygons(p["rings"]) for p in prims if p["kind"] == "fill"]
    parts += [rings_to_polygons([p["xy"]]) for p in prims if p["kind"] == "poly" and p.get("closed") and len(p["xy"]) >= 3]
    parts = [g for g in parts if g is not None and not g.is_empty]
    return unary_union(parts).buffer(0.05).buffer(-0.05) if parts else None


def rings_to_polygons(rings, min_area=1.0):
    """Closed loops -> polygons, loops inside loops becoming holes (even/odd nesting)."""
    polys = sorted((Polygon(r).buffer(0) for r in rings if len(r) >= 3), key=lambda p: -p.area)
    polys = [p for p in polys if p.area >= min_area]
    out = []
    depth = [0] * len(polys)
    for i, p in enumerate(polys):
        for j in range(i):
            if polys[j].contains(p.representative_point()):
                depth[i] += 1
    for i, p in enumerate(polys):
        if depth[i] % 2:
            continue
        holes = [polys[j] for j in range(len(polys)) if depth[j] == depth[i] + 1 and p.contains(polys[j].representative_point())]
        out.append(p.difference(unary_union(holes)) if holes else p)
    return unary_union(out) if out else Polygon()


# --------------------------------------------------------------------------- skeleton
def _prune(adj, v, prune):
    """Remove side branches shorter than `prune` (a leaf up to the first junction), repeatedly."""
    changed = True
    while changed:
        # all short branches of this round first, then remove them together: at a dead end both corner branches
        # go, instead of one of them becoming part of the centre line
        doomed = []
        for leaf in [k for k, nb in adj.items() if len(nb) == 1]:
            path, length, prev, cur = [leaf], 0.0, None, leaf
            while True:
                nxt = [x for x in adj[cur] if x != prev]
                if not nxt:
                    break
                length += float(np.hypot(*(v[nxt[0]] - v[cur])))
                prev, cur = cur, nxt[0]
                path.append(cur)
                if len(adj[cur]) != 2:
                    break
            if len(adj[cur]) >= 3 and length < prune:
                doomed.append(path)
        for path in doomed:
            for a, b in zip(path[:-1], path[1:]):
                adj[a].discard(b)
                adj[b].discard(a)
        changed = bool(doomed)


def skeleton(area, step=1.0, prune=10.0):
    """Centre lines of a street area: the inner Voronoi edges of its densified boundary, as a graph.

    Returns (nodes (K, 2), edges [list of node-index chains]) with the short side branches (area corners, < prune m)
    removed. Chains run between ends and junctions; loops (roundabouts) come out as a chain that starts and ends on
    the same junction."""
    pts = []
    for poly in as_polygons(area):
        for ring in [poly.exterior] + list(poly.interiors):
            line = LineString(ring.coords)
            n = max(4, int(line.length / step))
            pts.append(np.array([line.interpolate(t, normalized=True).coords[0] for t in np.linspace(0, 1, n, endpoint=False)]))
    pts = np.vstack(pts)
    vor = Voronoi(pts)
    v = vor.vertices
    inside = contains_xy(area, v[:, 0], v[:, 1])
    adj = defaultdict(set)
    for a, b in vor.ridge_vertices:
        if a >= 0 and b >= 0 and inside[a] and inside[b]:
            if LineString([v[a], v[b]]).within(area):
                adj[a].add(b)
                adj[b].add(a)
    _prune(adj, v, prune)
    adj = {k: nb for k, nb in adj.items() if nb}
    # chains between key nodes (degree != 2)
    key = {k for k, nb in adj.items() if len(nb) != 2}
    seen, chains = set(), []
    for k in key:
        for nb in adj[k]:
            if (k, nb) in seen:
                continue
            chain, prev, cur = [k], k, nb
            seen.add((k, nb))
            while cur not in key:
                chain.append(cur)
                nxt = [x for x in adj[cur] if x != prev]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
            chain.append(cur)
            seen.add((cur, prev))
            chains.append(chain)
    # pure loops without any junction (an isolated ring)
    rest = set(adj) - {c for ch in chains for c in ch}
    while rest:
        start = rest.pop()
        chain, prev, cur = [start], None, start
        while True:
            nxt = [x for x in adj[cur] if x != prev and (x in rest or x == start)]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            chain.append(cur)
            if cur == start:
                break
            rest.discard(cur)
        if len(chain) > 3:
            chains.append(chain)
    return v, chains


def boundary_tree(area, step=0.5):
    pts = []
    for poly in as_polygons(area):
        for ring in [poly.exterior] + list(poly.interiors):
            line = LineString(ring.coords)
            n = max(4, int(line.length / step))
            pts.append(np.array([line.interpolate(t, normalized=True).coords[0] for t in np.linspace(0, 1, n, endpoint=False)]))
    return cKDTree(np.vstack(pts))


def strip_polygon(xy, half_w):
    """The area within half_w (per point) of a centre line, as one polygon."""
    n = normals(xy)
    left = xy + n * half_w[:, None]
    right = xy - n * half_w[:, None]
    ring = np.vstack([left, right[::-1]])
    poly = Polygon(ring).buffer(0)
    if not poly.is_valid or poly.is_empty:
        poly = LineString(xy).buffer(float(np.median(half_w)), cap_style=2)
    return poly
