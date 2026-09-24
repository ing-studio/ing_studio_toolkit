"""Stage earthworks: the street surfaces, and the terrain made to fit them (terrain grid, drawing metres, altitudes).

The street surfaces, one per kind of paving, each continuous and smooth:
  existing streets   OSM centre lines fitted to the kerbs, on their smoothed ground profile (roads stage)
  new carriageways   on the designed profile, crowned (the cross fall falls to both kerbs)
  new sidewalks      a kerb height above the carriageway edge, rising gently away from it
A point takes the height of the centre line nearest to it, interpolated along that line (not the nearest station), and
each surface is smoothed a little (roads.profile.surface_smoothing_m) so junctions and tight bends have no steps; the
kerb between a carriageway and its sidewalk stays sharp.

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
Paved areas no street axis runs through (ramps, parking, driveways) stay drawn in 2D on the existing ground.
Results: terrain_design.tif, cutfill.tif, surfaces.npz (surfaces and masks), walls.npy, earthworks.json (volumes,
walls, bridges, and the paved areas as polygons: the Archicad bodies are exactly these)."""
import json
import math

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely import contains_xy
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ..config import settings
from ..geometry.raster import read_raster, write_raster
from ..roads.geometry import as_polygons, strip_polygon
from ..roads.network import RoadNet
from ..util import file_signature, load_json, log, save_json, skip, warn


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


def paved_areas(roads, pr, band, outline):
    """The paved areas the model is built from: {existing, carriageway, sidewalks, loose} (shapely or None). A new
    carriageway / sidewalk counts only along a street axis (within its half width + 1 m, sidewalks + band); what no
    axis runs through (ramps, parking, driveways) is 'loose' and stays on the existing ground."""
    g = lambda k: shape(roads[k]) if roads.get(k) else None
    car, sw, ex = g("carriageway_area"), g("sidewalk_area"), g("existing_area")
    loose = []
    if pr.edges:
        if car is not None:
            keep = car.intersection(unary_union([strip_polygon(e["xy"], e["half_w"] + 1.0) for e in pr.edges]))
            loose.append(car.difference(keep))
            car = keep
        if sw is not None:
            keep = sw.intersection(unary_union([strip_polygon(e["xy"], e["half_w"] + band + 1.0) for e in pr.edges]))
            if car is not None:
                keep = keep.difference(car)
            loose.append(sw.difference(keep))
            sw = keep
    else:
        loose += [a for a in (car, sw) if a is not None]
        car = sw = None
    new = [a for a in (car, sw) if a is not None and not a.is_empty]
    if ex is not None and new:
        ex = ex.difference(unary_union(new))
    out = {"existing": ex, "carriageway": car, "sidewalks": sw, "loose": unary_union(loose) if loose else None}
    return {k: _clean(v.intersection(outline)) if v is not None else None for k, v in out.items()}


def sidewalk_z(net, xy, kerb, cf_sw, max_rise_run=10.0):
    """Sidewalk surface: kerb height above the carriageway edge, rising away from it (drains to the kerb)."""
    cf = net.crossfall
    return net.blended(xy, lambda z, d, hw: z - cf * hw + kerb + cf_sw * np.clip(d - hw, 0.0, max_rise_run))


def surface_on(fn, mask, X, Y, sigma_px, ring=2):
    """A paved surface: fn(xy) at the cells of `mask` and a ring of `ring` cells around it (so it can be sampled up
    to its edge), smoothed within them (normalised Gaussian, sigma in cells); NaN elsewhere."""
    top = np.full(mask.shape, np.nan)
    if not mask.any():
        return top
    M = ndimage.binary_dilation(mask, iterations=ring)
    top[M] = fn(np.column_stack([X[M], Y[M]]))
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
            for a in range(0, len(run) - 1, per):
                piece = run[a:a + per + 1]
                if len(piece) < 2:
                    continue
                p0, p1 = pts[piece[0]], pts[piece[-1]]
                if np.hypot(*(p1 - p0)) < 0.5 * res:
                    continue
                top = float(np.max(zmax[rr[piece], cc[piece]]))
                bottom = float(np.min(zmin[rr[piece], cc[piece]])) - footing
                if top - bottom - footing < 0.3:
                    continue
                out.append({"xy": [p0.round(3).tolist(), p1.round(3).tolist()], "top": round(top, 2),
                            "bottom": round(bottom, 2), "height_m": round(top - bottom - footing, 2)})
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

    # ---- the paved areas and their surfaces
    areas = paved_areas(roads, pr, float(cfg["roads"]["proposed"]["sidewalk_band_m"]), shape(ter["outline"]))
    blds = [shape(it["polygon"]) for k in ("existing", "proposed") for it in bj[k]]
    BLD = mask_of(unary_union(blds), X, Y) if blds else np.zeros(z0.shape, bool)
    EX = mask_of(areas["existing"], X, Y) & ~BLD if ex.edges else np.zeros(z0.shape, bool)
    CAR = mask_of(areas["carriageway"], X, Y) & ~BLD
    SW = mask_of(areas["sidewalks"], X, Y) & ~BLD & ~CAR
    EX &= ~(CAR | SW)
    LOOSE = mask_of(areas["loose"], X, Y) & ~BLD & ~(EX | CAR | SW)
    sig = float(prof["surface_smoothing_m"]) / res
    top_ex = surface_on(ex.surface_z, EX, X, Y, sig) if ex.edges else np.full(z0.shape, np.nan)
    top_car = surface_on(pr.surface_z, CAR, X, Y, sig) if pr.edges else np.full(z0.shape, np.nan)
    top_sw = surface_on(lambda xy: sidewalk_z(pr, xy, kerb, cf_sw), SW, X, Y, sig) if pr.edges else \
        np.full(z0.shape, np.nan)
    surf = np.full(z0.shape, np.nan)  # the finished paved surface
    for M, top in ((EX, top_ex), (CAR, top_car), (SW, top_sw)):
        surf[M] = top[M]
    PAVED = EX | CAR | SW
    z1 = z0.copy()
    z1[EX | CAR] = surf[EX | CAR] - pav
    z1[SW] = surf[SW] - kerb - pav  # the ground runs on under the kerb at the carriageway's bed

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
        D = ~PAVED & ~BLD & valid & np.isfinite(near_d)
        both = D & (lo <= hi)  # every slope agrees: above all fill slopes, below all cut slopes
        z1[both] = np.clip(z0[both], lo[both], hi[both])
        clash = D & ~both  # slopes of two street stretches overlap: the nearer one wins, a wall between them
        z1[clash] = np.clip(z0[clash], near_lo[clash], near_hi[clash])
        # the nearest street cell jumps along a sloping street, which leaves small steps in the side slopes: smooth
        # the change of the ground there (masked, ~1 m), exact at the street edge, so only real steps remain
        change = np.where(D, np.nan_to_num(z1 - z0), 0.0)
        wgt = ndimage.gaussian_filter(D.astype(np.float64), 2.0)
        sm = ndimage.gaussian_filter(change, 2.0) / np.maximum(wgt, 1e-6)
        fade = np.clip(np.nan_to_num(near_d, nan=reach) / 3.0, 0.0, 1.0)
        z1[D] = z0[D] + ((1.0 - fade) * change + fade * sm)[D]
        # a retaining wall is needed where the slope has not met the ground at the end of its reach, where it
        # stops at an existing street with a step, and between street stretches whose slopes clash
        rim = D & (np.nan_to_num(near_d) > reach - 1.01 * res) & (np.abs(z1 - z0) > 0.3)  # one cell wide
        at_ex = D & ndimage.binary_dilation(EX) & (np.abs(z1 - z0) > 0.5)
        at_clash = cliffs(z1, z0, clash, 0.5)
        # a bridge ends at an abutment: the step between the deck's ground and the embankment beside it
        at_bridge = cliffs(z1, z0, ndimage.binary_dilation(bridge, iterations=2) & ~bridge & valid, 0.5) if bridge.any() \
            else np.zeros(z0.shape, bool)
        wall = rim | at_ex | at_clash | at_bridge
        walls = {"cells": int(wall.sum()), "length_m": round(float(wall.sum()) * res, 1),
                 "at_reach_m": round(float(rim.sum()) * res), "at_existing_streets_m": round(float(at_ex.sum()) * res),
                 "between_streets_m": round(float(at_clash.sum()) * res), "at_bridges_m": round(float(at_bridge.sum()) * res),
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
        EB = ~PAVED & ~BLD & valid & ~np.isfinite(near_d) & (dd <= ease) & np.isfinite(h)
        target = np.clip(z0, h - dd / fill_hv, h + dd / cut_hv)
        z1[EB] = (z0 + (1.0 - dd / ease) * (target - z0))[EB]

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
                        EX=EX, CAR=CAR, SW=SW, LOOSE=LOOSE, BLD=BLD, BRIDGE=bridge, gt=np.array(gt))
    bridge_area = mask_polygon(bridge, gt) if bridge.any() else None
    if bridges:
        warn("earthworks: bridges / viaducts where a street would stand more than "
             f"{ew['max_fill_m']} m above the ground: " + ", ".join(
                 f"{b['street']} {b['from_m']:.0f}-{b['to_m']:.0f} m (up to {b['max_height_m']:.0f} m high)" for b in bridges))
    if LOOSE.any():
        log(f"earthworks: {float(LOOSE.sum()) * area:,.0f} m2 of paved area has no street axis through it "
            "(ramps, parking, driveways): it stays drawn in 2D on the existing ground")
    geo = lambda g: mapping(g) if g is not None and not g.is_empty else None
    result = {"inputs": wanted, "cut_m3": round(cut), "fill_m3": round(fill), "balance_m3": round(fill - cut),
              "loose_paved_m2": round(float(LOOSE.sum()) * area),
              "max_cut_m": round(float(max(0.0, -dz_works.min())), 2), "max_fill_m": round(float(max(0.0, dz_works.max())), 2),
              "changed_area_m2": round(float((np.abs(dz_works) > 0.05).sum()) * area), "retaining_walls": walls,
              "bridges": bridges, "kept_under_buildings_m2": round(float(BLD.sum()) * area),
              "existing_edges_eased_m3": round(eased),
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
             f"slopes do not meet the ground within {ew['max_daylight_m']} m, run into an existing street, or where two "
             "street stretches are too close for their slopes)")
    if walls.get("at_buildings_m"):
        log(f"earthworks: the ground under the buildings is left as it is; beside them it changes by more than 0.5 m "
            f"along about {walls['at_buildings_m']:,} m (their walls retain it)")
    save_json(out_json, result)
