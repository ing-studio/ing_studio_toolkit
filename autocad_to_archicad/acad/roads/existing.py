"""Existing streets: OpenStreetMap centre lines, moved and widened to the drawing's kerb lines, on the terrain.

OSM gives where the streets are and what they are (class, lanes, width, one-way). Only streets on the ground are
taken: tunnels, covered passages and bridges are left out. The drawing's kerb lines give the exact edges: at every
station a ray is cast to the left and to the right; where both hit a kerb at a plausible width the centre is moved to
the middle and the width taken from the kerbs; in between the measurements are interpolated and smoothed, and without
any the OSM line and a width from its tags / class are kept. The profile follows the terrain along the street,
smoothed (existing.smoothing_m), with the usual cross fall.
"""
import numpy as np
from scipy import ndimage
from shapely import STRtree
from shapely.geometry import LineString
from shapely.ops import unary_union

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


def build(ways, to_drawing, kerb_lines, terrain, cfg, clip_area):
    """Existing streets as edges (xy, s, half_w, z, ground, kind, name, cls, snapped share)."""
    ex, prof = cfg["roads"]["existing"], cfg["roads"]["profile"]
    step = float(prof["station_m"])
    z_arr, gt = terrain
    segs = kerb_segments(kerb_lines)
    reach = float(ex["kerb_search_m"])
    sig = float(ex["smoothing_m"]) / step / 2.0
    edges = []
    for w in ways:
        tags = w["tags"]
        if tags.get("highway") not in ex["osm_classes"] or tags.get("area") == "yes":
            continue
        if any(tags.get(k, "no") != "no" for k in ("tunnel", "covered", "bridge")) or (_float(tags.get("layer")) or 0) != 0:
            continue  # under the ground, under a building or on a bridge: not a street on the terrain
        xy = to_drawing(w["lonlat"])
        line = LineString(xy)
        if not line.intersects(clip_area):
            continue
        part = line.intersection(clip_area.buffer(reach))
        pieces = [part] if part.geom_type == "LineString" else [g for g in getattr(part, "geoms", []) if g.geom_type == "LineString"]
        for piece in pieces:
            if piece.length < 2 * step:
                continue
            pts, s = resample(np.asarray(piece.coords), step)
            n = normals(pts)
            w_def, w_src = default_width(tags, cfg)
            left = ray_hits(pts, n, reach, segs)
            right = ray_hits(pts, -n, reach, segs)
            with np.errstate(invalid="ignore"):  # no kerb on a side: inf - inf
                width = left + right
                good = np.isfinite(width) & (width >= 0.6 * w_def) & (width <= 2.2 * w_def + 2.0) & \
                    (np.abs(left - right) / 2.0 <= 0.5 * w_def + 2.0)
            share = float(good.mean())
            if good.sum() >= 3 and share >= 0.25:
                shift = np.where(good, (left - right) / 2.0, np.nan)
                wid = np.where(good, width, np.nan)
                idx = np.arange(len(pts))
                shift = np.interp(idx, idx[good], shift[good])
                wid = np.interp(idx, idx[good], wid[good])
                shift = smooth(ndimage.median_filter(shift, 5, mode="nearest"), sig)
                wid = smooth(ndimage.median_filter(wid, 5, mode="nearest"), sig)
                pts = pts + n * shift[:, None]
                src = "kerbs"
            else:
                wid = np.full(len(pts), w_def)
                src = w_src
            hw = wid / 2.0
            # ground: median across the carriageway at each station, then smoothed along the street
            across = np.stack([sample_raster(z_arr, gt, pts + n * (f * hw)[:, None]) for f in (-0.6, -0.3, 0.0, 0.3, 0.6)])
            g = np.nanmedian(np.where(np.isfinite(across), across, np.nan), axis=0) if np.isfinite(across).any() else \
                np.full(len(pts), np.nan)
            ok = np.isfinite(g)
            if ok.sum() < 2:
                continue
            idx = np.arange(len(pts))
            g = np.interp(idx, idx[ok], g[ok])
            # the median across a crowned surface lies ~0.3 half widths below the crown
            z = smooth(g, sig) + float(prof["carriageway_crossfall_permille"]) / 1000.0 * 0.3 * hw
            edges.append({"xy": pts, "s": s, "half_w": hw, "z": z, "ground": g, "kind": "existing",
                          "cls": tags["highway"], "name": tags.get("name:en") or tags.get("name") or "",
                          "osm_id": w["id"], "width_source": src, "kerb_share": round(share, 2),
                          "oneway": tags.get("oneway") in ("yes", "1", "-1")})
    area = unary_union([strip_polygon(e["xy"], e["half_w"]) for e in edges]) if edges else None
    if area is not None:
        area = area.intersection(clip_area)
    return edges, area
