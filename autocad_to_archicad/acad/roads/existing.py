"""Existing streets: OpenStreetMap centre lines, moved and widened to the drawing's kerb lines, on the terrain, as one
connected network.

OSM gives where the streets are and what they are (class, lanes, width, one-way). Only streets on the ground are
taken: tunnels, covered passages and bridges are left out. OSM splits a street into many ways (wherever a tag
changes); they are joined into continuous chains first (at every node where just two ways meet), so a street is
fitted, profiled and drawn as one piece, without notches where its ways meet, and short links are kept.
The drawing's kerb lines give the exact edges: at every station a ray is cast to the left and to the right; where both
hit a kerb at a plausible width the centre is moved to the middle and the width taken from the kerbs; in between the
measurements are interpolated and smoothed, and without any the OSM line and a width from its tags / class are kept.
The profile keeps as close to the terrain along the street as a street can be (at most existing.max_grade_permille,
vertical curves no tighter than existing.min_vertical_radius_m; least absolute difference, so a slope or a wall the OSM
centre line strays onto does not pull it up or down), smoothed (existing.smoothing_m), with the usual cross fall;
stretches whose ground stays off it are reported. Under an OSM bridge the survey sees the deck, not the street: those
stations do not count, the street passes below within its rules.
Junctions: fitting moves each chain on its own, so at a junction the chains are brought together again: a street
ending on another one (a T) ends on that street's centre line at its height; streets ending together meet at their
mean position and height. The correction fades out over existing.junction_taper_m. The street area gets round ends
at junctions and rounded kerb returns (existing.kerb_return_m), so the paving is one piece there.
"""
import warnings

import numpy as np
from scipy import ndimage
from shapely import STRtree, distance, points
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, unary_union

from ..geometry.raster import sample_raster
from .geometry import normals, resample, smooth, strip_polygon


def _float(v):
    try:
        return float(str(v).split()[0].replace(",", "."))
    except (TypeError, ValueError):
        return None


def default_width(tags, cfg):
    ex = cfg["roads"]["existing"]
    w = _float(tags.get("width"))
    if w and 2.0 <= w <= 40.0:
        return w, "osm width"
    lanes = _float(tags.get("lanes"))
    if lanes and 1 <= lanes <= 10:
        return lanes * float(ex["osm_lane_m"]), "osm lanes"
    w = float(ex["osm_classes"][tags["highway"]])
    if tags.get("oneway") in ("yes", "1", "-1") and tags["highway"] not in ("service",):
        w = max(3.5, w / 2.0)
    return w, "class"


def ray_hits(origins, dirs, max_len, segs):
    """Distance along each ray to the first segment it crosses (inf when none within max_len)."""
    out = np.full(len(origins), np.inf)
    if not len(segs):
        return out
    rays = [LineString([o, o + d * max_len]) for o, d in zip(origins, dirs)]
    tree = STRtree([LineString([s[:2], s[2:]]) for s in segs])
    ri, si = tree.query(rays, predicate="intersects")
    if not len(ri):
        return out
    P, D = origins[ri], dirs[ri]
    A, B = segs[si, :2], segs[si, 2:]
    E = B - A
    den = D[:, 0] * E[:, 1] - D[:, 1] * E[:, 0]
    ok = np.abs(den) > 1e-12
    AP = A - P
    t = np.where(ok, (AP[:, 0] * E[:, 1] - AP[:, 1] * E[:, 0]) / np.where(ok, den, 1), np.inf)
    t[(t < 0.3)] = np.inf  # ignore hits at the start point itself
    np.minimum.at(out, ri, t)
    return out


def kerb_segments(lines):
    segs = [np.hstack([a, b]) for xy in lines for a, b in zip(xy[:-1], xy[1:]) if np.hypot(*(b - a)) > 1e-6]
    return np.array(segs) if segs else np.zeros((0, 4))


def on_ground(tags, classes):
    """An OSM way that is a street on the terrain (not a tunnel, covered passage or bridge)."""
    if tags.get("highway") not in classes or tags.get("area") == "yes":
        return False
    return not any(tags.get(k, "no") != "no" for k in ("tunnel", "covered", "bridge")) and \
        (_float(tags.get("layer")) or 0) == 0


def chains(lines):
    """OSM ways (LineStrings) joined into continuous chains wherever exactly two of them end at a node."""
    merged = linemerge(MultiLineString(lines))
    return list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]


def fit_to_kerbs(pts, n, w_def, segs, reach, sig):
    """Centre and width of a street from the kerb lines on both sides: (points, widths, source, share snapped)."""
    left = ray_hits(pts, n, reach, segs)
    right = ray_hits(pts, -n, reach, segs)
    with np.errstate(invalid="ignore"):  # no kerb on a side: inf - inf
        width, off = left + right, (left - right) / 2.0
        good = np.isfinite(width) & (width >= 0.6 * w_def) & (width <= 2.2 * w_def + 2.0) & \
            (np.abs(off) <= 0.5 * w_def + 2.0)
    share = float(good.mean())
    if good.sum() < 3 or share < 0.25:
        return pts, w_def.copy(), None, share
    idx = np.arange(len(pts))
    shift = np.interp(idx, idx[good], off[good])
    wid = np.interp(idx, idx[good], width[good])
    shift = smooth(ndimage.median_filter(shift, 5, mode="nearest"), sig)
    wid = smooth(ndimage.median_filter(wid, 5, mode="nearest"), sig)
    return pts + n * shift[:, None], wid, "kerbs", share


def bridge_decks(ways, to_drawing, region, cfg, margin):
    """Where OSM has a bridge (or a way above the ground: layer > 0) over the site: its deck's plan area, `margin`
    wider (the survey's terrain falls from a deck's edge over a few metres). The survey sees the deck there, not the
    street passing below it."""
    ex = cfg["roads"]["existing"]
    out = []
    for w in ways:
        t = w["tags"]
        if t.get("bridge", "no") == "no" and (_float(t.get("layer")) or 0) <= 0:
            continue
        xy = np.asarray(to_drawing(w["lonlat"]), dtype=np.float64)
        if len(xy) < 2:
            continue
        line = LineString(xy)
        if not line.intersects(region):
            continue
        width = default_width(t, cfg)[0] if t.get("highway") in ex["osm_classes"] else 4.0
        out.append(line.buffer(width / 2.0 + margin, cap_style=2))
    return unary_union(out) if out else None


def street_ground(z_arr, gt, pts, n, hw, shifts=(0.0, -0.5, 0.5, -1.0, 1.0), prefer=0.05):
    """The ground a street stands on at each station, and how far from level it is across the carriageway: (median
    height, height range) of samples across a carriageway's width, that band shifted up to one half width to either
    side where it is more level there (an OSM centre line a few metres off lies partly on the slope or the wall beside
    the street; shifting costs `prefer` m per half width)."""
    f = np.array([-0.6, -0.3, 0.0, 0.3, 0.6])
    best_g = np.full(len(pts), np.nan)
    best_r = np.full(len(pts), np.inf)
    best_c = np.full(len(pts), np.inf)
    for k in shifts:
        across = np.stack([sample_raster(z_arr, gt, pts + n * ((k + v) * hw)[:, None]) for v in f])
        with warnings.catch_warnings():  # stations off the terrain: all NaN
            warnings.simplefilter("ignore", RuntimeWarning)
            g = np.nanmedian(across, axis=0)
            r = np.nanmax(across, axis=0) - np.nanmin(across, axis=0)
        c = np.where(np.isfinite(r), r + prefer * abs(k) * 2.0, np.inf)
        if k == 0.0:
            best_g, best_r, best_c = g, np.where(np.isfinite(r), r, 0.0), c  # the line itself, even off the survey
            continue
        take = c < best_c
        best_g, best_r, best_c = np.where(take, g, best_g), np.where(take, r, best_r), np.where(take, c, best_c)
    return best_g, best_r


def street_profile(s, g, g_max, r_min, weight=None):
    """The height of an existing street along it: as close as it can be to the ground (least absolute difference, so
    ground the centre line strays onto - a slope beside the street, a wall, a gap in the survey - does not pull it),
    within what a street can do: |grade| <= g_max (one value, or one per station) and vertical curves no tighter than
    r_min. The grade limit gives way (at a high cost) only where the ground itself is steeper over a long stretch.
    weight: how much each station's ground counts (0 under a bridge: the street passes below within its rules)."""
    from scipy import sparse
    from scipy.optimize import linprog
    n = len(s)
    w = np.gradient(s) if n > 1 else np.ones(n)
    if weight is not None:
        w = w * np.asarray(weight, dtype=np.float64)
    if n < 3 or not (w > 0).any():
        return g.copy()
    # stations whose ground does not count are held, very lightly, to the straight line between those that do
    free = w <= 1e-3 * np.gradient(s)
    if free.any():
        idx = np.arange(n)
        g = np.where(free, np.interp(idx, idx[~free], g[~free]), g)
        w = np.where(free, 1e-3 * np.gradient(s), w)
    ds = np.maximum(np.diff(s), 1e-6)
    g_max = np.broadcast_to(np.asarray(g_max, dtype=np.float64), (n,))
    g_max = np.minimum(g_max[:-1], g_max[1:])  # per segment
    # unknowns: z (n), |z - g| (n), grade slack per segment (n - 1)
    rows, cols, vals, b = [], [], [], []

    def add(coefs, rhs):
        r = len(b)
        for c, v in coefs:
            rows.append(r)
            cols.append(c)
            vals.append(v)
        b.append(rhs)
    for i in range(n):
        add([(i, 1.0), (n + i, -1.0)], g[i])
        add([(i, -1.0), (n + i, -1.0)], -g[i])
    for i in range(n - 1):
        add([(i + 1, 1.0), (i, -1.0), (2 * n + i, -ds[i])], g_max[i] * ds[i])
        add([(i + 1, -1.0), (i, 1.0), (2 * n + i, -ds[i])], g_max[i] * ds[i])
    for i in range(1, n - 1):
        c = [(i + 1, 1.0 / ds[i]), (i, -1.0 / ds[i] - 1.0 / ds[i - 1]), (i - 1, 1.0 / ds[i - 1])]
        dm = 0.5 * (ds[i] + ds[i - 1])
        add(c, dm / r_min)
        add([(k, -v) for k, v in c], dm / r_min)
    N = 3 * n - 1
    cost = np.r_[np.zeros(n), w, 1e4 * ds]
    A = sparse.csr_matrix((vals, (rows, cols)), shape=(len(b), N))
    res = linprog(cost, A_ub=A, b_ub=np.array(b), bounds=[(None, None)] * n + [(0, None)] * (2 * n - 1),
                  method="highs")
    return res.x[:n] if res.status == 0 else g.copy()


def off_ground(e, limit, min_len):
    """Stretches of a street at least min_len long whose ground (along its centre line) lies more than `limit` above
    or below it: there the centre line runs beside the real street (a slope, a wall) or the survey has a gap."""
    d = e["ground"] - e["z"]
    bad = (np.abs(d) > limit) & ~e["under"] & e["measured"]
    out, start = [], None
    for i in range(len(bad) + 1):
        if i < len(bad) and bad[i] and start is None:
            start = i
        if (i == len(bad) or not bad[i]) and start is not None:
            a, b = e["s"][start], e["s"][i - 1]
            if b - a >= min_len:
                k = start + int(np.argmax(np.abs(d[start:i])))
                out.append({"street": e["name"] or e["cls"], "osm_id": e["osm_id"], "from_m": round(float(a), 1),
                            "to_m": round(float(b), 1), "ground_minus_street_m": round(float(d[k]), 2),
                            "at": np.round(e["xy"][k], 1).tolist()})
            start = None
    return out


def taper(e, end, dxy, dz, length):
    """Move one end of a street by (dxy, dz), the change fading out linearly over `length` along it."""
    s = e["s"] if end == 0 else e["s"][-1] - e["s"]
    w = np.clip(1.0 - s / max(min(length, float(e["s"][-1])), 1e-6), 0.0, 1.0)
    e["xy"] = e["xy"] + w[:, None] * np.asarray(dxy)[None, :]
    e["z"] = e["z"] + w * dz


def join_junctions(edges, border, tol=0.5, length=20.0):
    """Bring the chains together again at their junctions (after each was fitted on its own). e['line0']: its OSM
    centre line (resampled). Returns the junctions [(point, half widths of the street ends there, largest half width
    there, the streets meeting there)]."""
    lines0 = [LineString(e["line0"]) for e in edges]
    tree = STRtree(lines0)
    groups, tees = {}, []
    for i, e in enumerate(edges):
        for k in (0, 1):
            p = Point(e["line0"][0 if k == 0 else -1])
            if border.distance(p) < 0.01:
                continue  # cut at the edge of the site: not a junction
            near = [int(j) for j in tree.query(p, predicate="dwithin", distance=tol) if int(j) != i]
            hosts = [j for j in near
                     if min(Point(lines0[j].coords[0]).distance(p), Point(lines0[j].coords[-1]).distance(p)) > tol]
            if hosts:
                tees.append((i, k, max(hosts, key=lambda j: float(np.max(edges[j]["half_w"])))))
            elif near:
                groups.setdefault((round(p.x / tol), round(p.y / tol)), []).append((i, k))
    out = []
    # ends meeting at a node: to their mean position and height
    for members in groups.values():
        if len(members) < 2:
            continue
        at = np.mean([edges[i]["xy"][0 if k == 0 else -1] for i, k in members], axis=0)
        zt = float(np.mean([edges[i]["z"][0 if k == 0 else -1] for i, k in members]))
        for i, k in members:
            e = edges[i]
            j = 0 if k == 0 else -1
            taper(e, k, at - e["xy"][j], zt - e["z"][j], length)
        hws = [float(edges[i]["half_w"][0 if k == 0 else -1]) for i, k in members]
        out.append((at, hws, max(hws), sorted({i for i, _ in members})))
    # a street ending on another: on its centre line, at its height
    for i, k, h in tees:
        e, host = edges[i], edges[h]
        j = 0 if k == 0 else -1
        line = LineString(host["xy"])
        s = line.project(Point(e["xy"][j]))
        at = np.asarray(line.interpolate(s).coords[0])
        chain = np.r_[0.0, np.cumsum(np.hypot(*np.diff(host["xy"], axis=0).T))]
        zt = float(np.interp(s, chain, host["z"]))
        taper(e, k, at - e["xy"][j], zt - e["z"][j], length)
        out.append((at, [float(e["half_w"][j])], max(float(e["half_w"][j]), float(np.interp(s, chain, host["half_w"]))),
                    [i, h]))
    return out


def build(ways, to_drawing, kerb_lines, terrain, cfg, clip_area):
    """Existing streets as edges (xy, s, half_w, z, ground, kind, name, cls, snapped share) and their area.
    Returns (edges, area, {chains, junctions})."""
    ex, prof = cfg["roads"]["existing"], cfg["roads"]["profile"]
    step = float(prof["station_m"])
    z_arr, gt = terrain
    segs = kerb_segments(kerb_lines)
    reach = float(ex["kerb_search_m"])
    sig = float(ex["smoothing_m"]) / step / 2.0
    grades, r_min = ex["max_grade_permille"], float(ex["min_vertical_radius_m"])
    grade_of = lambda tags: float(grades.get(tags["highway"], grades["default"])) / 1000.0
    level_tol = float(ex["level_across_m"])
    region = clip_area.buffer(reach)
    lines, tags_of = [], []
    for w in ways:
        if not on_ground(w["tags"], ex["osm_classes"]):
            continue
        xy = np.asarray(to_drawing(w["lonlat"]), dtype=np.float64)
        if len(xy) < 2:
            continue
        line = LineString(xy)
        if line.length > 0.1 and line.distance(region) < 200.0:
            lines.append(line)
            tags_of.append(dict(w["tags"], _id=w["id"]))
    if not lines:
        return [], None, {"chains": 0, "junctions": 0, "off_ground": [], "under_bridges_m": 0}
    decks = bridge_decks(ways, to_drawing, region, cfg, float(ex["bridge_margin_m"]))
    way_tree = STRtree(lines)
    edges = []
    for chain in chains(lines):
        part = chain.intersection(region)
        pieces = [part] if part.geom_type == "LineString" else \
            [g for g in getattr(part, "geoms", []) if g.geom_type == "LineString"]
        for piece in pieces:
            if piece.length < 1.0:
                continue
            pts, s = resample(np.asarray(piece.coords), step)
            if len(pts) < 2:
                continue
            # each station takes the width of the OSM way it lies on; the street, the tags of its longest way
            src = way_tree.query_nearest(points(pts), all_matches=False)[1]
            w_def = np.array([default_width(tags_of[int(j)], cfg)[0] for j in src])
            t_main = tags_of[int(np.bincount(src).argmax())]
            n = normals(pts)
            pts0 = pts.copy()
            pts, wid, w_src, share = fit_to_kerbs(pts, n, w_def, segs, reach, sig)
            hw = wid / 2.0
            g, spread = street_ground(z_arr, gt, pts, n, hw)
            ok = np.isfinite(g)
            if not ok.any():
                continue
            idx = np.arange(len(pts))
            g = np.interp(idx, idx[ok], g[ok])
            # under a bridge (the carriageway touching its deck) the survey's "ground" is the deck: it does not count
            under = distance(decks, points(pts)) <= hw if decks is not None else np.zeros(len(pts), bool)
            g_max = np.array([grade_of(tags_of[int(j)]) for j in src])
            # a street is level across: where the ground across the carriageway is not, the centre line lies on a
            # slope or a wall beside the real street, and that ground counts little; off the survey the ground is
            # carried on from its edge and holds the street lightly
            level = 1.0 / (1.0 + (np.maximum(np.nan_to_num(spread) - level_tol, 0.0) / level_tol) ** 2)
            weight = np.where(under, 0.0, np.where(ok, level, 0.1))
            # the median across a crowned surface lies ~0.3 half widths below the crown
            z = smooth(street_profile(s, g, g_max, r_min, weight), sig) + \
                float(prof["carriageway_crossfall_permille"]) / 1000.0 * 0.3 * hw
            edges.append({"xy": pts, "s": s, "half_w": hw, "z": z, "ground": g, "kind": "existing",
                          "cls": t_main["highway"], "name": t_main.get("name:en") or t_main.get("name") or "",
                          "osm_id": t_main["_id"], "width_source": w_src or default_width(t_main, cfg)[1],
                          "kerb_share": round(share, 2), "oneway": t_main.get("oneway") in ("yes", "1", "-1"),
                          "line0": pts0, "under": under, "measured": ok})
    junctions = join_junctions(edges, region.boundary, length=float(ex["junction_taper_m"]))
    strays = [x for e in edges for x in off_ground(e, float(ex["off_ground_m"]), 2.0 * step)]
    under_m = sum(float(np.sum(np.gradient(e["s"])[e["under"]])) for e in edges if len(e["s"]) > 1)
    for e in edges:
        for k in ("line0", "under", "measured"):
            e.pop(k)
    strips =[strip_polygon(e["xy"], e["half_w"]) for e in edges]
    area = unary_union(strips) if edges else None
    if area is not None and junctions:
        # round ends where streets meet, and rounded kerb returns in the corners between the streets meeting there
        # (only those: a street passing nearby is not joined to them)
        r = float(ex["kerb_return_m"])
        extra = [Point(at).buffer(h) for at, hws, _, _ in junctions for h in hws]
        if r > 0:
            for at, hws, hw, members in junctions:
                zone = Point(at).buffer(hw + r + 2.0)
                local = unary_union([strips[i].intersection(zone) for i in members] +
                                    [Point(at).buffer(h) for h in hws])
                extra.append(local.buffer(r, quad_segs=8).buffer(-r, quad_segs=8).intersection(zone))
        area = unary_union([area] + extra)
    if area is not None:
        area = area.intersection(clip_area)
    return edges, area, {"chains": len(edges), "junctions": len(junctions), "off_ground": strays,
                         "under_bridges_m": round(under_m)}
