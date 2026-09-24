"""Stage georef: the drawing on the map (UTM of the site's zone), by matching its building outlines to OSM buildings.

Where to look: site.lonlat when it is given; otherwise the places the inputs' names point to (acad/io/geocode.py), best
first. Which layer holds the buildings: layers.existing_buildings when it is given; otherwise the layers with the most
building-like closed shapes (acad/layers.py), a name like 'building' first. Every (place, layer) is tried until one
matches clearly, so a wrong guess costs time but cannot place the drawing wrongly.
Rotation and shift only (scale 1: the drawing unit was decided by the read stage; a wrong unit shows up here as a
failed match). The search tries every rotation (georef.rotation_range_deg) within georef.search_radius_m of a point;
the best one must clearly beat the typical score (peak ratio), then ICP refines it. A place found from a name can be
anywhere in the site plan, and one wide search is not decisive in a dense city (a busy area overlaps anything), so the
plan's reach is covered by windows of that radius, nearest first; a window's best placement is searched again around
itself and accepted only when that search clearly peaks.
Result: georef.json with the transform drawing metres -> UTM and the building layers, and the OSM data (osm.json).
"""
import math

import numpy as np

from .. import layers as L
from ..config import settings
from ..geometry.crs import LonLatUTM, Rigid2D, utm_epsg
from ..geometry.register import densify_polylines, icp, rotation_search, to_rigid
from ..io import geocode
from ..io.osm import fetch
from ..site import load_site, on_layers, polylines
from ..util import detail, file_signature, load_json, log, save_json, skip, warn


def osm_building_points(ways, tr, step=1.0):
    rings = [tr.to_utm(w["lonlat"]) for w in ways if "highway" not in w["tags"]]
    return densify_polylines(rings, step)


def _places(job, site, half):
    """Where to look: [{lonlat, reach (how far the site may be from it), source}]."""
    cfg, g = job.cfg, job.cfg["georef"]
    ll = cfg["site"]["lonlat"]
    if ll not in (None, "auto"):
        return [{"lonlat": ll, "reach": 0.0, "source": "site.lonlat"}]
    texts = [p["text"] for p in site["prims"] if p["kind"] == "text"]
    letters = texts + [info.get("name", raw) for raw, info in site["layers"].items()]
    names = geocode.input_names(job)
    groups, queries, country = geocode.candidates(letters, names, texts, cfg, job.w("geocode.json"))
    log(f"georef: the site's position was not given: looking up the place names {', '.join(queries) or '-'}"
        + (f" in {country.upper()} (from the drawing's letters)" if country else "")
        + f": {len(groups)} candidate place(s)")
    for gr in groups[:int(g["max_places"])]:
        h = max(gr["hits"], key=lambda x: x["importance"])
        detail(f"georef:   {gr['lonlat'][1]:.5f} N, {gr['lonlat'][0]:.5f} E ({', '.join(gr['from'])}: {h['name'][:70]})")
    # the name can belong to anything within the site plan: search as far as the plan reaches
    return [{"lonlat": gr["lonlat"], "reach": half + 200.0,
             "source": f"place names {', '.join(gr['from'])} ({max(gr['hits'], key=lambda x: x['importance'])['name'][:90]})"}
            for gr in groups[:int(g["max_places"])]]


def windows(expected, reach, radius):
    """Centres of search windows covering `reach` around `expected`, nearest first."""
    step = 1.5 * radius
    n = max(0, math.ceil((reach - radius) / step))
    cs = [expected + np.array([i * step, j * step]) for i in range(-n, n + 1) for j in range(-n, n + 1)]
    return sorted(cs, key=lambda c: float(np.hypot(*(c - expected))))


def run(job, force=False):
    cfg = job.cfg
    out = job.w("georef.json")
    auto_place = cfg["site"]["lonlat"] in (None, "auto")
    wanted = {"site": file_signature(job.w("site.pkl")),
              "names": geocode.input_names(job) if auto_place else None,
              **settings(cfg, "site", "georef", "layers.existing_buildings", "layers.hints.existing_buildings")}
    prev = load_json(out) or {}
    if not force and prev.get("inputs") == wanted:
        skip(f"georef: already placed (rotation {prev['transform']['rotation_deg']:.3f} deg, "
             f"match {prev.get('icp', {}).get('within_1m_pct', '-')}% within 1 m)")
        return
    g, site_cfg = cfg["georef"], cfg["site"]
    site = load_site(job)
    bx = site["bbox"]
    half = 0.5 * math.hypot(bx[2] - bx[0], bx[3] - bx[1])
    places = _places(job, site, half)
    if not places:
        raise RuntimeError("georef: could not work out where the site is (no place in the file names or texts was "
                           "found on the map) - give a point near the site: --lonlat LON,LAT")
    by = L.by_layer(site)
    fixed = L.fixed_role(cfg, "existing_buildings", site)
    if fixed:
        layer_sets = [(fixed, "layers.existing_buildings")]
    else:
        cands = L.building_candidates(by, site["layers"], cfg)
        layer_sets = [(L.with_siblings([c[0]], by), f"{c[1]} building-like shapes" + (", named so" if c[3] else ""))
                      for c in cands[:int(g["max_layer_tries"])]]
        if not layer_sets:
            raise RuntimeError("georef: the drawing has no layer with building outlines to match to OpenStreetMap - "
                               "set layers.existing_buildings, or georef.mode=manual")
    result = {"inputs": wanted, "attempts": []}
    rng = float(g["rotation_range_deg"])
    radius, need = float(g["search_radius_m"]), float(g["min_peak_ratio"])
    angles = np.arange(-rng, rng + 1e-9, 2.0)
    found = None
    for place in places:
        lonlat = place["lonlat"]
        epsg = utm_epsg(*lonlat)
        tr = LonLatUTM(epsg)
        expected = tr.to_utm([lonlat])[0]
        wins = windows(expected, place["reach"], radius)
        far = max(float(np.abs(c - expected).max()) for c in wins)
        reach = far + radius + half + float(site_cfg["osm_margin_m"])
        corners = np.array([[expected[0] - reach, expected[1] - reach], [expected[0] + reach, expected[1] + reach]])
        ll = tr.to_lonlat(corners)
        ways = fetch(cfg, (ll[0, 0], ll[0, 1], ll[1, 0], ll[1, 1]), job.w("osm.json"))
        if g["mode"] == "manual":
            found = (place, epsg, tr, None, None, None)
            break
        Q = osm_building_points(ways, tr)
        Q = Q[(np.abs(Q - expected) <= reach).all(axis=1)]
        if len(Q) < 200:
            detail(f"georef: OpenStreetMap has too few buildings around {lonlat[1]:.4f} N, {lonlat[0]:.4f} E")
            result["attempts"].append({"place": place["source"], "note": "too few OSM buildings"})
            continue
        for names, why in layer_sets:
            P = densify_polylines(polylines(on_layers(site, names)), 1.0)
            if len(P) < 200:
                continue
            log(f"georef: matching {', '.join(dict.fromkeys(L.base_name(n) for n in names))} ({why}) to {len(Q):,} OSM "
                f"building points around {lonlat[1]:.4f} N, {lonlat[0]:.4f} E"
                + (f" ({len(wins)} windows of {radius:.0f} m)" if len(wins) > 1 else "") + " ...")
            best = 0.0
            for c in wins:
                coarse = rotation_search(P, Q, 2.0, angles, c, radius)
                ratio = coarse["peak_ratio"]
                if ratio < need and ratio >= 0.7 * need:  # promising: search again around that placement
                    again = rotation_search(P, Q, 2.0, angles, coarse["T"], radius)
                    detail(f"georef:   window ({c[0] - expected[0]:+.0f}, {c[1] - expected[1]:+.0f}) m: peak ratio "
                           f"{ratio:.2f}, around its best {again['peak_ratio']:.2f}")
                    coarse, ratio = again, again["peak_ratio"]
                elif len(wins) > 1:
                    detail(f"georef:   window ({c[0] - expected[0]:+.0f}, {c[1] - expected[1]:+.0f}) m: peak ratio {ratio:.2f}")
                best = max(best, ratio)
                if ratio >= need:
                    found = (place, epsg, tr, names, P, (Q, coarse))
                    break
            result["attempts"].append({"place": place["source"], "layers": names, "peak_ratio": round(best, 2)})
            detail(f"georef: best peak ratio {best:.2f} (needs {need})")
            if found:
                break
        if found:
            break
    if found is None:
        raise RuntimeError("georef: no clear match between the drawing and OpenStreetMap ("
                           + "; ".join(f"{a.get('place')}: {a.get('peak_ratio', a.get('note'))}" for a in result["attempts"])
                           + "). Give the site's position (--lonlat LON,LAT), check the drawing unit (--units), or place "
                             "it by hand: georef.mode=manual")
    place, epsg, tr, names, P, match = found
    result.update({"epsg": epsg, "site_lonlat": place["lonlat"], "lonlat_source": place["source"],
                   "building_layers": names})
    if g["mode"] == "manual":
        rigid = Rigid2D(math.radians(float(g["manual_rotation_deg"])), *g["manual_origin_utm"])
        log(f"georef: manual placement: rotation {g['manual_rotation_deg']} deg, drawing 0,0 = UTM {g['manual_origin_utm']}")
        result["method"] = "manual"
        cands = [] if fixed else L.building_candidates(by, site["layers"], cfg)
        result["building_layers"] = fixed or (L.with_siblings([cands[0][0]], by) if cands else [])
    else:
        Q, coarse = match
        fine = rotation_search(P, Q, 1.0, np.arange(coarse["angle_deg"] - 2, coarse["angle_deg"] + 2.001, 0.1),
                               coarse["T"], 15.0)
        detail(f"georef: best rotation {fine['angle_deg']:.2f} deg, peak ratio {coarse['peak_ratio']:.2f}")
        start = to_rigid(fine)
        rigid, stats = icp(P, Q, start)
        moved = float(np.max(np.hypot(*(rigid.apply(P) - start.apply(P)).T)))
        if moved > 5.0:
            warn(f"georef: ICP moved the drawing by up to {moved:.1f} m - kept the correlation result")
            rigid = start
            stats = {"note": "icp rejected"}
        result.update({"method": "osm_buildings", "peak_ratio": coarse["peak_ratio"],
                       "coarse_scores": coarse["scores"][:40], "icp": stats, "points": {"drawing": len(P), "osm": len(Q)}})
        log(f"georef: placed: rotation {math.degrees(rigid.angle):.3f} deg, drawing 0,0 = UTM "
            f"({rigid.t[0]:,.2f}, {rigid.t[1]:,.2f}); {stats.get('within_1m_pct')}% of the outlines within 1 m of OSM, "
            f"median {stats.get('median_m')} m; building outlines: {', '.join(dict.fromkeys(L.base_name(n) for n in names))}")
    centre = rigid.apply([[(bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2]])[0]
    result.update({"transform": rigid.to_json(), "site_centre_utm": centre.tolist(),
                   "site_centre_lonlat": tr.to_lonlat([centre])[0].tolist(),
                   "grid_convergence_deg": _convergence(tr, centre)})
    save_json(out, result)


def _convergence(tr, xy):
    """Angle from grid north to true north at xy (degrees): a local survey aligned to true north is rotated by it."""
    a = tr.to_lonlat([xy])[0]
    b = tr.to_utm([[a[0], a[1] + 0.001]])[0]
    return math.degrees(math.atan2(b[0] - xy[0], b[1] - xy[1]))
