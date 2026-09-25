"""Stage earthworks: the street surfaces, and the terrain made to fit them (terrain grid, drawing metres, altitudes).

The paving is one connected network:
  existing streets   OSM streets joined into one network, fitted to the kerbs, on their smoothed ground profile
  new carriageways   the drawing's carriageway along the new axes, and where it joins a street within
                     roads.profile.paving_reach_m of a street's edge and joining it takes little earthwork
                     (paving_max_cut_fill_m): junction aprons, the roundabout, driveways, lay-bys; where it only
                     covers an existing street, that street stays
  new sidewalks      the drawing's sidewalks along the streets
ALL carriageways, old and new, share ONE surface: a point takes the height of the centre line nearest to it (existing
and new streets alike), interpolated along that line (not the nearest station), crowned by the cross fall and blended
where streets meet, so new streets run into the old ones without a step. Along its own axes (half width + 1 m) a
new street keeps its designed surface, whatever runs beside it. Gaps narrower than roads.profile.close_gaps_m between
paved pieces (medians, strips between a new and an old street) are paved too. Paving beyond a street's edge (aprons,
driveways) leaves the edge at its height and follows the ground within roads.profile.paving_max_grade_permille.
A sidewalk is a kerb height above the carriageway beside it (its new street's, else the existing street's), rising
gently away from it. Each surface is smoothed a little (roads.profile.surface_smoothing_m); the kerb between a
carriageway and its sidewalk stays sharp. Where streets side by side lie on clearly different levels, the paving
between them would be steeper than roads.profile.paving_max_slope_permille: that strip is ground instead, shaped like
the ground beside any paving (below).

Layering (the Archicad file is built the same way): every paved surface is a body lying ON the terrain. The terrain
under a carriageway = its surface - pavement_m, under a sidewalk = its surface - kerb - pavement_m, so the ground runs
on under the kerb without a step. Around the paving the ground meets the paved edge flush:
  new streets       side slopes (roads.earthworks, horizontal:vertical) from the edge until they meet the ground: cut
                    where the ground is higher, fill where it is lower. Where a slope would run further than
                    max_daylight_m, stops at an existing street with a step, or clashes with another street's slope, a
                    retaining wall is needed (reported and drawn). A street standing more than max_fill_m above the
                    ground is a bridge: the ground stays as it is under it
  existing streets  the ground beside them is eased onto their edge within existing.edge_blend_m (no new walls)
  buildings         the ground under the buildings (buildings.json) stays as it is; slopes stop at their walls
Paved parts that join no street or lie farther from one (a parking lot on its own, plazas) stay drawn in 2D on the
existing ground.
Results: terrain_design.tif, cutfill.tif, surfaces.npz (surfaces and masks), walls.npy, earthworks.json (volumes,
walls, bridges, and the paved areas as polygons: the Archicad bodies are exactly these)."""
import json
import math

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely import STRtree, contains_xy, points
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import unary_union

from ..config import settings
from ..geometry.raster import read_raster, sample_raster, write_raster
from ..roads.geometry import as_polygons, strip_polygon
from ..roads.network import RoadNet
from ..util import file_signature, load_json, log, save_json, skip, warn

SLIVER_M = 0.8        # paving narrower than this (a sliver between two cuts) is not built
MIN_PIECE_M2 = 5.0    # nor a paved piece smaller than this
HOLE_M2 = 10.0        # holes in the paving smaller than this are paved over (buildings are larger: min_area_m2)
MIN_STEP_M2 = 25.0    # a level step in the paving smaller than this is a steep spot of a junction, not two levels
MIN_WALL_M = 4.0      # a retaining wall run shorter than this is a raster speck, not a wall


def mask_of(geom, X, Y):
    if geom is None or geom.is_empty:
        return np.zeros(X.shape, bool)
    return contains_xy(geom, X, Y)


def mask_polygon(mask, gt):
    """The cells of a mask as one (multi)polygon."""
    from osgeo import gdal, ogr
    ds = gdal.GetDriverByName("MEM").Create("", mask.shape[1], mask.shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    band = ds.GetRasterBand(1)
    band.WriteArray(mask.astype(np.uint8))
    vds = ogr.GetDriverByName("MEM").CreateDataSource("m")
    lyr = vds.CreateLayer("m", geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, band, lyr, 0)
    return unary_union([shape(json.loads(f.GetGeometryRef().ExportToJson())) for f in lyr if f.GetField("v") == 1])


def _clean(geom, min_area=1.0):
    parts = [p for p in as_polygons(geom.buffer(0)) if p.area >= min_area] if geom is not None else []
    return unary_union(parts) if parts else None


def smooth_region(mask, gt):
    """The cells of a mask as a polygon without the cells' staircase or a ragged threshold edge: closed over 1 m (bits
    a cell or two apart are one region), its outline simplified within 0.5 m (a region cut from the paving leaves a
    clean edge, not a saw)."""
    g = mask_polygon(mask, gt)
    return g.buffer(1.0, join_style=1).buffer(-1.0, join_style=1).simplify(0.5)


def tidy(geom, sliver_m=SLIVER_M, min_area=MIN_PIECE_M2):
    """Paving fit to build: slivers narrower than sliver_m (left by cuts between areas) and pieces smaller than
    min_area dropped; small holes (a cell or two left between areas, not a building) filled."""
    if geom is None:
        return None
    r = sliver_m / 2.0
    g = geom.buffer(-r, join_style=2, mitre_limit=2.0).buffer(r, join_style=2, mitre_limit=2.0)
    parts = []
    for p in as_polygons(g.intersection(geom)):
        if p.area >= min_area:
            parts.append(Polygon(p.exterior, [h for h in p.interiors if Polygon(h).area >= HOLE_M2]))
    return _clean(unary_union(parts)) if parts else None


def strips(edges, extra):
    """The area within half width + extra of a set of centre lines."""
    return unary_union([strip_polygon(e["xy"], e["half_w"] + extra) for e in edges])


def paved_areas(roads, pr, net, outline, band, reach):
    """The paved areas the model is built from: {existing, carriageway, sidewalks, loose} (shapely or None).
    In this order: the drawing's carriageway along a new street axis (within its half width + 1 m) is new carriageway;
    an existing street stays one where the drawing's carriageway merely covers it; the drawing's carriageway joining
    either and within `reach` of a street's edge is paving too (junction aprons, the roundabout, driveways, lay-bys);
    sidewalks count along a street (within its half width + `band`). The rest (a parking lot on its own, plazas) is
    'loose' and stays on the existing ground."""
    g = lambda k: shape(roads[k]) if roads.get(k) else None
    car, sw, ex = g("carriageway_area"), g("sidewalk_area"), g("existing_area")
    loose = []
    if pr.edges and car is not None:
        keep = car.intersection(strips(pr.edges, 1.0))
        rest = car.difference(keep)
        if ex is not None:
            rest = rest.difference(ex)
        near = rest.intersection(strips(net.edges, reach))
        base = unary_union([a for a in (keep, ex) if a is not None]).buffer(0.3)
        joined = [q for q in as_polygons(near) if q.intersects(base)]
        loose.append(rest.difference(unary_union(joined)) if joined else rest)
        car = unary_union([keep] + joined)
        if sw is not None:
            along = sw.intersection(strips(net.edges, band + 1.0)).difference(car)
            loose.append(sw.difference(along).difference(car))
            sw = along
    elif car is not None or sw is not None:
        loose += [a for a in (car, sw) if a is not None]
        car = sw = None
    new = [a for a in (car, sw) if a is not None and not a.is_empty]
    if ex is not None and new:
        ex = ex.difference(unary_union(new))
    loose = [q for q in loose if q is not None and not q.is_empty]
    out = {"existing": ex, "carriageway": car, "sidewalks": sw, "loose": unary_union(loose) if loose else None}
    return {k: _clean(v.intersection(outline)) if v is not None else None for k, v in out.items()}


def close_gaps(areas, width, outline, blds):
    """Gaps narrower than `width` between paved pieces (a median, the strip between a new street and an old one, a
    sliver left by a cut) become paving too: existing street beside existing streets (a median), else new carriageway
    (which must fit the ground like an apron); the drawing's paving found unfit to build (loose) is not taken again.
    Returns (areas, the gaps closed). Where the two sides lie on levels the paving cannot join, the surface check turns
    the strip into ground again."""
    kinds = [k for k in ("existing", "carriageway", "sidewalks") if areas.get(k) is not None]
    if not kinds or width <= 0:
        return areas, None
    paved = unary_union([areas[k] for k in kinds])
    r = width / 2.0
    gaps = paved.buffer(r, join_style=2, mitre_limit=2.0).buffer(-r, join_style=2, mitre_limit=2.0).difference(paved)
    if blds is not None:
        gaps = gaps.difference(blds.buffer(0.1))
    if areas.get("loose") is not None:  # the drawing's paving found unfit to build (a verge on a slope) stays so
        gaps = gaps.difference(areas["loose"].buffer(0.1))
    gaps = gaps.intersection(outline)
    # only gaps between paving (paving along most of their edge: a median, a strip between two streets), not a notch
    # in the paving's outer edge that is open to the terrain
    rim = paved.buffer(0.05)
    parts = [g for g in as_polygons(gaps) if g.area >= 0.5 and g.boundary.intersection(rim).length >= 0.6 * g.length]
    if not parts:
        return areas, None
    # a gap beside an existing street is existing street (a median); one beside new paving is new carriageway (it
    # must still fit the ground like an apron, else it stays ground)
    add = {k: [] for k in kinds}
    news = [areas[k] for k in ("carriageway", "sidewalks") if areas.get(k) is not None]
    new = unary_union(news) if news else None
    for g in parts:
        edge = g.boundary
        on_ex = edge.intersection(areas["existing"].buffer(0.05)).length if areas.get("existing") is not None else 0.0
        on_new = edge.intersection(new.buffer(0.05)).length if new is not None else 0.0
        k = "existing" if on_ex >= on_new else "carriageway"
        add.setdefault(k, []).append(g)
    out = dict(areas)
    for k, gs in add.items():
        if gs:
            out[k] = _clean(unary_union([a for a in [areas.get(k)] + gs if a is not None]))
    # a gap given to one kind is not also another's
    if out.get("carriageway") is not None and out.get("sidewalks") is not None:
        out["sidewalks"] = _clean(out["sidewalks"].difference(out["carriageway"]))
    new = [out[k] for k in ("carriageway", "sidewalks") if out.get(k) is not None]
    if out.get("existing") is not None and new:
        out["existing"] = _clean(out["existing"].difference(unary_union(new)))
    return out, unary_union(parts)


def trimmed(edges, cover):
    """Streets with the stretches under `cover` cut out (an old street the new design paves over no longer shapes the
    surface there); heights, widths and stations interpolated at the cuts."""
    if cover is None or cover.is_empty:
        return edges
    out = []
    for e in edges:
        line = LineString(e["xy"])
        if not line.intersects(cover):
            out.append(e)
            continue
        rest = line.difference(cover)
        for piece in [rest] if rest.geom_type == "LineString" else [g for g in getattr(rest, "geoms", [])
                                                                     if g.geom_type == "LineString"]:
            if piece.length < 1.0:
                continue
            c = np.asarray(piece.coords)
            s_ = np.array([line.project(Point(q)) for q in c])
            f = dict(e)
            f["xy"], f["s"] = c, s_
            for k in ("z", "half_w", "ground"):
                if k in e:
                    f[k] = np.interp(s_, e["s"], e[k])
            out.append(f)
    return out


def carriageway_z(net, xy, ground, grade):
    """The carriageway surface of a street network (crowned, blended at junctions); beyond a street's edge (aprons,
    driveways) it leaves the edge at its height and follows the ground within `grade`."""
    z = net.surface_z(xy)
    p = net.project(xy)
    off = np.maximum(p["d"] - p["hw"], 0.0)
    return z + np.clip(np.nan_to_num(ground(xy) - z), -grade * off, grade * off)


def sidewalk_z(net, xy, kerb, cf_sw, max_rise_run=10.0):
    """Sidewalk surface: kerb height above the carriageway edge, rising away from it (drains to the kerb)."""
    cf = net.crossfall
    return net.blended(xy, lambda z, d, hw: z - cf * hw + kerb + cf_sw * np.clip(d - hw, 0.0, max_rise_run))


def surface_on(fn, mask, X, Y, sigma_px, ring=2):
    """A paved surface: fn(xy) (or fn(xy, rows, cols)) at the cells of `mask` and a ring of `ring` cells around it (so
    it can be sampled up to its edge), smoothed within them (normalised Gaussian, sigma in cells); NaN elsewhere."""
    top = np.full(mask.shape, np.nan)
    if not mask.any():
        return top
    M = ndimage.binary_dilation(mask, iterations=ring)
    rr, cc = np.nonzero(M)
    top[rr, cc] = fn(np.column_stack([X[rr, cc], Y[rr, cc]]), rr, cc)
    if sigma_px > 0:
        w = ndimage.gaussian_filter(M.astype(np.float64), sigma_px)
        v = ndimage.gaussian_filter(np.where(M, top, 0.0), sigma_px)
        top[M] = (v / np.maximum(w, 1e-9))[M]
    return top


def side_slopes(shape_, rr, cc, seg, top, res, reach, fill_hv, cut_hv):
    """Envelope of the side slopes of every street stretch. rr, cc: the street cells that shape the ground, seg: the
    stretch each belongs to (pieces of segment_m of one centre line, computed together so the legs of a serpentine
    stay apart); top: the finished surface there. Returns (lowest allowed = highest fill slope, highest allowed =
    lowest cut slope, and the fill / cut slope and distance of the nearest stretch) per cell; NaN / inf beyond every
    stretch's reach."""
    lo = np.full(shape_, -np.inf)
    hi = np.full(shape_, np.inf)
    near_d = np.full(shape_, np.inf)
    near_lo = np.full(shape_, np.nan)
    near_hi = np.full(shape_, np.nan)
    pad = int(np.ceil(reach / res)) + 1
    for sid in np.unique(seg):
        sel = seg == sid
        r0, r1 = max(0, rr[sel].min() - pad), min(shape_[0], rr[sel].max() + pad + 1)
        c0, c1 = max(0, cc[sel].min() - pad), min(shape_[1], cc[sel].max() + pad + 1)
        m = np.zeros((r1 - r0, c1 - c0), bool)
        m[rr[sel] - r0, cc[sel] - c0] = True
        dist, (ri, ci) = ndimage.distance_transform_edt(~m, return_indices=True)
        dd = dist * res
        h = top[r0:r1, c0:c1][ri, ci]
        inside = (dd <= reach) & ~m & np.isfinite(h)
        fl = np.where(inside, h - dd / fill_hv, -np.inf)
        cl = np.where(inside, h + dd / cut_hv, np.inf)
        win = (slice(r0, r1), slice(c0, c1))
        lo[win] = np.maximum(lo[win], fl)
        hi[win] = np.minimum(hi[win], cl)
        closer = inside & (dd < near_d[win])
        near_d[win] = np.where(closer, dd, near_d[win])
        near_lo[win] = np.where(closer, fl, near_lo[win])
        near_hi[win] = np.where(closer, cl, near_hi[win])
    near_d[~np.isfinite(near_d)] = np.nan
    return lo, hi, near_lo, near_hi, near_d


def smooth_change(dz, M, dist, reach, sigma_px=2.0, exact_m=1.0):
    """The change of the ground dz within M smoothed (normalised Gaussian over M), easing in from the exact value at
    the paving's edge to fully smoothed exact_m away from it."""
    change = np.where(M, np.nan_to_num(dz), 0.0)
    wgt = ndimage.gaussian_filter(M.astype(np.float64), sigma_px)
    sm = ndimage.gaussian_filter(change, sigma_px) / np.maximum(wgt, 1e-6)
    fade = np.clip(np.nan_to_num(dist, nan=reach) / exact_m, 0.0, 1.0)
    return (1.0 - fade) * change + fade * sm


def cliffs(z, z_before, area, jump):
    """Cells where the new surface jumps by more than `jump` to a neighbour, and by clearly more than the ground did
    before (a retaining wall the redesign needs), within `area`."""
    out = np.zeros(z.shape, bool)
    for axis in (0, 1):
        dz = np.abs(np.diff(z, axis=axis))
        d0 = np.abs(np.diff(z_before, axis=axis))
        big = (np.nan_to_num(dz) > jump) & (np.nan_to_num(dz) > np.nan_to_num(d0) + 0.3)
        if axis == 0:
            out[:-1] |= big
        else:
            out[:, :-1] |= big
    return out & area


def wall_segments(wall, X, Y, z1, res, seg_m, footing):
    """Retaining walls as straight pieces: the wall cells of each connected run, ordered along the run, cut every
    seg_m; each piece's top / bottom = the highest / lowest finished ground around it (bottom minus the footing)."""
    lab, n = ndimage.label(wall, structure=np.ones((3, 3)))
    zmax = ndimage.maximum_filter(np.nan_to_num(z1, nan=-1e9), size=5)
    zmin = -ndimage.maximum_filter(np.nan_to_num(-z1, nan=-1e9), size=5)
    out = []
    per = max(2, int(round(seg_m / res)))
    for k in range(1, n + 1):
        rr, cc = np.nonzero(lab == k)
        if len(rr) < 3:
            continue
        pts = np.column_stack([X[rr, cc], Y[rr, cc]])
        # order the cells along the run: start at the cell farthest from the middle, then always the nearest next
        tree = cKDTree(pts)
        start = int(np.argmax(np.hypot(*(pts - pts.mean(axis=0)).T)))
        order, used = [start], np.zeros(len(pts), bool)
        used[start] = True
        for _ in range(len(pts) - 1):
            d, idx = tree.query(pts[order[-1]], k=min(12, len(pts)))
            nxt = next((int(i) for dd, i in zip(np.atleast_1d(d), np.atleast_1d(idx)) if not used[i] and dd <= 3 * res), None)
            if nxt is None:
                rest = np.nonzero(~used)[0]
                if not len(rest):
                    break
                nxt = int(rest[np.argmin(np.hypot(*(pts[rest] - pts[order[-1]]).T))])
                if np.hypot(*(pts[nxt] - pts[order[-1]])) > 3 * res:  # a separate piece of the same component
                    order.append(-1)
            order.append(nxt)
            used[nxt] = True
        runs, cur = [], []
        for i in order:
            if i < 0:
                runs.append(cur)
                cur = []
            else:
                cur.append(i)
        runs.append(cur)
        for run in runs:
            if len(run) < 2 or len(run) * res < MIN_WALL_M:  # a speck of cliff cells, not a wall
                continue
            # the run's path eased over about 2 m: the wall follows the cliff, not the cells' staircase
            path = pts[run]
            k_ = min(len(run), max(1, int(round(2.0 / res))) | 1)
            if k_ > 1:
                pad = np.pad(path, ((k_ // 2, k_ // 2), (0, 0)), mode="edge")
                path = np.column_stack([np.convolve(pad[:, j], np.ones(k_) / k_, mode="valid") for j in (0, 1)])
                path[0], path[-1] = pts[run[0]], pts[run[-1]]
            ends = list(range(0, len(run) - 1, per)) + [len(run) - 1]
            ps = []
            for a, b in zip(ends[:-1], ends[1:]):
                piece = run[a:b + 1]
                if np.hypot(*(path[b] - path[a])) < 0.5 * res:
                    continue
                ps.append((path[a], path[b], float(np.max(zmax[rr[piece], cc[piece]])),
                           float(np.min(zmin[rr[piece], cc[piece]]))))
            if not ps:
                continue
            # neighbouring pieces' tops and bottoms eased (never below the ground they hold): no saw along the wall
            top = np.array([p[2] for p in ps])
            bot = np.array([p[3] for p in ps])
            if len(ps) > 2:
                top = np.maximum(top, np.convolve(np.pad(top, 1, mode="edge"), np.ones(3) / 3, mode="valid"))
                bot = np.minimum(bot, np.convolve(np.pad(bot, 1, mode="edge"), np.ones(3) / 3, mode="valid"))
            for (p0, p1, _, _), t, b in zip(ps, top, bot):
                if t - b < 0.3:
                    continue
                out.append({"xy": [p0.round(3).tolist(), p1.round(3).tolist()], "top": round(float(t), 2),
                            "bottom": round(float(b) - footing, 2), "height_m": round(float(t - b), 2)})
    return out


def bridge_stretches(net, bridge, gt, clearance):
    """Stretches of the new streets over a bridge / viaduct: [{street, from_m, to_m, length_m, max_height_m}]."""
    out = []
    H, W = bridge.shape
    for e in net.edges:
        c = ((e["xy"][:, 0] - gt[0]) / gt[1]).astype(int)
        r = ((e["xy"][:, 1] - gt[3]) / gt[5]).astype(int)
        ok = (r >= 0) & (r < H) & (c >= 0) & (c < W)
        on = np.zeros(len(e["xy"]), bool)
        on[ok] = bridge[r[ok], c[ok]]
        start = None
        for i in range(len(on) + 1):
            if i < len(on) and on[i] and start is None:
                start = i
            if (i == len(on) or not on[i]) and start is not None:
                j = i - 1
                if e["s"][j] - e["s"][start] >= 5.0:
                    h = clearance[r[start:j + 1].clip(0, H - 1), c[start:j + 1].clip(0, W - 1)]
                    out.append({"street": e.get("name"), "from_m": round(float(e["s"][start]), 1),
                                "to_m": round(float(e["s"][j]), 1), "length_m": round(float(e["s"][j] - e["s"][start]), 1),
                                "max_height_m": round(float(np.nanmax(h)), 1)})
                start = None
    return out


def run(job, force=False):
    cfg = job.cfg
    out_json, out_tif = job.w("earthworks.json"), job.w("terrain_design.tif")
    roads, bj, ter = load_json(job.w("roads.json")), load_json(job.w("buildings.json")), load_json(job.w("terrain.json"))
    if not roads or bj is None or not ter:
        raise RuntimeError("run the terrain, buildings and roads stages first")
    wanted = {"roads": file_signature(job.w("roads.json")), "terrain": file_signature(job.w("terrain_existing.tif")),
              "buildings": file_signature(job.w("buildings.json")),
              **settings(cfg, "roads.earthworks", "roads.profile", "roads.existing.edge_blend_m",
                         "roads.proposed.sidewalk_band_m")}
    prev = load_json(out_json) or {}
    if not force and prev.get("inputs") == wanted and out_tif.exists() and job.w("surfaces.npz").exists():
        skip(f"earthworks: already done (cut {prev['cut_m3']:,.0f} m3, fill {prev['fill_m3']:,.0f} m3)")
        return
    prof, ew = cfg["roads"]["profile"], cfg["roads"]["earthworks"]
    band = float(cfg["roads"]["proposed"]["sidewalk_band_m"])
    cf, cf_sw = float(prof["carriageway_crossfall_permille"]) / 1000.0, float(prof["sidewalk_crossfall_permille"]) / 1000.0
    kerb, pav = float(prof["kerb_m"]), float(prof["pavement_m"])
    fill_hv, cut_hv = float(ew["fill_slope_h_per_v"]), float(ew["cut_slope_h_per_v"])
    z0, gt, _ = read_raster(job.w("terrain_existing.tif"))
    res = gt[1]
    H, W = z0.shape
    X, Y = np.meshgrid(gt[0] + (np.arange(W) + 0.5) * res, gt[3] - (np.arange(H) + 0.5) * res)
    valid = np.isfinite(z0)
    blend = float(prof["junction_blend_m"])
    ex = RoadNet.from_json(roads["existing"], None, cf, blend)
    pr = RoadNet.from_json(roads["proposed"], None, cf, blend)
    net = RoadNet(ex.edges + pr.edges, None, cf, blend)  # every street: one carriageway surface

    # ---- the paved areas and their surfaces
    areas = paved_areas(roads, pr, net, shape(ter["outline"]), band, float(prof["paving_reach_m"]))
    # where the new streets pave over an old one, the old centre line no longer counts
    new = [areas[k] for k in ("carriageway", "sidewalks") if areas[k] is not None]
    if new and ex.edges:
        net = RoadNet(trimmed(ex.edges, unary_union(new)) + pr.edges, None, cf, blend)
    blds = [shape(it["polygon"]) for k in ("existing", "proposed") for it in bj[k]]
    BLD = mask_of(unary_union(blds), X, Y) if blds else np.zeros(z0.shape, bool)
    # narrow gaps between the paved pieces are closed: the paving is one piece
    areas, gaps = close_gaps(areas, float(prof["close_gaps_m"]), shape(ter["outline"]),
                             unary_union(blds) if blds else None)
    GAP = mask_of(gaps, X, Y) & ~BLD
    EX = mask_of(areas["existing"], X, Y) & ~BLD if net.edges else np.zeros(z0.shape, bool)
    CAR = mask_of(areas["carriageway"], X, Y) & ~BLD
    g_pave = float(prof["paving_max_grade_permille"]) / 1000.0
    # what paving beyond a street's edge runs towards: the ground, or for a building's access its ground floor
    target = z0.copy()
    ground = lambda xy: sample_raster(target, gt, xy)
    # aprons (the drawing's carriageway beyond the new axes) only where the ground lets them join the street: where
    # that would take more than paving_max_cut_fill_m of cut / fill (an embankment, a plaza on a slope) they stay 2D.
    # An apron reaching a building (a driveway, a garage entrance: up to access_max_m2) is its access and stays: it
    # runs from the street towards the building's ground floor at the paving grade, walls beside it if need be
    AXES = CAR & mask_of(strips(pr.edges, 1.0), X, Y) if pr.edges else np.zeros(z0.shape, bool)
    AP = CAR & ~AXES
    ACCESS = np.zeros(z0.shape, bool)
    if AP.any():
        items = [it for k in ("existing", "proposed") for it in bj[k]]
        lab, n = ndimage.label(AP)
        at_bld = np.unique(lab[AP & ndimage.binary_dilation(BLD, iterations=max(1, int(round(2.0 / res))))])
        sizes = ndimage.sum(AP, lab, np.arange(n + 1)) * res * res
        ACCESS = np.isin(lab, [k for k in at_bld if k > 0 and sizes[k] <= float(prof["access_max_m2"])])
        if ACCESS.any() and items:
            rr, cc = np.nonzero(ACCESS)
            tree = STRtree([shape(it["polygon"]) for it in items])
            near = tree.query_nearest(points(np.column_stack([X[rr, cc], Y[rr, cc]])), all_matches=False)[1]
            target[rr, cc] = [items[int(k)]["ground_floor_z"] for k in near]
        rr, cc = np.nonzero(AP)
        xy = np.column_stack([X[rr, cc], Y[rr, cc]])
        fits = np.zeros(z0.shape, bool)
        fits[rr, cc] = np.abs(np.nan_to_num(ground(xy) - carriageway_z(net, xy, ground, g_pave))) <= \
            float(prof["paving_max_cut_fill_m"])
        fits |= ACCESS
        lab, _ = ndimage.label((AP & fits) | AXES | EX)
        joined = np.isin(lab, np.unique(lab[AXES | EX]))
        drop = AP & ~(fits & joined)
        if drop.any():
            gone = smooth_region(drop, gt)
            gone = gone.intersection(areas["carriageway"])
            areas["carriageway"] = _clean(areas["carriageway"].difference(gone))
            areas["loose"] = _clean(unary_union([a for a in (areas["loose"], gone) if a is not None]))
            CAR = mask_of(areas["carriageway"], X, Y) & ~BLD
    SW = mask_of(areas["sidewalks"], X, Y) & ~BLD & ~CAR
    EX &= ~(CAR | SW)
    LOOSE = mask_of(areas["loose"], X, Y) & ~BLD & ~(EX | CAR | SW)
    sig = float(prof["surface_smoothing_m"]) / res
    CARR = EX | CAR  # all carriageways: one surface
    if net.edges:
        # along its axes a new street has its designed surface, whatever runs beside it (smoothed only with itself);
        # the paving around it is smoothed towards it, so it joins its aprons and the streets it ties into
        raw = surface_on(lambda xy, *_: carriageway_z(net, xy, ground, g_pave), CARR, X, Y, 0.0)
        if AXES.any():
            rr, cc = np.nonzero(AXES)
            raw[rr, cc] = pr.surface_z(np.column_stack([X[rr, cc], Y[rr, cc]]))
        top_carr = surface_on(lambda xy, rr, cc: raw[rr, cc], CARR, X, Y, sig)
        if AXES.any():
            own = surface_on(lambda xy, *_: pr.surface_z(xy), AXES, X, Y, sig)
            top_carr[AXES] = own[AXES]
    else:
        top_carr = np.full(z0.shape, np.nan)
    # sidewalks: a kerb above the carriageway beside them (the new one within the sidewalk band, else the existing
    # street), rising away from it
    if CARR.any():
        def beside(M):
            if not M.any():
                return np.full(z0.shape, np.inf), np.full(z0.shape, np.nan)
            dist, (ri, ci) = ndimage.distance_transform_edt(~M, return_indices=True)
            return dist * res, np.where(M, top_carr, np.nan)[ri, ci]
        (d_car, z_car), (d_ex, z_ex) = beside(CAR), beside(EX)
        own = d_car <= band + 1.0
        dist, edge = np.where(own, d_car, d_ex), np.where(own, z_car, z_ex)
        raw_sw = surface_on(lambda xy, rr, cc: edge[rr, cc] + kerb + cf_sw * np.clip(dist[rr, cc] - 0.5 * res, 0.0, 10.0),
                            SW, X, Y, 0.0)
        if pr.edges:
            # along a new street its sidewalk follows that street (not an access or a neighbour beside it)
            ALONG = np.isfinite(raw_sw) & mask_of(strips(pr.edges, band + 1.0), X, Y)
            rr, cc = np.nonzero(ALONG)
            raw_sw[rr, cc] = sidewalk_z(pr, np.column_stack([X[rr, cc], Y[rr, cc]]), kerb, cf_sw)
        top_sw = surface_on(lambda xy, rr, cc: raw_sw[rr, cc], SW, X, Y, sig)
    else:
        top_sw = surface_on(lambda xy, *_: sidewalk_z(net, xy, kerb, cf_sw), SW, X, Y, sig) if net.edges else \
            np.full(z0.shape, np.nan)
    top_ex = top_car = top_carr  # one surface: the Archicad bodies of both kinds are cut from it
    # a level step inside the paving (streets side by side on clearly different levels, the paving between them
    # steeper than paving_max_slope_permille) is no paving but ground: between two paved levels a bank flush with both,
    # else shaped like any ground beside the paving (a wall where the levels are too close) (the new streets along
    # their axes always stay paving: their profile governs there)
    max_slope = float(prof["paving_max_slope_permille"]) / 1000.0

    def steep(top, M):
        gy, gx = np.gradient(np.where(M, top, np.nan), res)
        return M & ndimage.binary_dilation(np.nan_to_num(np.hypot(gx, gy)) > max_slope) & ~AXES
    BANK = steep(top_carr, CARR) | steep(top_sw, SW)
    # a steep spot smaller than MIN_STEP_M2 (where streets of slightly different heights blend at a junction) is no
    # second level: the paving stays whole there instead of getting a hole
    lab, n = ndimage.label(BANK)
    if n:
        size = ndimage.sum(BANK, lab, np.arange(n + 1)) * res * res
        BANK = np.isin(lab, np.nonzero(size >= MIN_STEP_M2)[0]) & BANK
    bank_top = np.where(CARR, top_carr, top_sw)
    if BANK.any():
        gone = smooth_region(BANK, gt)
        for k in ("existing", "carriageway", "sidewalks"):
            if areas[k] is not None:
                areas[k] = _clean(areas[k].difference(gone))
    # the paving as it is built: no slivers, specks or pinholes left by the cuts above (they show as noise in 3D)
    for k in ("existing", "carriageway", "sidewalks"):
        areas[k] = tidy(areas[k])
    was = CARR | SW
    EX = mask_of(areas["existing"], X, Y) & ~BLD
    CAR = mask_of(areas["carriageway"], X, Y) & ~BLD
    SW = mask_of(areas["sidewalks"], X, Y) & ~BLD & ~CAR
    EX &= ~(CAR | SW)
    CARR = EX | CAR
    BANK = was & ~(CARR | SW)
    # a filled pinhole takes its surface from around it
    for top, M in ((top_carr, CARR), (top_sw, SW)):
        hole = M & ~np.isfinite(top)
        if hole.any():
            ok_ = np.isfinite(top)
            idx = ndimage.distance_transform_edt(~ok_, return_distances=False, return_indices=True)
            top[hole] = top[idx[0][hole], idx[1][hole]]
    surf = np.full(z0.shape, np.nan)  # the finished paved surface
    surf[CARR] = top_carr[CARR]
    surf[SW] = top_sw[SW]
    PAVED = EX | CAR | SW
    z1 = z0.copy()
    z1[EX | CAR] = surf[EX | CAR] - pav
    z1[SW] = surf[SW] - kerb - pav  # the ground runs on under the kerb at the carriageway's bed
    # a level step with paving on both sides is a bank from one paving edge to the other, flush with both (the
    # surface between them, only too steep to pave); one with paving on one side only is ground like any other
    r_cells = max(1, int(round(float(prof["close_gaps_m"]) / 2.0 / res)))
    yy, xx = np.mgrid[-r_cells:r_cells + 1, -r_cells:r_cells + 1]
    # (a closed gap that turns out to be a level step was never paving: it stays the natural ground)
    BETWEEN = BANK & ~GAP & ndimage.binary_closing(PAVED | BLD, structure=(xx ** 2 + yy ** 2) <= r_cells ** 2) & \
        np.isfinite(bank_top)
    if ew.get("max_fill_m"):  # no bank higher than an embankment may be (under a viaduct the ground stays)
        BETWEEN &= np.nan_to_num(bank_top - z0, nan=0.0) <= float(ew["max_fill_m"])
    # the bank is the blend of two street levels, uneven where the blend gives up on one of them: smoothed (~1 m)
    wgt = ndimage.gaussian_filter(BETWEEN.astype(np.float64), 2.0)
    bank_sm = ndimage.gaussian_filter(np.where(BETWEEN, np.nan_to_num(bank_top), 0.0), 2.0) / np.maximum(wgt, 1e-6)
    z1[BETWEEN] = bank_sm[BETWEEN]

    # ---- new streets: bridges, side slopes, walls
    PR = CAR | SW
    bridge = np.zeros(z0.shape, bool)
    bridges, walls = [], {"cells": 0, "length_m": 0.0}
    near_d = np.full(z0.shape, np.nan)
    D = np.zeros(z0.shape, bool)
    if PR.any():
        # a street standing higher above the ground than an embankment should is a bridge / viaduct: the ground stays
        # as it is under it, the deck stands above it (no side slopes there)
        max_fill = ew.get("max_fill_m")
        if max_fill:
            high = PR & (np.nan_to_num(z1 - z0, nan=0.0) > float(max_fill))
            bridge = ndimage.binary_closing(high, iterations=2) & PR
            z1[bridge] = z0[bridge]
            bridges = bridge_stretches(pr, bridge, gt, surf - pav - z0)
        rr, cc = np.nonzero(PR & ~bridge)
        p = pr.project(np.column_stack([X[rr, cc], Y[rr, cc]]))
        seg = p["edge"].astype(np.int64) * 100000 + (p["s"] // float(ew["segment_m"])).astype(np.int64)
        reach = float(ew["max_daylight_m"])
        # the slopes start at the finished surface: the ground meets the paving's edge flush
        lo, hi, near_lo, near_hi, near_d = side_slopes(z0.shape, rr, cc, seg, surf, res, reach, fill_hv, cut_hv)
        D = ~PAVED & ~BETWEEN & ~BLD & valid & np.isfinite(near_d)
        both = D & (lo <= hi)  # every slope agrees: above all fill slopes, below all cut slopes
        z1[both] = np.clip(z0[both], lo[both], hi[both])
        clash = D & ~both  # slopes of two street stretches overlap: the nearer one wins, a wall between them
        z1[clash] = np.clip(z0[clash], near_lo[clash], near_hi[clash])
        # the nearest street cell jumps along a sloping street, and the distance to a staircase of cells swings by
        # half a cell along a slanting edge: both leave teeth in the side slopes. Smooth the change of the ground
        # (masked, ~1 m) up to a metre from the edge, so only real steps remain
        z1[D] = z0[D] + smooth_change(z1 - z0, D, near_d, reach)[D]
        # a retaining wall is needed where the slope has not met the ground at the end of its reach, where it
        # stops at an existing street with a step, and between street stretches whose slopes clash
        rim = D & (np.nan_to_num(near_d) > reach - 1.01 * res) & (np.abs(z1 - z0) > 0.3)  # one cell wide
        at_ex = D & ndimage.binary_dilation(EX) & (np.abs(z1 - z0) > 0.5)
        at_clash = cliffs(z1, z0, clash, 0.5)
        # a bridge ends at an abutment: the step between the deck's ground and the embankment beside it
        at_bridge = cliffs(z1, z0, ndimage.binary_dilation(bridge, iterations=2) & ~bridge & valid, 0.5) if bridge.any() \
            else np.zeros(z0.shape, bool)
        # between paving on clearly different levels (streets side by side)
        at_steps = cliffs(z1, z0, ndimage.binary_dilation(BANK, iterations=2) & ~PAVED & valid, 0.5) if BANK.any()             else np.zeros(z0.shape, bool)
        wall = rim | at_ex | at_clash | at_bridge | at_steps
        walls = {"cells": int(wall.sum()), "length_m": round(float(wall.sum()) * res, 1),
                 "at_reach_m": round(float(rim.sum()) * res), "at_existing_streets_m": round(float(at_ex.sum()) * res),
                 "between_streets_m": round(float(at_clash.sum()) * res), "at_bridges_m": round(float(at_bridge.sum()) * res),
                 "at_level_steps_m": round(float(at_steps.sum()) * res),
                 "clash_area_m2": round(float(clash.sum()) * res * res)}
        # beside a building the slope stops at its wall, which retains the step (no separate wall)
        at_bld = D & ndimage.binary_dilation(BLD) & (np.abs(z1 - z0) > 0.5)
        walls["at_buildings_m"] = round(float(at_bld.sum()) * res)
        np.save(job.w("walls.npy"), np.column_stack([X[wall], Y[wall], z1[wall], z0[wall]]))
        segs = wall_segments(wall, X, Y, z1, res, float(ew["wall_segment_m"]), float(ew["wall_footing_m"]))
        walls["segments"] = segs
        walls["modelled_m"] = round(sum(math.hypot(s["xy"][1][0] - s["xy"][0][0], s["xy"][1][1] - s["xy"][0][1])
                                        for s in segs), 1)
    else:
        np.save(job.w("walls.npy"), np.zeros((0, 4)))

    # ---- existing streets: the ground beside them eased onto their edge (where no new street shapes it)
    EB = np.zeros(z0.shape, bool)
    ease = float(cfg["roads"]["existing"]["edge_blend_m"])
    if EX.any() and ease > 0:
        dist, (ri, ci) = ndimage.distance_transform_edt(~EX, return_indices=True)
        dd = dist * res
        h = surf[ri, ci]
        EB = ~PAVED & ~BETWEEN & ~BLD & valid & ~np.isfinite(near_d) & (dd <= ease) & np.isfinite(h)
        target = np.clip(z0, h - dd / fill_hv, h + dd / cut_hv)
        z1[EB] = (z0 + (1.0 - dd / ease) * (target - z0))[EB]
        z1[EB] = z0[EB] + smooth_change(z1 - z0, EB, np.where(EB, dd, np.nan), ease)[EB]

    # ---- volumes (the regrading under and beside existing streets is kept apart: it is a surface fit, not works)
    dz = np.where(valid, z1 - z0, 0.0)
    area = res * res
    eased = float(np.abs(dz[EB]).sum() * area)
    dz_works = np.where(EX | EB, 0.0, dz)
    cut, fill = float(-dz_works[dz_works < 0].sum() * area), float(dz_works[dz_works > 0].sum() * area)
    write_raster(out_tif, z1, gt)
    write_raster(job.w("cutfill.tif"), np.where(valid, dz_works, np.nan), gt)
    f32 = lambda a: a.astype(np.float32)
    np.savez_compressed(job.w("surfaces.npz"), top_ex=f32(top_ex), top_car=f32(top_car), top_sw=f32(top_sw),
                        EX=EX, CAR=CAR, SW=SW, LOOSE=LOOSE, BLD=BLD, BRIDGE=bridge, BANK=BANK, gt=np.array(gt))
    bridge_area = mask_polygon(bridge, gt) if bridge.any() else None
    if bridges:
        warn("earthworks: bridges / viaducts where a street would stand more than "
             f"{ew['max_fill_m']} m above the ground: " + ", ".join(
                 f"{b['street']} {b['from_m']:.0f}-{b['to_m']:.0f} m (up to {b['max_height_m']:.0f} m high)" for b in bridges))
    if LOOSE.any():
        log(f"earthworks: {float(LOOSE.sum()) * area:,.0f} m2 of the drawing's paving joins no street, lies more than "
            f"{prof['paving_reach_m']} m beyond one or on a slope (plazas, parking, embankments): it stays drawn in 2D on "
            "the existing ground")
    if GAP.any():
        log(f"earthworks: {float(GAP.sum()) * area:,.0f} m2 of gaps narrower than {prof['close_gaps_m']} m between the "
            "paved pieces (medians, strips between new and old streets) closed with paving")
    if BANK.any():
        log(f"earthworks: {float(BANK.sum()) * area:,.0f} m2 between paving on clearly different levels (streets side by "
            f"side) would be steeper than {prof['paving_max_slope_permille']} per mille: ground there, sloped or walled "
            "like the ground beside any paving")
    geo = lambda g: mapping(g) if g is not None and not g.is_empty else None
    result = {"inputs": wanted, "cut_m3": round(cut), "fill_m3": round(fill), "balance_m3": round(fill - cut),
              "loose_paved_m2": round(float(LOOSE.sum()) * area),
              "max_cut_m": round(float(max(0.0, -dz_works.min())), 2), "max_fill_m": round(float(max(0.0, dz_works.max())), 2),
              "changed_area_m2": round(float((np.abs(dz_works) > 0.05).sum()) * area), "retaining_walls": walls,
              "bridges": bridges, "kept_under_buildings_m2": round(float(BLD.sum()) * area),
              "existing_edges_eased_m3": round(eased), "gaps_closed_m2": round(float(GAP.sum()) * area), "level_steps_m2": round(float(BANK.sum()) * area),
              "areas_m2": {"existing_streets": round(float(EX.sum()) * area), "carriageway": round(float(CAR.sum()) * area),
                           "sidewalks": round(float(SW.sum()) * area)},
              "paved": {k: geo(v) for k, v in areas.items()}, "bridge_area": geo(bridge_area)}
    log(f"earthworks: street surfaces: existing {result['areas_m2']['existing_streets']:,} m2, new carriageways "
        f"{result['areas_m2']['carriageway']:,} m2, sidewalks {result['areas_m2']['sidewalks']:,} m2 (continuous, smoothed "
        f"over {prof['surface_smoothing_m']} m); the terrain {pav} m below them ({kerb + pav:.2f} m under sidewalks)")
    log(f"earthworks: cut {cut:,.0f} m3, fill {fill:,.0f} m3 (balance {fill - cut:+,.0f} m3); deepest cut "
        f"{result['max_cut_m']} m, highest fill {result['max_fill_m']} m, {result['changed_area_m2'] / 1e4:.2f} ha changed")
    if walls["cells"]:
        warn(f"earthworks: retaining walls needed along about {walls['length_m']:,.0f} m (steps over 0.5 m where the side "
             f"slopes do not meet the ground within {ew['max_daylight_m']} m ({walls['at_reach_m']:,} m), run into an "
             f"existing street ({walls['at_existing_streets_m']:,} m), where two street stretches are too close for their "
             f"slopes ({walls['between_streets_m']:,} m), at bridge abutments ({walls['at_bridges_m']:,} m) and between "
             f"streets side by side on different levels ({walls['at_level_steps_m']:,} m))")
    if walls.get("at_buildings_m"):
        log(f"earthworks: the ground under the buildings is left as it is; beside them it changes by more than 0.5 m "
            f"along about {walls['at_buildings_m']:,} m (their walls retain it)")
    save_json(out_json, result)
