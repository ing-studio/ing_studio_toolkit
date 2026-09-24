"""Stage roads: the existing streets (OpenStreetMap, fitted to the drawing's kerbs) and the proposed streets (from
the drawing, profile designed to the street rules). Every street surface stops at the buildings (the buildings stage's
footprints): a street never runs into a building. The new buildings' fire access (a street within reach) is checked
here. Result: roads.json (centre lines with stations, heights, widths; carriageway and sidewalk areas; the rule
checks)."""
import math

import numpy as np
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from ..config import settings
from ..geometry.crs import LonLatUTM, Rigid2D
from ..geometry.raster import read_raster
from ..roads import existing as ex_mod
from ..roads import proposed as pr_mod
from ..roads.network import RoadNet
from ..site import load_site, on_layers, polylines
from ..util import detail, file_signature, load_json, log, save_json, skip, warn


def min_grade_stretches(e, min_grade, min_len=20.0):
    """Stretches flatter than the drainage minimum, at least min_len long: [(from s, to s)]."""
    g = np.abs(np.nan_to_num(e["grade"], nan=1.0))
    flat = g < min_grade
    out, start = [], None
    for i, f in enumerate(flat):
        if f and start is None:
            start = i
        if (not f or i == len(flat) - 1) and start is not None:
            end = i if not f else i + 1
            if e["s"][min(end, len(e["s"]) - 1)] - e["s"][start] >= min_len:
                out.append((round(float(e["s"][start]), 1), round(float(e["s"][min(end, len(e["s"]) - 1)]), 1)))
            start = None
    return out


def regrade_existing(ex_edges, ties, grade, tol=0.1):
    """Where a new street end cannot meet an existing street within the rules, the existing street is regraded
    locally: raised / lowered by the mismatch at the join, tapering off at `grade` (so over |mismatch| / grade metres).
    Returns [{at, change_m, over_m}] and changes the existing streets' heights in place."""
    out = []
    for t in ties:
        dz = float(t.get("mismatch_m", 0.0))
        if abs(dz) <= tol:
            continue
        reach = abs(dz) / grade
        p = np.asarray(t["xy"])
        for e in ex_edges:
            d = np.hypot(*(e["xy"] - p).T)
            m = d < reach
            if m.any():
                e["z"] = e["z"] + np.where(m, dz * (1.0 - d / reach), 0.0)
                e["regraded"] = True
        t["regraded_existing_m"] = round(dz, 2)
        t["mismatch_m"] = 0.0
        out.append({"at": t["xy"], "change_m": round(dz, 2), "over_m": round(reach, 1), "street": t["existing"]})
    return out


def run(job, force=False):
    cfg = job.cfg
    out = job.w("roads.json")
    geo, ter = load_json(job.w("georef.json")), load_json(job.w("terrain.json"))
    bj, lj = load_json(job.w("buildings.json")), load_json(job.w("layers.json"))
    if not geo or not ter or bj is None or not lj:
        raise RuntimeError("run the georef, layers, terrain and buildings stages first")
    roles = lj["roles"]
    wanted = {"site": file_signature(job.w("site.pkl")), "terrain": file_signature(job.w("terrain_existing.tif")),
              "georef": geo["transform"], "buildings": file_signature(job.w("buildings.json")), "layers": roles,
              **settings(cfg, "roads"), "fire": cfg["buildings"]["checks"]}
    prev = load_json(out) or {}
    if not force and prev.get("inputs") == wanted:
        skip(f"roads: already built ({len(prev['existing'])} existing, {len(prev['proposed'])} proposed street pieces)")
        return
    site = load_site(job)
    z, gt, _ = read_raster(job.w("terrain_existing.tif"))
    clip = shape(ter["outline"])
    cf = float(cfg["roads"]["profile"]["carriageway_crossfall_permille"]) / 1000.0
    g2u, tr = Rigid2D.from_json(geo["transform"]), LonLatUTM(geo["epsg"])
    warnings = []
    # the buildings that stay (existing ones to be demolished are not among them): streets stop at their walls
    blds = unary_union([shape(it["polygon"]) for k in ("existing", "proposed") for it in bj[k]]) \
        if bj["existing"] or bj["proposed"] else None

    ex_edges, ex_area = [], None
    if cfg["roads"]["existing"]["enabled"]:
        ways = [w for w in load_json(job.w("osm.json"))["ways"] if "highway" in w["tags"]]
        kerbs = polylines(on_layers(site, roles["kerbs"]))
        ex_edges, ex_area = ex_mod.build(ways, lambda ll: g2u.inverse(tr.to_utm(ll)), kerbs, (z, gt), cfg, clip)
        snapped = sum(1 for e in ex_edges if e["width_source"] == "kerbs")
        length = sum(float(e["s"][-1]) for e in ex_edges)
        log(f"roads: existing: {len(ex_edges)} OSM street pieces, {length / 1000:.2f} km; {snapped} fitted to the "
            f"drawing's kerbs ({len(kerbs):,} kerb lines), the others at their OSM / class width")
    existing = RoadNet(ex_edges, ex_area, cf, float(cfg["roads"]["profile"]["junction_blend_m"]))

    pr_edges, car, sw, summary, w = [], None, None, {}, []
    if cfg["roads"]["proposed"]["enabled"]:
        pr_edges, car, sw, summary, w = pr_mod.build(site, roles, cfg, (z, gt), existing, clip, blds)
        rg = cfg["roads"]["existing"].get("regrade_grade_permille")
        if rg and pr_edges and summary.get("tie_ins"):
            done = regrade_existing(ex_edges, summary["tie_ins"], float(rg) / 1000.0)
            if done:
                summary["regraded_existing"] = done
                # the warnings about those joins are answered by the regrading
                w = [m for m in w if not (m.startswith("the street end at") and "off its height" in m)]
                log("roads: existing streets regraded where new streets join them off their height: " + ", ".join(
                    f"{d['street']} at ({d['at'][0]:.0f}, {d['at'][1]:.0f}) {d['change_m']:+.2f} m over {d['over_m']:.0f} m"
                    for d in done))
        warnings += w
        if pr_edges:
            std = summary["standard"]
            log(f"roads: rules: class '{summary['class']}' on {std['terrain']} terrain ({std['terrain_source']}): "
                f"design speed {std['design_speed_kmh']} km/h, lane {std['lane_m']} m, max grade "
                f"{std['max_grade_permille']} per mille"
                + (f" ({std['exceptional_grade_permille']} on up to {std['exceptional_max_length_m']} m)"
                   if std.get("exceptional_grade_permille") else "")
                + f", min radius {std['min_radius_m']} m, vertical curves {std['crest_radius_m']} / {std['sag_radius_m']} m "
                f"({std['source']}); serpentine bends {cfg['roads']['profile']['serpentine_max_grade_permille']} per mille")
            log(f"roads: proposed: {summary['streets']} street pieces, {summary['length_m'] / 1000:.2f} km "
                f"({summary['centre_lines']}), {summary['junctions']} junctions, {len(summary['tie_ins'])} ends tied "
                f"to existing streets")
            if summary.get("exceptional_stretches"):
                detail("roads: the exceptional grade is used on " + ", ".join(
                    f"{x['street']} {x['from_m']:.0f}-{x['to_m']:.0f} m" for x in summary["exceptional_stretches"]))
            min_g = float(cfg["roads"]["profile"]["min_grade_permille"]) / 1000.0
            r_min = float(std["min_radius_m"])
            tight = []
            for e in pr_edges:
                gmax = float(np.nanmax(np.abs(e["grade"]))) * 1000 if len(e["grade"]) > 1 else 0.0
                e["flat_stretches"] = min_grade_stretches(e, min_g)
                cf_ = np.nan_to_num(e["cut_fill"], nan=0.0)
                cut, fill = float(max(0.0, -cf_.min())), float(max(0.0, cf_.max()))
                rmin = float(np.min(e["radius"]))
                e["checks"] = {"length_m": round(float(e["s"][-1]), 1), "max_grade_permille": round(gmax, 1),
                               "limit_permille": round(float(np.max(e["limit"])) * 1000, 1),
                               "min_radius_m": round(rmin, 1) if math.isfinite(rmin) else None,
                               "max_cut_m": round(cut, 2), "max_fill_m": round(fill, 2),
                               "flat_stretches": e["flat_stretches"]}
                if math.isfinite(rmin) and rmin < r_min and e["s"][-1] > 20:
                    tight.append(f"{e['name']} ({rmin:.0f} m)")
                detail(f"roads: {e['name']}: {e['checks']['length_m']} m, max grade {gmax:.1f} per mille, "
                       f"smallest bend radius {rmin:.0f} m, cut up to {cut:.2f} m, fill up to {fill:.2f} m"
                       + (f", flatter than {cfg['roads']['profile']['min_grade_permille']} per mille at "
                          f"{e['flat_stretches']}" if e["flat_stretches"] else ""))
            if tight:
                warnings.append(f"bends tighter than {r_min:.0f} m, the smallest radius at {std['design_speed_kmh']} km/h "
                                f"(drawn so by the architect; treated as serpentine bends, at most "
                                f"{cfg['roads']['profile']['serpentine_max_grade_permille']} per mille): {', '.join(tight)}")
            worst = max((e["checks"]["max_grade_permille"] for e in pr_edges), default=0)
            log(f"roads: proposed profile: steepest grade {worst:.1f} per mille, total height difference to the "
                f"ground {summary['objective_m2']:,.0f} m2" + (", all tie-ins within 0.1 m" if all(
                    abs(t.get("mismatch_m", 0)) <= 0.1 for t in summary["tie_ins"]) else ""))
        else:
            warn(f"roads: no proposed streets found ({summary.get('note', '')})")
    if car is not None and ex_area is not None:
        ex_area = ex_area.difference(car.buffer(0.2))
    # no street surface inside a building
    if blds is not None and not blds.is_empty:
        cut = {}
        for key, geom in (("existing streets", ex_area), ("new carriageways", car), ("new sidewalks", sw)):
            if geom is not None and not geom.is_empty:
                cut[key] = geom.intersection(blds).area
        ex_area = ex_area.difference(blds) if ex_area is not None else None
        car = car.difference(blds) if car is not None else None
        sw = sw.difference(blds) if sw is not None else None
        if any(v > 1.0 for v in cut.values()):
            log("roads: street surfaces cut back at the buildings: " + ", ".join(
                f"{k} {v:,.0f} m2" for k, v in cut.items() if v > 1.0))
        summary["cut_at_buildings_m2"] = {k: round(v, 1) for k, v in cut.items()}
    # fire access of the new buildings: a street within reach (ՀՀՇՆ 30-01-2023)
    ck = cfg["buildings"]["checks"]
    tall = [shape(it["polygon"]) for it in bj["proposed"] if it["storeys"] >= int(ck["min_storeys"])]
    parts = [g for g in (car, ex_area) if g is not None and not g.is_empty]
    streets = unary_union(parts) if parts else None
    if tall and streets is not None:
        merged = unary_union([p.buffer(0.3) for p in tall])
        far = []
        for p in getattr(merged, "geoms", [merged]):
            d = p.distance(streets)
            if d > float(ck["max_to_street_m"]):
                far.append({"at": [round(p.centroid.x, 1), round(p.centroid.y, 1)], "to_street_m": round(d, 1)})
        summary["fire_access"] = {"buildings": len(getattr(merged, "geoms", [merged])), "far_from_street": far,
                                  "max_to_street_m": ck["max_to_street_m"]}
        if far:
            warnings.append(f"{len(far)} new buildings of {ck['min_storeys']}+ storeys stand more than "
                            f"{ck['max_to_street_m']} m from a street: they need a 6 m fire lane: " + ", ".join(
                                f"({f['at'][0]:.0f}, {f['at'][1]:.0f}) {f['to_street_m']:.0f} m" for f in far[:8]))
    for m in warnings:
        warn("roads: " + m)
    save_json(out, {"inputs": wanted,
                    "existing": RoadNet(ex_edges, None, cf).to_json(),
                    "proposed": RoadNet(pr_edges, None, cf).to_json(),
                    "existing_area": mapping(ex_area) if ex_area is not None and not ex_area.is_empty else None,
                    "carriageway_area": mapping(car) if car is not None and not car.is_empty else None,
                    "sidewalk_area": mapping(sw) if sw is not None and not sw.is_empty else None,
                    "summary": {k: v for k, v in summary.items()}, "warnings": warnings})
