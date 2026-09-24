"""Stage layers: what each layer of the site plan holds (buildings, shadows, trees, streets ...), worked out from the
geometry and OpenStreetMap (acad/layers.py). A role fixed in the settings (layers.<role> = name patterns) is taken as
it is; its partner (axes for a carriageway, shadows for buildings) is then searched with it. The existing buildings'
layers are the ones the georef stage matched to OpenStreetMap.
Result: layers.json {roles: {role: [layer]}, evidence: {layer: why}}.
"""
from shapely.geometry import box

from .. import layers as L
from ..config import settings
from ..geometry.crs import LonLatUTM, Rigid2D
from ..site import load_site
from ..util import detail, file_signature, load_json, log, save_json, skip, warn


def run(job, force=False):
    cfg = job.cfg
    out = job.w("layers.json")
    geo = load_json(job.w("georef.json"))
    if not geo:
        raise RuntimeError("run the georef stage first")
    b = cfg["buildings"]
    wanted = {"site": file_signature(job.w("site.pkl")), "georef": geo["transform"],
              "buildings": geo.get("building_layers"), "osm": file_signature(job.w("osm.json")),
              **settings(cfg, "layers"),
              "tree_crown_m": [b["tree_min_crown_m"], b["tree_max_crown_m"]], "max_area_m2": b["max_area_m2"],
              "kerb_search_m": cfg["roads"]["existing"]["kerb_search_m"]}
    prev = load_json(out) or {}
    if not force and prev.get("inputs") == wanted:
        skip("layers: already known (" + ", ".join(f"{k.replace('_', ' ')} {len(v)}" for k, v in prev["roles"].items()
                                                    if v) + ")")
        return
    site = load_site(job)
    by = L.by_layer(site)
    layers = site["layers"]
    osm = load_json(job.w("osm.json")) or {"ways": []}
    g2u, tr = Rigid2D.from_json(geo["transform"]), LonLatUTM(geo["epsg"])
    to_drawing = lambda ll: g2u.inverse(tr.to_utm(ll))
    streets_osm = [w for w in osm["ways"] if "highway" in w["tags"]]
    fixed = {role: L.fixed_role(cfg, role, site) for role in L.ROLES}
    roles, evidence = {}, {}
    taken = lambda: {r for v in roles.values() for r in v}

    def keep(role, found, ev):
        roles[role] = fixed[role] if fixed[role] is not None else L.with_siblings(found, by)
        if fixed[role] is None:
            evidence.update(ev)

    roles["existing_buildings"] = fixed["existing_buildings"] or geo.get("building_layers") or []
    evidence.update({r: "building outlines that match OpenStreetMap's buildings" for r in roles["existing_buildings"]})
    keep("trees", *(L.tree_layers(by, layers, cfg) if fixed["trees"] is None else ([], {})))

    # new streets: axis lines along the middle of a hatch layer's strips
    car, axes, ev = [], [], {}
    if fixed["carriageway"] is None or fixed["axes"] is None:
        osm_lines = L.osm_drawing_lines(streets_osm, to_drawing, cfg["roads"]["existing"]["osm_classes"])
        car, axes, ev = L.street_layers(by, layers, site, cfg, osm_lines, exclude=taken(),
                                        strips_of=fixed["carriageway"], lines_of=fixed["axes"])
    keep("carriageway", car, ev)
    keep("axes", axes, ev)
    car_area = L.area_of([p for r in roles["carriageway"] for p in by.get(r, [])]) if roles["carriageway"] else None
    sw, ev = ([], {})
    if fixed["sidewalks"] is None and car_area is not None:
        sw, ev = L.sidewalk_layers(by, car_area, exclude=taken())
    keep("sidewalks", sw, ev)

    # new buildings: the outlines that cast the drawn shadows
    casters, shadows, direction, ev = [], [], None, {}
    if fixed["proposed_buildings"] is None or fixed["shadows"] is None:
        casters, shadows, direction, ev = L.shadow_layers(by, layers, cfg, exclude=taken(),
                                                          casters_of=fixed["proposed_buildings"],
                                                          shadows_of=fixed["shadows"])
    if not casters and fixed["proposed_buildings"] is None:
        casters, more = L.proposed_by_name(by, layers, cfg, exclude=taken())
        ev.update(more)
    keep("proposed_buildings", casters, ev)
    keep("shadows", shadows, ev)

    kb, ev = ([], {})
    if fixed["kerbs"] is None:
        kb, ev = L.kerb_layers(by, layers, cfg, streets_osm, to_drawing, box(*site["bbox"]), exclude=taken())
    keep("kerbs", kb, ev)

    shown = lambda r: layers.get(r, {}).get("name", r)
    for role in L.ROLES:
        names = roles.get(role, [])
        if names:
            log(f"layers: {role.replace('_', ' ')}: " + ", ".join(dict.fromkeys(L.base_name(shown(r)) for r in names))
                + (" (from the settings)" if fixed[role] is not None else ""))
            for r in names:
                if r in evidence:
                    detail(f"layers:   {shown(r)}: {evidence[r]}")
        else:
            detail(f"layers: {role.replace('_', ' ')}: none found")
    if not roles["carriageway"]:
        warn("layers: no new streets found (no hatch layer with axis lines along its strips) - set layers.carriageway "
             "(and layers.axes) if the drawing has them")
    if not roles["proposed_buildings"]:
        warn("layers: no new buildings found (no drawn shadows, no layer named as new buildings) - set "
             "layers.proposed_buildings if the drawing has them")
    save_json(out, {"inputs": wanted, "roles": roles,
                    "how": {r: "setting" if fixed[r] is not None else "found" for r in L.ROLES},
                    "evidence": {r: e for r, e in evidence.items() if r in taken()},
                    "shadow_direction_deg": direction, "shown": {r: shown(r) for r in taken()}})
