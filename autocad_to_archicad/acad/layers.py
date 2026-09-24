"""What each drawing layer holds, worked out from its geometry (and OpenStreetMap), not from its name.

  existing_buildings  building outlines that match OpenStreetMap's buildings: the georef stage tries the layers with
                      the most building-like closed shapes and keeps the one that places the drawing on the map
  kerbs               lines that run along both sides of OpenStreetMap's streets at a street's width
  carriageway, axes   a layer of lines that runs along the middle of the strips of a hatch layer: the new streets'
                      axis lines and their carriageway (the axes must not be OSM streets: those exist already)
  sidewalks           hatches that line the carriageway's edges
  proposed_buildings  closed outlines whose footprints, slid in one common direction, make the shapes of another
  shadows             layer: architects' drawn shadows, and the buildings that cast them
  trees               layers made of round symbols of tree size (circles, round hatches)
A DWG with XREFs repeats a layer per XREF ('2918_P_ROADS$0$WIL_VOIRIE 02', '2918_P_LDSCP$0$WIL_VOIRIE 02'): a role
takes every layer with the same name. Names in several languages ('road', 'voirie', 'ombre', 'ծառ' ...) only order the
candidates and break ties. Any role can be fixed with layer name patterns in layers.<role>.
"""
import math
from collections import defaultdict

import numpy as np
from osgeo import gdal, ogr
from scipy import ndimage
from shapely import STRtree
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from . import buildings as B
from .geometry.raster import sample_raster
from .roads.existing import default_width, kerb_segments, ray_hits
from .roads.geometry import area_of, normals, resample
from .site import layer_names, matcher, polylines

ROLES = ("existing_buildings", "proposed_buildings", "shadows", "trees", "carriageway", "axes", "sidewalks", "kerbs")


def by_layer(site):
    out = defaultdict(list)
    for p in site["prims"]:
        out[p["layer"]].append(p)
    return out


def base_name(raw):
    return raw.split("$0$")[-1].split("|")[-1]


def with_siblings(chosen, all_layers):
    """The chosen layers and every layer of the same name in another XREF."""
    bases = {base_name(r) for r in chosen}
    return sorted(r for r in all_layers if base_name(r) in bases)


def hinted(raw, layers, words):
    names = " ".join(layer_names(raw, layers)).lower()
    return any(w.lower() in names for w in words)


def fixed_role(cfg, role, site):
    """Layers of a role fixed in the settings (layers.<role> = patterns), or None when it is 'auto'."""
    v = cfg["layers"][role]
    if v == "auto" or v is None:
        return None
    m = matcher(v, site["layers"])
    return sorted({p["layer"] for p in site["prims"] if m(p["layer"])})


def closed_shapes(prims, min_area=1.0):
    out = []
    for p in prims:
        rings = [p["xy"]] if p["kind"] == "poly" and p.get("closed") and len(p["xy"]) >= 3 else \
            p.get("rings", []) if p["kind"] == "fill" else []
        for r in rings:
            if len(r) < 3:
                continue
            g = Polygon(r)
            g = g if g.is_valid else g.buffer(0)
            if g.geom_type == "Polygon" and g.area > min_area:
                out.append(g)
    return out


# --------------------------------------------------------------------------- trees
def round_symbols(prims, lo, hi):
    """(symbols of tree size, all shapes) of a layer: circles and round closed shapes. A round shape whose centre lies
    inside a bigger one is part of that symbol (the trunk mark in a crown): it counts neither way."""
    n = 0
    rounds = []  # (x, y, radius)
    for p in prims:
        if p["kind"] == "circle":
            rounds.append((float(p["c"][0]), float(p["c"][1]), float(p["r"])))
        elif p["kind"] == "poly" and not p.get("closed"):
            n += 1
    for g in closed_shapes(prims, 0.0):
        if 4 * math.pi * g.area / max(g.length ** 2, 1e-9) >= 0.85:  # a square: 0.79
            rounds.append((g.centroid.x, g.centroid.y, math.sqrt(g.area / math.pi)))
        else:
            n += 1
    kept = []
    if rounds:
        from scipy.spatial import cKDTree
        a = np.array(rounds)
        tree = cKDTree(a[:, :2])
        for i, (x, y, rad) in enumerate(a):
            near = tree.query_ball_point((x, y), float(a[:, 2].max()))
            if not any(a[j, 2] > rad and math.hypot(x - a[j, 0], y - a[j, 1]) < a[j, 2] for j in near):
                kept.append((x, y, rad))
    r = sum(1 for _, _, rad in kept if lo <= rad <= hi)
    return r, n + len(kept)


def tree_layers(by, layers, cfg):
    b, words = cfg["buildings"], cfg["layers"]["hints"]["trees"]
    lo, hi = float(b["tree_min_crown_m"]), float(b["tree_max_crown_m"])
    out, ev = [], {}
    for raw, prims in by.items():
        r, n = round_symbols(prims, lo, hi)
        if not n:
            continue
        share, hint = r / n, hinted(raw, layers, words)
        if r >= 10 and (share >= 0.8 or (share >= 0.5 and hint)):
            out.append(raw)
            ev[raw] = f"{r} round symbols of tree size ({100 * share:.0f} % of its shapes)"
    return sorted(out), ev


# --------------------------------------------------------------------------- buildings (candidates for georef)
def building_candidates(by, layers, cfg, exclude=()):
    """Layers ranked as existing building outlines: [(raw, faces, rectilinear share, hinted)], most likely first.
    Building-like = many closed faces of building size with square corners; a name hint goes first."""
    words = cfg["layers"]["hints"]["existing_buildings"]
    out = []
    for raw, prims in by.items():
        if raw in exclude or sum(1 for p in prims if p["kind"] in ("poly", "fill")) < 20:
            continue
        faces = [f for f in B.faces_of(prims, 20.0, 5000.0)]
        if len(faces) < 20:
            continue
        a = B._angles(faces[:400])
        if not len(a):
            continue
        h, e = np.histogram(a[:, 0] % 90.0, bins=90, range=(0, 90), weights=a[:, 1])
        k = int(np.argmax(h))
        rect = float(sum(h[(k + d) % 90] for d in (-2, -1, 0, 1, 2)) / max(h.sum(), 1e-9))
        out.append((raw, len(faces), round(rect, 2), hinted(raw, layers, words)))
    # name hint first, then square-cornered layers with many faces
    out.sort(key=lambda t: (not t[3], -(t[1] * t[2])))
    return out


# --------------------------------------------------------------------------- streets
def burn(geom, gt, shape):
    """Boolean grid (rows, cols = shape, geotransform gt) of the cells whose centre lies in a (multi)polygon."""
    ds = gdal.GetDriverByName("MEM").Create("", shape[1], shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    vds = ogr.GetDriverByName("MEM").CreateDataSource("burn")
    lyr = vds.CreateLayer("burn", geom_type=ogr.wkbUnknown)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkb(geom.wkb))
    lyr.CreateFeature(f)
    gdal.RasterizeLayer(ds, [1], lyr, burn_values=[1])
    return ds.GetRasterBand(1).ReadAsArray().astype(bool)


def _grid(site, res=0.5, max_cells=3.0e7):
    bx = site["bbox"]
    w, h = bx[2] - bx[0], bx[3] - bx[1]
    res = max(res, math.sqrt(w * h / max_cells))
    shape = (int(h / res) + 2, int(w / res) + 2)
    return (bx[0] - res, res, 0.0, bx[3] + res, 0.0, -res), shape


def street_layers(by, layers, site, cfg, osm_lines=None, exclude=(), strips_of=None, lines_of=None):
    """(carriageway layers, axis layers, evidence): the line layer that runs along the middle of a hatch layer's strips.
    A point of an axis is centred when the distance to the strip's edge is largest there across the line; the axis
    layer must be centred for most of its length (stair treads or hatch outlines cross strips, they do not follow
    them), and must not run along OSM streets (those are existing). strips_of / lines_of: layers fixed by the settings
    (only the other one is searched)."""
    words = cfg["layers"]["hints"]["carriageway"]
    gt, shape = _grid(site)
    strips = {}
    for raw, prims in by.items():
        if (raw in exclude and not strips_of) or (strips_of and raw not in strips_of):
            continue
        U = area_of([p for p in prims if p["kind"] in ("fill", "poly")])
        if U is not None and U.area >= 1000.0:
            strips[raw] = U
    lines = {}
    for raw, prims in by.items():
        if (raw in exclude and not lines_of) or (lines_of and raw not in lines_of):
            continue
        ls = [np.asarray(p["xy"], dtype=np.float64) for p in prims if p["kind"] == "poly" and not p.get("closed")
              and len(p["xy"]) >= 2]
        pts, ns, lens = [], [], []
        for xy in ls:
            q, s = resample(xy, 2.0)
            if len(q) >= 2:
                pts.append(q)
                ns.append(normals(q))
                lens.append(s[-1])
        if pts and sum(lens) >= 100.0:
            lines[raw] = (np.vstack(pts), np.vstack(ns), float(np.median(lens)))
    osm_tree = None
    if osm_lines:
        from scipy.spatial import cKDTree
        osm_pts = np.vstack([resample(l, 2.0)[0] for l in osm_lines if len(l) >= 2])
        osm_tree = cKDTree(osm_pts)
    pairs = []
    for sraw, U in strips.items():
        edt = ndimage.distance_transform_edt(burn(U, gt, shape)) * gt[1]
        for araw, (P, N, med_len) in lines.items():
            if araw == sraw or med_len < 20.0:
                continue
            d0 = sample_raster(edt, gt, P, nan_outside=False)
            dl = sample_raster(edt, gt, P + N, nan_outside=False)
            dr = sample_raster(edt, gt, P - N, nan_outside=False)
            ok = (d0 >= 1.5) & (d0 <= 12.0) & (d0 >= dl - 0.3) & (d0 >= dr - 0.3)
            share = float(ok.mean())
            if ok.sum() * 2.0 < 100.0 or share < 0.4:
                continue
            on_osm = float((osm_tree.query(P[ok])[0] < 6.0).mean()) if osm_tree is not None else 0.0
            if on_osm > 0.5:
                continue
            pairs.append((ok.sum() * 2.0 * (1.5 if hinted(sraw, layers, words) else 1.0), sraw, araw,
                          {"centred_m": round(float(ok.sum() * 2.0)), "share": round(share, 2),
                           "width_m": round(float(2 * np.median(d0[ok])), 1), "along_osm_share": round(on_osm, 2)}))
    if not pairs:
        # no axis lines: a hatch layer named as a street layer, if any
        named = [r for r in strips if hinted(r, layers, words)]
        if named:
            best = max(named, key=lambda r: strips[r].area)
            return [best], [], {best: "hatch layer named as a street layer (no axis lines found)"}
        return [], [], {}
    pairs.sort(key=lambda t: -t[0])
    _, sraw, araw, stats = pairs[0]
    ev = {sraw: f"hatched strips {stats['width_m']} m wide with the axis lines of {base_name(araw)} along their middle "
                f"({stats['centred_m']} m, {100 * stats['share']:.0f} % of those lines)",
          araw: f"lines along the middle of {base_name(sraw)}'s strips for {stats['centred_m']} m"}
    return [sraw], [araw], ev


def sidewalk_layers(by, car, exclude=(), min_share=0.2):
    """Hatch layers that line the carriageway's edges: [raw], evidence. The best one and those close to it."""
    edge = car.boundary
    scores = {}
    for raw, prims in by.items():
        if raw in exclude or not any(p["kind"] == "fill" for p in prims):
            continue
        U = area_of([p for p in prims if p["kind"] == "fill"])
        if U is None or U.area < 100.0 or U.intersection(car).area > 0.5 * U.area:
            continue
        share = edge.intersection(U.buffer(0.5)).length / max(edge.length, 1e-9)
        if share >= min_share:
            scores[raw] = share
    if not scores:
        return [], {}
    top = max(scores.values())
    keep = [r for r, s in scores.items() if s >= 0.8 * top]
    return keep, {r: f"hatches along {100 * scores[r]:.0f} % of the carriageway's edges" for r in keep}


def kerb_layers(by, layers, cfg, osm_ways, to_drawing, clip, exclude=(), min_share=0.15):
    """Line layers found on both sides of OpenStreetMap's streets at a plausible street width: [raw], evidence."""
    P, N, WD = [], [], []
    classes = cfg["roads"]["existing"]["osm_classes"]
    for w in osm_ways:
        if w["tags"].get("highway") not in classes:
            continue
        line = LineString(to_drawing(w["lonlat"])).intersection(clip)
        for g in getattr(line, "geoms", [line]):
            if g.geom_type != "LineString" or g.length < 10.0:
                continue
            p, _ = resample(np.asarray(g.coords), 5.0)
            P.append(p)
            N.append(normals(p))
            WD.append(np.full(len(p), default_width(w["tags"], cfg)[0]))
    if not P:
        return [], {}
    P, N, WD = np.vstack(P), np.vstack(N), np.concatenate(WD)
    reach = float(cfg["roads"]["existing"]["kerb_search_m"])
    words = cfg["layers"]["hints"]["kerbs"]
    found = {}
    for raw, prims in by.items():
        if raw in exclude:
            continue
        ls = polylines([p for p in prims if p["kind"] == "poly"])
        if sum(len(x) for x in ls) < 20:
            continue
        segs = kerb_segments(ls)
        left, right = ray_hits(P, N, reach, segs), ray_hits(P, -N, reach, segs)
        with np.errstate(invalid="ignore"):
            wd = left + right
            good = np.isfinite(wd) & (wd >= 0.6 * WD) & (wd <= 2.2 * WD + 2.0) & \
                (np.abs(left - right) / 2.0 <= 0.5 * WD + 2.0)
        share = float(good.mean())
        if share >= min_share or (share >= 0.5 * min_share and hinted(raw, layers, words)):
            found[raw] = share
    return sorted(found), {r: f"lines on both sides of {100 * s:.0f} % of OSM's street stations at a street's width"
                           for r, s in found.items()}


# --------------------------------------------------------------------------- shadows and the buildings that cast them
def shadow_layers(by, layers, cfg, exclude=(), casters_of=None, shadows_of=None, min_casters=10, min_explained=0.5):
    """(caster layers, shadow layers, direction deg, evidence). A shadow layer's shapes touch the casters' footprints
    and are explained by them: a footprint slid along one direction (the same for all) fills the shadow.
    casters_of / shadows_of: layers fixed by the settings (only the other one is searched)."""
    faces, shapes = {}, {}
    for raw, prims in by.items():
        if (casters_of and raw in casters_of) or (not casters_of and raw not in exclude):
            f = [x for x in B.faces_of(prims, 30.0, float(cfg["buildings"]["max_area_m2"]))]
            if 3 <= len(f) <= 2000 or casters_of:
                faces[raw] = f
        if (shadows_of and raw in shadows_of) or (not shadows_of and raw not in exclude):
            s = closed_shapes(prims)
            if 3 <= len(s) <= 5000 or shadows_of:
                shapes[raw] = s
    unions = {r: unary_union(f) for r, f in faces.items()}
    found = []
    for craw, fc in faces.items():
        if not fc:
            continue
        tree = STRtree(fc)
        for sraw, sp in shapes.items():
            if sraw == craw or not sp:
                continue
            touch = len(set(tree.query(sp, predicate="dwithin", distance=0.3)[0])) / len(sp)
            if touch < 0.5:
                continue
            su = unary_union(sp)
            if su.intersection(unions[craw]).area > 0.8 * su.area:  # the same shapes (an outline and its hatch)
                continue
            d = B.shadow_direction(fc, sp)
            if d is None:
                continue
            cs = B.shadow_lengths(fc, sp, d)
            explained = len({c[2] for c in cs}) / len(sp)
            if len(cs) >= min_casters and explained >= min_explained:
                found.append((len(cs), explained, d, craw, sraw))
    if not found:
        return [], [], None, {}
    found.sort(key=lambda t: -t[0])
    direction = found[0][2]
    found = [f for f in found if abs((f[2] - direction + 90.0) % 180.0 - 90.0) <= 2.0]
    shadows = sorted({f[4] for f in found})
    # caster layers: the one with the most footprints; another only when it adds footprints of its own (a hatch of
    # the same outlines adds nothing)
    words = cfg["layers"]["hints"]["proposed_buildings"]
    cands = sorted({f[3] for f in found}, key=lambda r: (-len(faces[r]), not hinted(r, layers, words)))
    casters, covered = [], None
    for r in cands:
        if covered is None or unions[r].difference(covered).area > 0.5 * unions[r].area:
            casters.append(r)
            covered = unions[r] if covered is None else covered.union(unions[r])
    ev = {}
    for n, share, d, craw, sraw in found:
        if craw in casters:
            ev[craw] = f"{n} of its footprints cast the drawn shadows (along {d:.1f} deg)"
        ev[sraw] = f"{100 * share:.0f} % of its shapes are footprints slid along {d:.1f} deg (drawn shadows)"
    return casters, shadows, direction, ev


def proposed_by_name(by, layers, cfg, exclude=()):
    """Without drawn shadows: building-sized closed outlines on a layer named as new buildings."""
    words = cfg["layers"]["hints"]["proposed_buildings"]
    out = [r for r, prims in by.items() if r not in exclude and hinted(r, layers, words)
           and len(B.faces_of(prims, 30.0, float(cfg["buildings"]["max_area_m2"]))) >= 3]
    return out, {r: "building outlines on a layer named as new buildings (no drawn shadows found)" for r in out}


def osm_drawing_lines(osm_ways, to_drawing, classes):
    return [to_drawing(w["lonlat"]) for w in osm_ways if w["tags"].get("highway") in classes]
