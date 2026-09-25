"""Stage context: the surroundings of the site, so it sits in its city - the OpenStreetMap buildings around it, on a
terrain made from the open world terrain model.

  terrain     a grid of context.grid_m over the survey terrain's box grown by context.margin_m; heights from the world
              terrain tiles (cloud.world_terrain_url at zoom context.dem_zoom, ~30 m data, +-3-5 m). They differ from
              the survey terrain by a few metres: the difference along the survey terrain's outline is carried into
              the context (from the nearest outline points, fading to its median over context.fade_m), so the two meet
              without a step. The Archicad file gets it as a second mesh with the survey terrain as its hole
  buildings   OpenStreetMap buildings in that box (Overpass: ways, multipolygons and building:parts), outside the
              survey terrain and clear of the drawing's buildings (inside, the drawing says what stands). A building
              detailed by building:parts is made of its parts, each from its min_height to its height (the stepped
              shapes of towers and terraces); heights as for the existing buildings (OSM height, levels, else the usual
              storeys of its type). Each stands on the ground under it
Results: context_terrain.tif (altitudes), context.json (the buildings, bodies ready to extrude)."""
import math

import numpy as np
from scipy.spatial import cKDTree
from shapely import contains_xy, segmentize
from shapely.geometry import LineString, box, mapping, shape
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from .. import buildings as B
from ..config import settings
from ..geometry.crs import LonLatUTM, Rigid2D
from ..geometry.raster import nearest_fill, read_raster, sample_raster, write_raster
from ..io import overpass, world_dem
from ..roads.geometry import as_polygons
from ..util import file_signature, load_json, log, save_json, skip, warn


def footprint(item, to_xy):
    """The item's outline (outer rings minus inner, member ways joined) in drawing metres, or None."""
    lines = lambda rings: [LineString(to_xy(np.asarray(r))) for r in rings if len(r) >= 2]
    outer = unary_union(list(polygonize(unary_union(lines(item["outer"])))))
    if outer.is_empty:
        return None
    if item["inner"]:
        inner = unary_union(list(polygonize(unary_union(lines(item["inner"])))))
        outer = outer.difference(inner)
    outer = outer.buffer(0)
    return None if outer.is_empty else outer


def heights(tags, b):
    """(bottom above ground, top above ground, source) of a building or part from its OSM tags."""
    storey = float(b["existing_storey_m"])
    h, n, src = B.osm_height(tags, storey)
    if h is None:
        n = B.OSM_TYPE_STOREYS.get(tags.get("building") or tags.get("building:part"), int(b["existing_default_storeys"]))
        h, src = n * storey, f"usual for OSM type '{tags.get('building') or tags.get('building:part')}' (assumed)"
    low = B._float(tags.get("min_height"))
    if low is None:
        ml = B._float(tags.get("building:min_level"))
        low = ml * storey if ml else 0.0
    return max(0.0, low), max(h, low + 1.0), src


def run(job, force=False):
    cfg = job.cfg
    c = cfg["context"]
    out_json, out_tif = job.w("context.json"), job.w("context_terrain.tif")
    ter, geo, bj = load_json(job.w("terrain.json")), load_json(job.w("georef.json")), load_json(job.w("buildings.json"))
    if not c["enabled"]:
        save_json(out_json, {"enabled": False, "buildings": []})
        skip("context: switched off (context.enabled)")
        return
    if not ter or not geo or bj is None or not job.w("terrain_design.tif").exists():
        raise RuntimeError("run the georef, terrain, buildings and earthworks stages first")
    wanted = {"terrain": file_signature(job.w("terrain_design.tif")), "buildings": file_signature(job.w("buildings.json")),
              "georef": file_signature(job.w("georef.json")), **settings(cfg, "context"),
              "b": {k: cfg["buildings"][k] for k in ("existing_storey_m", "existing_default_storeys", "embed_m")}}
    prev = load_json(out_json) or {}
    if not force and prev.get("inputs") == wanted and out_tif.exists():
        skip(f"context: already done ({len(prev['buildings'])} buildings around the site)")
        return
    g2u, tr = Rigid2D.from_json(geo["transform"]), LonLatUTM(geo["epsg"])
    to_xy = lambda ll: g2u.inverse(tr.to_utm(ll))
    to_ll = lambda xy: tr.to_lonlat(g2u.apply(np.asarray(xy, dtype=np.float64).reshape(-1, 2)))
    outline = shape(ter["outline"])
    m = float(c["margin_m"])
    x0, y0, x1, y1 = outline.bounds
    area = box(x0 - m, y0 - m, x1 + m, y1 + m)

    # ---- the context terrain: world terrain tiles, fitted to the survey terrain along its outline
    g = float(c["grid_m"])
    xs = np.arange(area.bounds[0], area.bounds[2] + g / 2, g)
    ys = np.arange(area.bounds[3], area.bounds[1] - g / 2, -g)
    X, Y = np.meshgrid(xs, ys)
    xy = np.column_stack([X.ravel(), Y.ravel()])
    zw = world_dem.heights(to_ll(xy), cfg["cloud"]["world_terrain_url"], int(c["dem_zoom"])).reshape(X.shape)
    ok = np.isfinite(zw)
    if ok.sum() < 4:
        raise RuntimeError("context: the world terrain tiles gave no heights here (offline?) - "
                           "switch the surroundings off with --set context.enabled=false")
    zw = nearest_fill(zw, ok)
    gt = (xs[0] - g / 2, g, 0.0, ys[0] + g / 2, 0.0, -g)
    z1, zgt, _ = read_raster(job.w("terrain_design.tif"))
    zs = nearest_fill(z1, np.isfinite(z1))
    edge = np.vstack([np.asarray(r.coords)[:, :2] for p in as_polygons(segmentize(outline, g))
                      for r in [p.exterior]])
    diff = sample_raster(zs, zgt, edge, nan_outside=False) - sample_raster(zw, gt, edge, nan_outside=False)
    tree = cKDTree(edge)
    d, i = tree.query(xy, k=min(8, len(edge)))
    wgt = 1.0 / np.maximum(d, 1.0) ** 2
    near = (wgt * diff[i]).sum(axis=1) / wgt.sum(axis=1)
    fade = np.exp(-d[:, 0] / float(c["fade_m"]))
    shift = np.median(diff)
    zc = zw + (fade * near + (1.0 - fade) * shift).reshape(X.shape)
    write_raster(out_tif, zc, gt)
    inside = lambda p: contains_xy(outline, p[:, 0], p[:, 1])

    def ground(poly):
        """(median, min) of the ground under a footprint: the survey terrain inside its outline, else the context."""
        bx0, by0, bx1, by1 = poly.bounds
        st = max(1.0, min(4.0, math.sqrt(poly.area) / 6.0))
        P = np.stack(np.meshgrid(np.arange(bx0, bx1 + st, st), np.arange(by0, by1 + st, st)), -1).reshape(-1, 2)
        P = np.vstack([P[contains_xy(poly, P[:, 0], P[:, 1])], np.asarray(poly.exterior.coords)[:, :2]
                       if poly.geom_type == "Polygon" else np.zeros((0, 2))])
        v = np.where(inside(P), sample_raster(zs, zgt, P, nan_outside=False), sample_raster(zc, gt, P, nan_outside=False))
        return float(np.median(v)), float(v.min())

    # ---- the buildings around
    ll = to_ll(np.asarray(area.exterior.coords))
    bbox = (ll[:, 0].min(), ll[:, 1].min(), ll[:, 0].max(), ll[:, 1].max())
    try:
        items = overpass.buildings(bbox, c["overpass_urls"], cfg["site"]["osm_user_agent"], job.w("context_osm.json"))
    except RuntimeError as e:
        warn(f"context: {e} - no buildings around the site this time (the terrain is made)")
        items = []
    drawn = [shape(it["polygon"]) for k in ("existing", "proposed", "demolished") for it in bj.get(k, [])]
    drawn += [shape(w["polygon"]) for w in bj.get("walls", [])]
    taken = unary_union(drawn).buffer(1.0) if drawn else None
    keep_out = outline.buffer(-2.0)
    b = cfg["buildings"]
    embed = float(b["embed_m"])
    polys = []
    for it in items:
        p = footprint(it, to_xy)
        if p is None or not p.intersects(area):
            continue
        p = p.intersection(area.buffer(-0.5 * g))  # no building overhangs the edge of the context ground
        if p.is_empty or p.area < float(c["min_area_m2"]):
            continue
        if keep_out.contains(p.representative_point()) or (taken is not None and p.intersection(taken).area > 0.2 * p.area):
            continue
        polys.append((p, it))
    # a building detailed by parts is made of its parts
    parts = [(p, it) for p, it in polys if it["kind"] == "part"]
    ptree = STRtree([p for p, _ in parts]) if parts else None
    out, n_parts, srcs = [], 0, {}
    for p, it in polys:
        if it["kind"] == "building" and ptree is not None:
            cover = sum(p.intersection(parts[j][0]).area for j in ptree.query(p))
            if cover >= 0.5 * p.area:
                continue
        med, lo = ground(p)
        bottom, top, src = heights(it["tags"], b)
        n_parts += it["kind"] == "part"
        srcs[src.split(" (")[0] if "usual" not in src else "usual for its OSM type"] = \
            srcs.get(src.split(" (")[0] if "usual" not in src else "usual for its OSM type", 0) + 1
        for q in as_polygons(p.simplify(0.05)):
            if q.area < 1.0:
                continue
            out.append({"polygon": mapping(q), "osm": it["id"], "kind": it["kind"],
                        "bottom_z": round((lo - embed) if bottom <= 0.0 else med + bottom, 2),
                        "top_z": round(med + top, 2), "height_m": round(top, 1), "source": src,
                        "name": it["tags"].get("name")})
    save_json(out_json, {"inputs": wanted, "area": mapping(area), "grid_m": g, "shift_m": round(float(shift), 2),
                         "edge_diff_m": [round(float(np.percentile(diff, 10)), 2), round(float(np.percentile(diff, 90)), 2)],
                         "buildings": out, "licence": "(c) OpenStreetMap contributors, ODbL"})
    log(f"context: {len(out):,} buildings around the site ({n_parts} of them building parts) within "
        f"{m:.0f} m of the survey terrain; heights: " + ", ".join(f"{k} {v}" for k, v in
                                                                  sorted(srcs.items(), key=lambda kv: -kv[1])))
    log(f"context: ground from the world terrain model on a {g:.0f} m grid, {(area.area - outline.area) / 1e4:.0f} ha; "
        f"it differs from the survey terrain along its outline by {np.percentile(diff, 10):+.1f} .. "
        f"{np.percentile(diff, 90):+.1f} m (median {shift:+.1f} m), carried over so they meet without a step")
