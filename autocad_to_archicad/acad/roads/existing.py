"""Existing streets: OpenStreetMap centre lines, moved and widened to the drawing's kerb lines, on the terrain, as one
connected network.

OSM gives where the streets are and what they are (class, lanes, width, one-way). Only streets on the ground are
taken: tunnels, covered passages and bridges are left out. OSM splits a street into many ways (wherever a tag
changes); they are joined into continuous chains first (at every node where just two ways meet), so a street is
fitted, profiled and drawn as one piece, without notches where its ways meet, and short links are kept.
The drawing's kerb lines give the exact edges: at every station a ray is cast to the left and to the right; where both
hit a kerb at a plausible width the centre is moved to the middle and the width taken from the kerbs; in between the
measurements are interpolated and smoothed, and without any the OSM line and a width from its tags / class are kept.
The profile follows the terrain along the street, smoothed (existing.smoothing_m), with the usual cross fall.
Junctions: fitting moves each chain on its own, so at a junction the chains are brought together again: a street
ending on another one (a T) ends on that street's centre line at its height; streets ending together meet at their
mean position and height. The correction fades out over existing.junction_taper_m. The street area gets round ends
at junctions and rounded kerb returns (existing.kerb_return_m), so the paving is one piece there.
"""
import warnings

import numpy as np
from scipy import ndimage
from shapely import STRtree, points
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
        return [], None, {"chains": 0, "junctions": 0}
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
            # ground: median across the carriageway at each station, then smoothed along the street
            across = np.stack([sample_raster(z_arr, gt, pts + n * (f * hw)[:, None]) for f in (-0.6, -0.3, 0.0, 0.3, 0.6)])
            with warnings.catch_warnings():  # stations off the terrain: all NaN
                warnings.simplefilter("ignore", RuntimeWarning)
                g = np.nanmedian(np.where(np.isfinite(across), across, np.nan), axis=0)
            ok = np.isfinite(g)
            if not ok.any():
                continue
            idx = np.arange(len(pts))
            g = np.interp(idx, idx[ok], g[ok])
            # the median across a crowned surface lies ~0.3 half widths below the crown
            z = smooth(g, sig) + float(prof["carriageway_crossfall_permille"]) / 1000.0 * 0.3 * hw
            edges.append({"xy": pts, "s": s, "half_w": hw, "z": z, "ground": g, "kind": "existing",
                          "cls": t_main["highway"], "name": t_main.get("name:en") or t_main.get("name") or "",
                          "osm_id": t_main["_id"], "width_source": w_src or default_width(t_main, cfg)[1],
                          "kerb_share": round(share, 2), "oneway": t_main.get("oneway") in ("yes", "1", "-1"),
                          "line0": pts0})
    junctions = join_junctions(edges, region.boundary, length=float(ex["junction_taper_m"]))
    for e in edges:
        e.pop("line0")
    strips = [strip_polygon(e["xy"], e["half_w"]) for e in edges]
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
    return edges, area, {"chains": len(edges), "junctions": len(junctions)}
