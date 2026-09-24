"""Buildings and trees from the drawing, with heights from what the drawing, OpenStreetMap and the project documents say.

Footprints: the outlines on the building layers are joined into closed faces (a DWG often holds buildings as loose
line segments), faces smaller than min_area_m2 or larger than max_area_m2 are left out.

Existing buildings: a face is a building when OpenStreetMap has a building over at least osm_min_cover of it; its
height is OSM's 'height', else 'building:levels' x storey height, else the usual number of storeys of its OSM type.
A face OSM does not know is kept when most of its outline is free (a building OSM misses), and dropped when it is
enclosed by other faces (a courtyard).

Proposed buildings: architects draw a building's shadow as its footprint slid along one direction by a length
proportional to its height (the sun at a fixed angle). The shadow layers are read that way:
  direction  the edges of the shadow outlines that are not parallel to the footprints' sides
  length     each shadow's edges along that direction
  caster     the footprint faces whose slid copy runs into that shadow
  storeys    the lengths are whole multiples of one step (the shadow of one storey): the largest step that makes every
             shadow but at most one a whole number of storeys, within the drawing's precision (step_tolerance_m);
             storeys = length / step. A step and its half both fit when every building happens to have an even number
             of storeys; one shadow of an odd number (two, in a large set) decides for the half
The project documents' above-ground floor area (programme table), when given, chooses among a step and its multiples
and is compared with footprint x storeys as a check.
"""
import math

import numpy as np
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

OSM_TYPE_STOREYS = {"house": 2, "detached": 2, "semidetached_house": 2, "terrace": 2, "bungalow": 1, "garage": 1,
                    "garages": 1, "shed": 1, "carport": 1, "hut": 1, "kiosk": 1, "retail": 1, "service": 1,
                    "roof": 1, "industrial": 2, "warehouse": 1, "church": 3, "school": 3, "apartments": 5,
                    "residential": 5, "office": 5, "commercial": 3, "hotel": 6, "university": 4, "hospital": 5}


# --------------------------------------------------------------------------- footprints
def faces_of(prims, min_area, max_area):
    """Closed faces of the outlines (closed polylines, loose segments and fill borders), largest first."""
    lines = []
    for p in prims:
        if p["kind"] == "poly" and len(p["xy"]) >= 2:
            xy = np.vstack([p["xy"], p["xy"][:1]]) if p.get("closed") else p["xy"]
            lines.append(LineString(xy))
        elif p["kind"] == "fill":
            lines += [LineString(np.vstack([r, r[:1]])) for r in p["rings"] if len(r) >= 3]
    if not lines:
        return []
    faces = [f for f in polygonize(unary_union(lines)) if min_area <= f.area <= max_area]
    return sorted((orient(f.buffer(0), 1.0) if not f.is_valid else orient(f, 1.0) for f in faces),
                  key=lambda f: -f.area)


def shared_boundary(faces, tol=0.2):
    """Share of each face's outline that runs along another face."""
    tree = STRtree(faces)
    out = []
    for i, f in enumerate(faces):
        others = [faces[j] for j in tree.query(f.buffer(tol)) if j != i]
        if not others:
            out.append(0.0)
            continue
        near = f.exterior.intersection(unary_union([o.buffer(tol) for o in others]))
        out.append(float(near.length) / max(f.exterior.length, 1e-6))
    return out


def _float(v):
    try:
        return float(str(v).split(";")[0].replace("m", "").strip())
    except (TypeError, ValueError):
        return None


def osm_height(tags, storey):
    """(height m, storeys, source) from OSM tags, or (None, None, None)."""
    h = _float(tags.get("height"))
    lv = _float(tags.get("building:levels"))
    if h and 2 <= h <= 400:
        return h, lv or max(1, round(h / storey)), "OSM height"
    if lv and 1 <= lv <= 120:
        roof = _float(tags.get("roof:levels")) or 0
        return (lv + roof) * storey, lv + roof, "OSM levels"
    return None, None, None


def existing_buildings(faces, osm_polys, b):
    """[dict(poly, storeys, height_m, source, osm_type)] for the existing building faces."""
    storey = float(b["existing_storey_m"])
    tree = STRtree([p for p, _ in osm_polys]) if osm_polys else None
    shared = shared_boundary(faces)
    out, dropped = [], 0
    for f, sh in zip(faces, shared):
        best, cover = None, 0.0
        if tree is not None:
            hits = [osm_polys[j] for j in tree.query(f)]
            if hits:
                cover = sum(f.intersection(p).area for p, _ in hits) / f.area
                best = max(hits, key=lambda h: f.intersection(h[0]).area)
        if cover >= float(b["osm_min_cover"]):
            tags = best[1]
            h, n, src = osm_height(tags, storey)
            if h is None:
                n = OSM_TYPE_STOREYS.get(tags.get("building"), int(b["existing_default_storeys"]))
                h, src = n * storey, f"usual for OSM type '{tags.get('building')}' (assumed)"
            out.append({"poly": f, "storeys": n, "height_m": h, "source": src, "osm_type": tags.get("building")})
        elif sh < float(b["courtyard_shared"]):
            n = int(b["existing_default_storeys"])
            out.append({"poly": f, "storeys": n, "height_m": n * storey, "source": "not in OSM (assumed)",
                        "osm_type": None})
        else:
            dropped += 1
    return out, dropped


# --------------------------------------------------------------------------- shadows -> storeys
def _angles(polys, min_len=0.3):
    rows = []
    for g in polys:
        for ring in [g.exterior] + list(g.interiors):
            c = np.asarray(ring.coords)
            d = np.diff(c, axis=0)
            L = np.hypot(*d.T)
            rows += [(math.degrees(math.atan2(dy, dx)) % 180.0, l) for (dx, dy), l in zip(d, L) if l > min_len]
    return np.array(rows).reshape(-1, 2)


def _adiff(a, b):
    return np.abs((np.asarray(a) - b + 90.0) % 180.0 - 90.0)


def shadow_direction(faces, shadows):
    """Direction (degrees, mod 180) of the shadow sweep: the strongest edge direction of the shadow outlines that is
    not a side direction of the footprints."""
    fa, sa = _angles(faces), _angles(shadows)
    if not len(fa) or not len(sa):
        return None
    h, e = np.histogram(fa[:, 0], bins=180, range=(0, 180), weights=fa[:, 1])
    sides = [e[np.argmax(h)] + 0.5]
    sides.append((sides[0] + 90.0) % 180.0)
    diag = sa[(_adiff(sa[:, 0], sides[0]) > 8) & (_adiff(sa[:, 0], sides[1]) > 8)]
    if not len(diag):
        return None
    h2, e2 = np.histogram(diag[:, 0], bins=180, range=(0, 180), weights=diag[:, 1])
    k = int(np.argmax(h2))
    sel = _adiff(diag[:, 0], e2[k] + 0.5) < 2.0
    return float(np.average(diag[sel, 0], weights=diag[sel, 1]))


def _sweep(f, v):
    """The area a polygon covers when slid by vector v (its Minkowski sum with the segment 0-v): the polygon, its
    moved copy, and the band every edge sweeps."""
    parts = [f, translate(f, v[0], v[1])]
    for ring in [f.exterior] + list(f.interiors):
        c = np.asarray(ring.coords)
        for a, b in zip(c[:-1], c[1:]):
            q = Polygon([tuple(a), tuple(b), (b[0] + v[0], b[1] + v[1]), (a[0] + v[0], a[1] + v[1])])
            if q.area > 1e-9:
                parts.append(q if q.is_valid else q.buffer(0))
    return unary_union(parts)


def shadow_lengths(faces, shadows, direction):
    """For every face that casts one of the shadows: (face index, sweep length m, shadow index)."""
    d = np.array([math.cos(math.radians(direction)), math.sin(math.radians(direction))])
    U = unary_union(faces)
    tree = STRtree(faces)
    best = {}
    for si, sp in enumerate(shadows):
        c = np.asarray(sp.exterior.coords)
        dd = np.diff(c, axis=0)
        L = np.hypot(*dd.T)
        ang = np.degrees(np.arctan2(dd[:, 1], dd[:, 0])) % 180.0
        par = (_adiff(ang, direction) < 3.0) & (L > 0.2)
        if not par.any():
            continue
        length = float(np.median(L[par]))
        zone, room = sp.buffer(0.3), sp.union(U).buffer(0.3)
        for j in tree.query(sp.buffer(0.5)):
            f = faces[j]
            for sgn in (1.0, -1.0):
                v = sgn * length * d
                extra = _sweep(f, v).difference(f)
                if extra.area < 1e-6:
                    continue
                hit = extra.intersection(zone).area / extra.area
                fits = extra.intersection(room).area / extra.area
                if fits >= 0.9 and hit >= 0.25 and hit > best.get(j, (0, 0, 0))[0]:
                    best[j] = (hit, length, si)
    return [(j, length, si) for j, (hit, length, si) in best.items()]


def step_fit(lengths, q, max_storeys=80):
    """Share of the lengths that are (nearly) whole multiples of q (soft: 1 on the multiple, 0 at 0.25 away)."""
    n = np.asarray(lengths, dtype=np.float64) / q
    err = np.abs(n - np.round(n))
    ok = (np.round(n) >= 1) & (np.round(n) <= max_storeys)
    return float(np.mean(np.exp(-(err / 0.08) ** 2) * ok))


def misfits(lengths, q, tol=0.15):
    """Lengths that are not a whole number (at least 1) of steps q, within tol metres (at most a quarter step)."""
    L = np.asarray(lengths, dtype=np.float64)
    n = np.maximum(1.0, np.round(L / q))
    return np.abs(L - n * q) > min(tol, q / 4.0)


def whole_share(lengths, q, tol=0.15):
    """Share of the lengths that are a whole number of steps q (see misfits)."""
    return float(1.0 - misfits(lengths, q, tol).mean()) if len(lengths) else 0.0


def storey_step(lengths, tol=0.15, min_step=0.3, max_storeys=80):
    """The shadow of one storey. First the step whose multiples fit the lengths best (soft score, the largest such
    step when several fit alike); then of it, twice it, a half and a third: the largest that makes every length but
    at most one (one slip in ten or more) a whole number of steps within tol metres (at most a quarter step),
    refined to the least-squares step of the lengths that fit. Returns (step, share of the lengths that fit) or
    (None, 0). A half step always fits even storey counts: storey_aliases() lists the alternatives, so the documents'
    floor area can decide when it is known."""
    L = np.asarray(lengths, dtype=np.float64)
    L = L[L > 0.05]
    if len(L) < 3:
        return None, 0.0
    qs = np.arange(0.1, float(L.max()) + 1e-9, 0.002)
    scores = np.array([step_fit(L, q, max_storeys) for q in qs])
    q0 = float(qs[scores >= scores.max() - 0.02].max())
    allowed = 1 if len(L) >= 10 else 0
    for f in (2.0, 1.0, 0.5, 1.0 / 3.0):
        q = q0 * f
        if q < min_step or L.max() / q > max_storeys:
            continue
        bad = misfits(L, q, tol)
        if bad.sum() <= allowed:
            n = np.maximum(1.0, np.round(L[~bad] / q))
            q = float(np.dot(L[~bad], n) / np.dot(n, n))
            return q, whole_share(L, q, tol)
    return q0, whole_share(L, q0, tol)


def storey_aliases(lengths, q, min_fit=0.6):
    """q, q/2, q/3 and 2q, where they still make most lengths whole: [(step, share that fits)]."""
    out = []
    for f in (1.0, 0.5, 1.0 / 3.0, 2.0):
        s = whole_share(lengths, q * f)
        if s >= min_fit or f == 1.0:
            out.append((q * f, s))
    return out


# --------------------------------------------------------------------------- trees
def trees_of(prims, b, dedupe=0.6):
    """(x, y, crown radius m) of the tree symbols: circles, and small round fills."""
    pts = []
    for p in prims:
        if p["kind"] == "circle":
            pts.append((float(p["c"][0]), float(p["c"][1]), float(p["r"])))
        elif p["kind"] == "fill":
            for r in p["rings"]:
                if len(r) < 3:
                    continue
                g = Polygon(r)
                if not g.is_valid or g.area < 0.3 or g.area > 150:
                    continue
                roundness = 4 * math.pi * g.area / max(g.length ** 2, 1e-9)
                if roundness >= 0.6:
                    pts.append((g.centroid.x, g.centroid.y, math.sqrt(g.area / math.pi)))
    if not pts:
        return np.zeros((0, 3))
    a = np.array(pts)
    a = a[np.argsort(-a[:, 2])]  # the biggest symbol of a tree first (the crown, not the trunk dot)
    from scipy.spatial import cKDTree
    keep = np.ones(len(a), bool)
    tree = cKDTree(a[:, :2])
    for i in range(len(a)):
        if keep[i]:
            for j in tree.query_ball_point(a[i, :2], max(dedupe, 0.5 * a[i, 2])):
                if j != i:
                    keep[j] = False
    a = a[keep]
    lo, hi = float(b["tree_min_crown_m"]), float(b["tree_max_crown_m"])
    return a[(a[:, 2] >= lo) & (a[:, 2] <= hi)]
