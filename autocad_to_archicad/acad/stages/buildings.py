"""Stage buildings: the buildings, trees and underground levels of the site, with heights, on the terrain.

  existing buildings   the outlines of the existing building layers joined into faces; heights from OSM. One that the
                       new buildings, carriageways or sidewalks cover (buildings.demolish_share / demolish_m2) is to be
                       demolished: left out and listed; a smaller overlap is trimmed off it
  proposed buildings   the outlines that cast the drawn shadows; storeys read from the shadows, checked against the
                       documents' above-ground floor area (when documents are given)
  underground levels   the level outlines read from the project documents (documents stage), stacked down from
                       the ground floor level
  trees                the tree symbols: circles and small round fills
The layers are the layers stage's. Each building stands on the terrain: its ground floor at the median terrain height
over its footprint, its body reaching down to the lowest terrain there. The streets and earthworks that follow leave
the ground under the buildings as it is, so this stays true. See acad/buildings.py for the rules.
Result: buildings.json.
"""
import math
from collections import Counter

import numpy as np
from shapely import contains_xy
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

from .. import buildings as B
from .. import layers as L
from ..config import settings
from ..geometry.crs import LonLatUTM, Rigid2D
from ..geometry.raster import nearest_fill, read_raster, sample_raster
from ..roads.geometry import as_polygons
from ..site import load_site, on_layers
from ..util import detail, file_signature, load_json, log, save_json, skip, warn


def terrain_under(poly, z, gt, step=1.0):
    """(median, min, max) of the terrain inside a footprint (and on its outline)."""
    x0, y0, x1, y1 = poly.bounds
    xs = np.arange(x0 + step / 2, x1, step)
    ys = np.arange(y0 + step / 2, y1, step)
    pts = np.zeros((0, 2))
    if len(xs) and len(ys):
        X, Y = np.meshgrid(xs, ys)
        m = contains_xy(poly, X, Y)
        pts = np.column_stack([X[m], Y[m]])
    ring = np.asarray(poly.exterior.coords)
    pts = np.vstack([pts, ring[:, :2]])
    v = sample_raster(z, gt, pts, nan_outside=False)
    v = v[np.isfinite(v)]
    if not len(v):
        return None
    return float(np.median(v)), float(v.min()), float(v.max())


def osm_buildings(job):
    geo, osm = load_json(job.w("georef.json")), load_json(job.w("osm.json"))
    if not geo or not osm:
        return []
    g2u, tr = Rigid2D.from_json(geo["transform"]), LonLatUTM(geo["epsg"])
    out = []
    for w in osm["ways"]:
        if "building" not in w["tags"] or len(w["lonlat"]) < 4:
            continue
        xy = g2u.inverse(tr.to_utm(np.array(w["lonlat"])))
        p = Polygon(xy)
        if not p.is_valid:
            p = p.buffer(0)
        if p.geom_type == "Polygon" and p.area > 5:
            out.append((p, w["tags"]))
    return out


def run(job, force=False):
    cfg = job.cfg
    b = cfg["buildings"]
    out = job.w("buildings.json")
    if not job.w("terrain_existing.tif").exists() or not job.w("layers.json").exists():
        raise RuntimeError("run the layers and terrain stages first")
    docs = load_json(job.w("documents.json")) or {}
    roles = load_json(job.w("layers.json"))["roles"]
    wanted = {"site": file_signature(job.w("site.pkl")), "terrain": file_signature(job.w("terrain_existing.tif")),
              "documents": file_signature(job.w("documents.json")) if job.w("documents.json").exists() else None,
              "osm": file_signature(job.w("osm.json")) if job.w("osm.json").exists() else None, "layers": roles,
              **settings(cfg, "buildings"), "sidewalk_band_m": cfg["roads"]["proposed"]["sidewalk_band_m"]}
    prev = load_json(out) or {}
    if not force and prev.get("inputs") == wanted:
        skip(f"buildings: already done ({len(prev['existing'])} existing, {len(prev['proposed'])} proposed, "
             f"{len(prev['trees'])} trees)")
        return
    result = {"inputs": wanted, "existing": [], "proposed": [], "demolished": [], "underground": [], "trees": [],
              "checks": {}}
    if not b["enabled"]:
        save_json(out, result)
        skip("buildings: switched off (buildings.enabled)")
        return
    site = load_site(job)
    z, gt, _ = read_raster(job.w("terrain_existing.tif"))
    zf = nearest_fill(z, np.isfinite(z))
    ter = load_json(job.w("terrain.json"))
    outline = shape(ter["outline"]) if ter and ter.get("outline") else None
    min_a, max_a = float(b["min_area_m2"]), float(b["max_area_m2"])
    storey, gstorey = float(b["storey_m"]), float(b["ground_storey_m"])
    height_of = lambda n: gstorey + max(0, n - 1) * storey

    def place(item):
        t = terrain_under(item["poly"], zf, gt)
        if t is None:
            return False
        med, lo, hi = t
        item.update({"ground_floor_z": round(med, 2), "bottom_z": round(lo - float(b["embed_m"]), 2),
                     "top_z": round(med + item["height_m"], 2), "terrain_range_m": round(hi - lo, 2)})
        return True

    # ---- proposed (first: an existing outline under a proposed one is being replaced)
    prop_faces = B.faces_of(on_layers(site, roles["proposed_buildings"]), min_a, max_a)
    shadows = []
    for p in on_layers(site, roles["shadows"]):
        rings = [p["xy"]] if p["kind"] == "poly" and p.get("closed") and len(p["xy"]) >= 3 else \
            p.get("rings", []) if p["kind"] == "fill" else []
        for r in rings:
            g = Polygon(r)
            g = g if g.is_valid else g.buffer(0)
            if g.geom_type == "Polygon" and g.area > 1.0:
                shadows.append(g)
    step, fit, direction, casters, step_src = None, 0.0, None, [], None
    if prop_faces and shadows:
        direction = B.shadow_direction(prop_faces, shadows)
        if direction is not None:
            casters = B.shadow_lengths(prop_faces, shadows, direction)
        lengths = [c[1] for c in casters]
        if b["shadow_per_storey_m"] == "auto":
            step, fit = B.storey_step(lengths)
            step_src = "the largest step that makes every drawn shadow (but at most one) a whole number of storeys"
        else:
            step = float(b["shadow_per_storey_m"])
            fit, step_src = B.whole_share(lengths, step), "buildings.shadow_per_storey_m"
    by_face = {j: (length, si) for j, length, si in casters}
    # the documents describe the district inside their plan outlines: their floor area is compared there only
    prog = docs.get("program")
    plan_area = unary_union([shape(p["polygon"]) for e in docs.get("documents", []) for p in e.get("plans", [])]) \
        if docs.get("documents") else None
    plan_area = plan_area.buffer(20.0) if plan_area is not None and not plan_area.is_empty else None
    in_plan = [j for j in by_face if plan_area is not None and plan_area.contains(prop_faces[j].representative_point())]

    def gfa(q, faces_idx):
        return sum(prop_faces[j].area * max(1, int(round(by_face[j][0] / q))) for j in faces_idx)
    if step and prog and prog.get("above_ground_m2") and in_plan and b["shadow_per_storey_m"] == "auto":
        target = float(prog["above_ground_m2"])
        options = B.storey_aliases([c[1] for c in casters], step)
        best = min(options, key=lambda o: abs(math.log(max(gfa(o[0], in_plan), 1.0) / target)))
        if abs(best[0] - step) > 1e-6:
            log(f"buildings: one storey = {step:.3f} m of shadow and {best[0]:.3f} m both make the shadows whole storeys; "
                f"{best[0]:.3f} m gives the documents' floor area best ({gfa(best[0], in_plan):,.0f} against "
                f"{target:,.0f} m2, {gfa(step, in_plan):,.0f} with {step:.3f} m)")
            step, fit = best
            step_src = "the drawn shadow lengths are whole multiples of it; the documents' floor area chose among its multiples"
    elif step and b["shadow_per_storey_m"] == "auto":
        log(f"buildings: one storey = {step:.3f} m of shadow: the largest step that makes the drawn shadows whole "
            f"storeys ({step / 2:.3f} m would too, with twice the storeys: the drawing cannot tell; the project's floor "
            "area (--doc) or buildings.shadow_per_storey_m can)")
    storeys_of = {j: max(1, int(round(length / step))) for j, (length, _) in by_face.items()} if step else {}
    # a face without its own shadow that shares a long side with a face that has one can be part of that building
    # (towers are often drawn in parts: a core, a strip at the base). It takes that face's storeys only if, that tall,
    # its own shadow would fall on drawn shadows or on buildings - a podium beside a tower would throw a shadow the
    # drawing does not have
    joined = {}
    if storeys_of and direction is not None:
        dvec = np.array([math.cos(math.radians(direction)), math.sin(math.radians(direction))])
        rooms = {}  # where a shadow of n storeys may fall unseen: drawn shadows, buildings at least as tall
        for j, f in enumerate(prop_faces):
            if j in storeys_of:
                continue
            best = None
            for k, n in sorted(storeys_of.items(), key=lambda kv: -kv[1]):
                shared = f.exterior.intersection(prop_faces[k].buffer(0.2)).length
                if shared < float(b["joined_shared"]) * f.exterior.length / 4.0:
                    continue
                if n not in rooms:
                    rooms[n] = unary_union(shadows + [prop_faces[i] for i, m in storeys_of.items() if m >= n]).buffer(0.3)
                length = by_face[k][0]
                for sgn in (1.0, -1.0):
                    extra = B._sweep(f, sgn * length * dvec).difference(f)
                    if extra.area > 1e-6 and extra.intersection(rooms[n]).area / extra.area >= 0.9:
                        best = n
                        break
                if best:
                    break
            if best:
                joined[j] = best
    for j, f in enumerate(prop_faces):
        if j in storeys_of:
            n = storeys_of[j]
            item = {"poly": f, "storeys": n, "height_m": round(height_of(n), 2), "shadow_m": round(by_face[j][0], 3),
                    "source": "drawn shadow"}
        elif j in joined:
            n = joined[j]
            item = {"poly": f, "storeys": n, "height_m": round(height_of(n), 2), "shadow_m": None,
                    "source": "part of a building with a drawn shadow"}
        else:
            n = int(b["proposed_default_storeys"])
            item = {"poly": f, "storeys": n, "height_m": round(height_of(n), 2), "shadow_m": None,
                    "source": "no shadow in the drawing (assumed)"}
        if place(item):
            result["proposed"].append(item)
    if prop_faces:
        srcs = Counter(i["source"] for i in result["proposed"])
        log(f"buildings: proposed: {len(result['proposed'])} footprints ({sum(i['poly'].area for i in result['proposed']):,.0f} m2); "
            + (f"shadows {len(shadows)} drawn along {direction:.1f} deg, one storey = {step:.3f} m of shadow "
               f"(fits {100 * fit:.0f}% of them); " if step else "")
            + ", ".join(f"{v} from {k}" for k, v in srcs.items()))
        storeys = Counter(i["storeys"] for i in result["proposed"] if i["source"] == "drawn shadow")
        if storeys:
            detail("buildings: proposed storeys: " + ", ".join(f"{k} storeys x {v}" for k, v in sorted(storeys.items())))

    result["checks"]["shadows"] = {"direction_deg": direction, "storey_step_m": step, "fit": round(fit, 3),
                                   "step_source": step_src, "shadows": len(shadows), "casters": len(casters)}
    # ---- check against the programme of the documents
    if prog and result["proposed"]:
        inside = [i for i in result["proposed"] if plan_area is None or plan_area.contains(i["poly"].representative_point())]
        gfa_m = sum(i["poly"].area * i["storeys"] for i in inside if i["source"] != "no shadow in the drawing (assumed)")
        ratio = gfa_m / prog["above_ground_m2"] if prog["above_ground_m2"] else None
        result["checks"]["programme"] = {
            "documents_above_ground_m2": prog["above_ground_m2"], "model_gfa_m2": round(gfa_m),
            "buildings_compared": len([i for i in inside if i["source"] != "no shadow in the drawing (assumed)"]),
            "area": "inside the documents' plan outlines" if plan_area is not None else "all proposed buildings",
            "ratio": round(ratio, 3) if ratio else None, "functions": prog["functions_m2"], "source": prog["source"]}
        log(f"buildings: floor area of the proposed buildings in the documents' district = {gfa_m:,.0f} m2 "
            f"(footprint x storeys, {result['checks']['programme']['buildings_compared']} buildings); the documents say "
            f"{prog['above_ground_m2']:,.0f} m2 above ground ({prog['source']})" + (f": {100 * (ratio - 1):+.0f} %" if ratio else ""))
        if ratio and not 0.75 <= ratio <= 1.33:
            warn("buildings: the storeys read from the shadows and the documents' floor area disagree by more than a "
                 "third - check buildings.shadow_per_storey_m and the proposed layers")

    # ---- spacing and fire access of the new buildings (ՀՀՇՆ 30-01-2023)
    ck = b["checks"]
    tall = [i["poly"] for i in result["proposed"] if i["storeys"] >= int(ck["min_storeys"])]
    if tall:
        from shapely.strtree import STRtree
        merged = unary_union([p.buffer(0.3) for p in tall])  # parts closer than 0.6 m are one building
        blocks = list(getattr(merged, "geoms", [merged]))  # a tower drawn in parts is one building
        tree = STRtree(blocks)
        close = []
        for i, p in enumerate(blocks):
            for j in tree.query(p.buffer(float(ck["between_buildings_m"]))):
                if j > i:
                    d = p.distance(blocks[j])
                    if d < float(ck["between_buildings_m"]):
                        m = p.centroid.coords[0]
                        close.append({"at": [round(m[0], 1), round(m[1], 1)], "gap_m": round(d, 1)})
        result["checks"]["spacing"] = {"buildings": len(blocks), "closer_than_m": ck["between_buildings_m"],
                                       "close_pairs": close,
                                       "under_fire_min": sum(1 for c in close if c["gap_m"] < float(ck["fire_min_m"]))}
        log(f"buildings: spacing of {len(blocks)} new buildings of {ck['min_storeys']}+ storeys: {len(close)} gaps under "
            f"{ck['between_buildings_m']} m ({result['checks']['spacing']['under_fire_min']} under the {ck['fire_min_m']} m "
            "fire distance)")

    # ---- existing (what the new development covers is to be demolished; a sliver is trimmed off)
    ex_faces = B.faces_of(on_layers(site, roles["existing_buildings"]), min_a, max_a)
    if ex_faces:
        new = {"new buildings": unary_union([i["poly"] for i in result["proposed"]]) if result["proposed"] else None}
        by = L.by_layer(site)
        car = L.area_of([p for r in roles["carriageway"] for p in by.get(r, [])])
        if car is not None:
            new["new carriageways"] = car
            sw = L.area_of([p for r in roles["sidewalks"] for p in by.get(r, [])])
            if sw is not None:
                new["new sidewalks"] = sw.difference(car).intersection(
                    car.buffer(float(cfg["roads"]["proposed"]["sidewalk_band_m"])))
        new = {k: v for k, v in new.items() if v is not None and not v.is_empty}
        all_new = unary_union(list(new.values())) if new else None
        items, dropped = B.existing_buildings(ex_faces, osm_buildings(job), b)
        trimmed = 0
        for it in items:
            if outline is not None and not outline.buffer(20).intersects(it["poly"]):
                continue
            if all_new is not None and it["poly"].intersects(all_new):
                over = {k: it["poly"].intersection(v).area for k, v in new.items()}
                total = it["poly"].intersection(all_new).area
                if total >= float(b["demolish_share"]) * it["poly"].area or total >= float(b["demolish_m2"]):
                    c = it["poly"].representative_point()
                    result["demolished"].append({
                        "at": [round(c.x, 1), round(c.y, 1)], "area_m2": round(it["poly"].area, 1),
                        "covered_m2": round(total, 1), "by": max(over, key=over.get), "storeys": it["storeys"],
                        "polygon": mapping(it["poly"])})
                    continue
                if total > 0.01:
                    rest = [q for q in as_polygons(it["poly"].difference(all_new.buffer(0.05))) if q.area >= min_a]
                    if not rest:
                        continue
                    it["poly"] = max(rest, key=lambda q: q.area)
                    trimmed += 1
            it["height_m"] = round(it["height_m"], 2)
            if place(it):
                result["existing"].append(it)
        srcs = Counter(i["source"].split(" (")[0] if "usual" not in i["source"] else "usual for its OSM type"
                       for i in result["existing"])
        log(f"buildings: existing: {len(result['existing'])} buildings ({sum(i['poly'].area for i in result['existing']):,.0f} m2) "
            f"from {len(ex_faces)} outlines ({dropped} courtyards / gaps left out); heights: "
            + ", ".join(f"{k} {v}" for k, v in srcs.most_common()))
        if result["demolished"]:
            kinds = Counter(d["by"] for d in result["demolished"])
            warn(f"buildings: {len(result['demolished'])} existing buildings "
                 f"({sum(d['area_m2'] for d in result['demolished']):,.0f} m2) stand where the drawing has "
                 + ", ".join(f"{k} ({v})" for k, v in kinds.most_common()) + ": they are to be demolished (left out, "
                 "listed in the report)")
        if trimmed:
            detail(f"buildings: {trimmed} existing buildings overlap the new development a little (drawing tolerance): "
                   "trimmed to it")

    # ---- underground levels from the documents
    ug = b["underground"]
    levels = docs.get("underground") or []
    if levels and ug["enabled"]:
        top = [shape(levels[0]["polygon"])]
        t = terrain_under(top[0], zf, gt)
        if ug["ground_level"] == "auto":
            gl = round(t[2], 1) if t else None
            gl_src = f"the highest terrain over {levels[0]['level']}'s outline"
        else:
            gl, gl_src = float(ug["ground_level"]), "buildings.underground.ground_level"
        if gl is not None:
            h, slab = float(ug["storey_m"]), float(ug["slab_m"])
            for k, lv in enumerate(levels):
                poly = shape(lv["polygon"])
                floor_z = gl - (k + 1) * h
                tt = terrain_under(poly, zf, gt)
                result["underground"].append({
                    "level": lv["level"], "poly": poly, "floor_z": round(floor_z, 2), "slab_m": slab,
                    "area_m2": lv["area_m2"], "stated_m2": lv.get("stated_m2"), "source": lv["source"],
                    "terrain_min_z": round(tt[1], 2) if tt else None,
                    "below_ground_share": round(float(np.mean(sample_raster(zf, gt, np.asarray(
                        poly.exterior.coords)[:, :2], nan_outside=False) > floor_z + h)), 2) if tt else None})
            log(f"buildings: underground: {len(levels)} levels ({', '.join(l['level'] for l in levels)}) under the "
                f"ground floor at {gl:.1f} m ({gl_src}), {h} m apart; lowest floor {gl - len(levels) * h:.1f} m")
            result["checks"]["underground_ground_level"] = {"z": gl, "source": gl_src}

    # ---- trees
    if roles["trees"]:
        tr = B.trees_of(on_layers(site, roles["trees"]), b)
        if outline is not None and len(tr):
            tr = tr[contains_xy(outline, tr[:, 0], tr[:, 1])]
        occupied = unary_union([i["poly"] for i in result["proposed"] + result["existing"]]) if (
            result["proposed"] or result["existing"]) else None
        if occupied is not None and len(tr):
            tr = tr[~contains_xy(occupied, tr[:, 0], tr[:, 1])]
        zt = sample_raster(zf, gt, tr[:, :2], nan_outside=False) if len(tr) else np.zeros(0)
        hr = float(b["tree_height_per_crown_radius"])
        result["trees"] = [{"x": round(float(x), 3), "y": round(float(y), 3), "z": round(float(zz), 2),
                            "crown_m": round(float(r), 2),
                            "height_m": round(min(float(b["tree_max_height_m"]),
                                                  max(float(b["tree_min_height_m"]), hr * r)), 1)}
                           for (x, y, r), zz in zip(tr, zt) if np.isfinite(zz)]
        log(f"buildings: {len(result['trees'])} trees (crown radius {np.median(tr[:, 2]) if len(tr) else 0:.1f} m typical)")

    for key in ("existing", "proposed", "underground"):
        for it in result[key]:
            it["polygon"] = mapping(it.pop("poly"))
            it["area_m2"] = round(float(shape(it["polygon"]).area), 1) if "area_m2" not in it else it["area_m2"]
    save_json(out, result)
