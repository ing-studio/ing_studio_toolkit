"""Stage archicad: write <drawing>_FromDWG.pln in the output folder.

Contents (plan coordinates = the drawing's, in metres; heights = altitude - z reference, which is set as the project
zero altitude):
  Site - Terrain              ONE mesh: the terrain made to fit the streets (earthworks stage)
  Site - Roads existing       street surfaces: grey solids (surface 'Site - Asphalt') on the existing streets' profile
  Site - Roads proposed       the new carriageways, crowned, on their designed profile, with their aprons and
                              driveways (grey solids)
  Site - Sidewalks proposed   sidewalks, a kerb height above the carriageway (light grey solids)
  Site - Road centre lines    centre lines of all streets (plan)
  Site - Retaining walls      the walls the streets need (Morph solids)
  Site - Buildings existing / proposed, Site - Underground levels   Morph solids
  Site - Trees                library objects (archicad.tree_objects), sized to the drawn crown
  DWG - <layer>               the drawing itself: lines, arcs, circles, fills, texts on the drawing's layers
Layering: the street bodies are exactly the earthworks stage's paved areas and surfaces, and lie ON the terrain: a
carriageway body is pavement_m thick, a sidewalk body kerb + pavement_m (its side facing the carriageway is the kerb),
a bridge deck bridge_deck_m. The mesh follows their undersides: its vertices under the paving are the same grid the
bodies are triangulated on, the paving's outer edge is a mesh line at their underside, and a second line just outside
it lifts the ground flush with their top. No street, sidewalk or tree stands inside a building (the roads stage cut the
surfaces back at the buildings; trees on a carriageway are left out). Everything on 'Site - ' and 'DWG - ' layers is
deleted first, so the file always holds one version. The PLN starts as a copy of Archicad's template (the relief
tool's rule) unless an Archicad has it open.
"""
import math
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from shapely import contains_xy, segmentize, set_precision
from shapely.geometry import LineString, Point, box, shape
from shapely.ops import unary_union

from ..archicad import elements as el
from ..archicad import site_writer as sw
from ..archicad.client import ArchicadError, eid
from ..archicad.session import connect_project, forget_project, project_is_open
from ..config import settings
from ..geometry.crs import LonLatUTM, Rigid2D
from ..geometry.raster import nearest_fill, read_raster, sample_raster
from ..geometry.bodies import GRID_OFFSET, prism, surface_body
from ..geometry.terrain_mesh import adaptive_points
from ..roads.geometry import as_polygons, rings_to_polygons
from ..site import load_site
from ..util import detail, file_signature, load_json, log, ok, save_json, skip, tool, warn
from .buildings import terrain_under


def tiles(poly, size):
    """A polygon cut into pieces of at most size x size (big street areas become several bodies)."""
    x0, y0, x1, y1 = poly.bounds
    if x1 - x0 <= size and y1 - y0 <= size:
        return [poly]
    out = []
    for x in np.arange(x0, x1, size):
        for y in np.arange(y0, y1, size):
            out += [q for q in as_polygons(poly.intersection(box(x, y, x + size, y + size))) if q.area > 0.5]
    return out


def pinches(poly):
    """Points where a polygon's outline touches itself (a hole touching the edge, a bow tie): nodes of its boundary
    where more than two edges meet."""
    from collections import Counter
    noded = unary_union(poly.boundary)
    ends = Counter()
    for line in getattr(noded, "geoms", [noded]):
        c = line.coords
        ends[tuple(np.round(c[0], 4))] += 1
        ends[tuple(np.round(c[-1], 4))] += 1
    return [p for p, k in ends.items() if k > 2]


def solid_parts(poly, grid=0.01):
    """A polygon made fit for a solid body: vertices on a 1 cm grid (no slivers between vertices mm apart), and no
    point where its outline touches itself (not a closed body): a 3 cm disc is filled in there."""
    out = []
    for p in as_polygons(set_precision(poly, grid)):
        touch = pinches(p)
        if touch:
            p = set_precision(unary_union([p] + [Point(q).buffer(3 * grid, quad_segs=2) for q in touch]), grid)
        # the coordinates stay on the grid, but the grid is not kept with the polygon: later cuts (the body's cells)
        # would snap to it too
        out += [set_precision(q, 0.0) for q in as_polygons(p) if q.area >= 0.5]
    return out


def _prepare_output(job):
    out = Path(job.output_pln)
    if out.exists() and project_is_open(job.cfg["archicad"]["host"], out):
        log("archicad: the PLN is open in Archicad, so it is not recreated; its Site / DWG layers are replaced")
        return
    template = tool(job.cfg, "archicad_template")
    log(f"archicad: new PLN from {template}")
    out.parent.mkdir(parents=True, exist_ok=True)
    forget_project(out)
    Path(str(out) + ".lck").unlink(missing_ok=True)
    shutil.copyfile(template, out)


SITE_LAYER_KEYS = ("layer_terrain", "layer_roads_existing", "layer_roads_proposed", "layer_sidewalks", "layer_road_lines",
                   "layer_walls", "layer_buildings_existing", "layer_buildings_proposed", "layer_underground",
                   "layer_trees")


def _layer_name(prefix, shown):
    name = "".join(c for c in shown if c.isprintable()).strip() or "0"
    return (prefix + name)[:120]


# --------------------------------------------------------------------------- mesh building
class MeshWriter:
    """Mesh payloads with heights relative to the z reference and the way this Archicad takes vertex z."""

    def __init__(self, floor, z_ref, story_level, z_relative, point_mode):
        self.floor, self.z_ref, self.story = floor, z_ref, story_level
        self.relative, self.mode = z_relative, point_mode

    def data(self, ring, holes, lines, points, level, skirt_type, skirt, extra=None):
        off = self.z_ref + self.story + (level if self.relative else 0.0)
        f = lambda a: sw.xyz_list(np.column_stack([a[:, 0], a[:, 1], a[:, 2] - off]))
        d = {"floorIndex": self.floor, "level": level, "skirtType": skirt_type, "skirtLevel": skirt,
             "polygonCoordinates": f(ring)}
        if holes:
            d["holes"] = [{"polygonCoordinates": f(h)} for h in holes]
        subs = [{"coordinates": f(l)} for l in lines if len(l) >= 2]
        if points is not None and len(points):
            pts = f(points)
            if self.mode == "single":
                subs += [{"coordinates": [c]} for c in pts]
            else:
                subs += [{"coordinates": [c, dict(c, x=c["x"] + 0.01)]} for c in pts]
        if subs:
            d["sublines"] = subs
        if extra:
            d.update(extra)
        return d


def ring3(ring, zf):
    xy = np.asarray(ring.coords)[:-1, :2]
    return np.column_stack([xy, zf(xy)])


def sampler(arr, mask, gt):
    """Bilinear sampler of arr's values on `mask`, carried on beyond it by the nearest such value (so a surface can be
    sampled right up to its edge without mixing in its neighbour's heights); None when the mask is empty."""
    ok = mask & np.isfinite(arr)
    if not ok.any():
        return None
    full = nearest_fill(np.where(ok, arr, 0.0), ok)
    return lambda xy: sample_raster(full, gt, np.asarray(xy, dtype=np.float64).reshape(-1, 2), nan_outside=False)


def open_rings(geom, step):
    """The rings of a (multi)polygon, a vertex at least every `step`, each as two open lines (a mesh line does not
    close on itself)."""
    out = []
    for poly in as_polygons(segmentize(geom, step)):
        for ring in [poly.exterior] + list(poly.interiors):
            c = np.asarray(ring.coords)[:, :2]
            if len(c) >= 4:
                m = len(c) // 2
                out += [c[:m + 1], c[m:]]
    return out


def with_z(lines, zf):
    return [np.column_stack([l, zf(l)]) for l in lines]


def clip_lines(lines, poly):
    out = []
    for l in lines:
        inside = contains_xy(poly, l[:, 0], l[:, 1])
        run = []
        for p, k in zip(l, inside):
            if k:
                run.append(p)
            elif len(run) >= 2:
                out.append(np.array(run))
                run = []
            else:
                run = []
        if len(run) >= 2:
            out.append(np.array(run))
    return out


# --------------------------------------------------------------------------- 2D drawing
def drawing_items(site, layer_index, pen_of, solid, text_scale, floor):
    """Create-command payloads for the site plan's primitives: {command: (key, items)}."""
    polys, arcs, circles, hatches, texts, spots = [], [], [], [], [], []
    for p in site["prims"]:
        L = layer_index.get(p["layer"])
        if L is None:
            continue
        pen = pen_of(p["color"], p["rgb"])
        k = p["kind"]
        if k == "poly":
            xy = np.vstack([p["xy"], p["xy"][:1]]) if p["closed"] else p["xy"]
            xy = sw.clean_xy(xy)
            if len(xy) >= 2:
                polys.append({"floorInd": floor, "layerIndex": L, "linePenIndex": pen, "coordinates": sw.xy_list(xy)})
        elif k == "arc":
            arcs.append({"floorInd": floor, "layerIndex": L, "linePenIndex": pen, "origin": sw.xy_list([p["c"]])[0],
                         "radius": round(float(p["r"]), 4), "begAngle": float(p["a0"]), "endAngle": float(p["a1"])})
        elif k == "circle":
            circles.append({"floorInd": floor, "layerIndex": L, "linePenIndex": pen, "origin": sw.xy_list([p["c"]])[0],
                            "radius": round(float(p["r"]), 4)})
        elif k == "fill":
            area = rings_to_polygons(p["rings"], min_area=0.01)
            for poly in as_polygons(area):
                clean = poly.simplify(0.005)
                clean = clean if clean.is_valid else clean.buffer(0)
                for piece in (q for part in as_polygons(clean) for q in sw.without_holes(part)):
                    piece = piece.buffer(0)
                    if piece.is_empty or piece.area < 0.01 or piece.geom_type != "Polygon":
                        continue
                    for ring in sw.hatch_rings(piece):
                        h = {"floorInd": floor, "layerIndex": L, "coordinates": sw.xy_list(ring),
                             "contourPenIndex": pen, "fillPenIndex": pen}
                        if p["solid"] and solid:
                            h["fillId"] = solid
                        hatches.append(h)
        elif k == "text":
            texts.append({"coordinate": {"x": round(float(p["xy"][0]), 4), "y": round(float(p["xy"][1]), 4), "z": 0.0},
                          "text": p["text"], "height": round(max(0.5, p["h"] * 1000.0 / text_scale), 2),
                          "angle": float(p["rot"]), "justification": p["just"], "pen": pen, "floorIndex": floor,
                          "_layer": L})
        elif k == "point":
            spots.append({"floorInd": floor, "layerIndex": L, "position": sw.xy_list([p["xy"]])[0], "penIndex": pen})
    return [("CreateHatches", "hatchesData", hatches, "fills"), ("CreatePolylines", "polylinesData", polys, "lines"),
            ("CreateArcs", "arcsData", arcs, "arcs"), ("CreateCircles", "circlesData", circles, "circles"),
            ("CreateTexts", "textsData", texts, "texts"), ("CreateHotspots", "hotspotsData", spots, "points")]


def site_geometry(job, ter, ew):
    """Everything the PLN is built from that needs no Archicad: the design terrain, the z reference, the paving as
    body pieces with their surfaces, and the terrain mesh's lines and points (also used by the checks)."""
    cfg, a = job.cfg, job.cfg["archicad"]
    prof = cfg["roads"]["profile"]
    pav, kerb = float(prof["pavement_m"]), float(prof["kerb_m"])
    deck = float(cfg["roads"]["earthworks"]["bridge_deck_m"])
    z1, gt, _ = read_raster(job.w("terrain_design.tif"))
    zfilled = nearest_fill(z1, np.isfinite(z1))
    zf = lambda xy: sample_raster(zfilled, gt, xy, nan_outside=False)
    z_ref = a["z_reference"]
    if z_ref == "auto":
        z_ref = math.floor(float(np.nanmin(z1)) / 10.0) * 10.0
    z_ref = float(z_ref)
    outline = shape(ter["outline"])
    inner = outline.buffer(-0.5)
    # ---- the paving (earthworks: its areas and surfaces) as the bodies will have it, and the terrain under it
    S = np.load(job.w("surfaces.npz"))
    on_ground = (S["EX"] | S["CAR"] | S["SW"]) & ~S["BRIDGE"]
    # each surface on its cells and the ring the earthworks stage computed around them: smooth up to its edge
    top_at = {k: sampler(S[t], np.isfinite(S[t]), gt) if S[m].any() else None
              for k, t, m in (("existing", "top_ex", "EX"), ("carriageway", "top_car", "CAR"), ("sidewalks", "top_sw", "SW"))}
    beside_at = sampler(z1, ~on_ground, gt)     # the terrain around the paving
    finished = z1.copy()                        # the ground to stand on: the paving's top where there is paving
    for key, m in (("top_ex", "EX"), ("top_car", "CAR"), ("top_sw", "SW")):
        finished[S[m]] = S[key][S[m]]
    finished_at = sampler(finished, np.isfinite(finished), gt)
    bridge_area = shape(ew["bridge_area"]) if ew.get("bridge_area") else None
    thick = {"existing": pav, "carriageway": pav, "sidewalks": kerb + pav}
    pieces = {}  # kind -> [(polygon, thickness, on a bridge)]
    for kind, g in ((k, shape(ew["paved"][k]) if ew["paved"].get(k) else None) for k in thick):
        if g is None or top_at[kind] is None:
            continue
        out = []
        for poly in as_polygons(g):
            q = poly.simplify(0.05)
            for part in as_polygons(q if q.is_valid else q.buffer(0)):
                if bridge_area is not None and part.intersects(bridge_area):
                    out += [(p, thick[kind], False) for p in as_polygons(part.difference(bridge_area))]
                    out += [(p, deck, True) for p in as_polygons(part.intersection(bridge_area))]
                else:
                    out.append((part, thick[kind], False))
        pieces[kind] = [x for x in out if x[0].area >= 2.0]
    cell = float(a["road_cell_m"])
    # the terrain mesh under the paving = the bodies' undersides: under each piece the grid its body is triangulated
    # on and a line just inside its edge (inset_m), at that body's underside, so where two pieces meet at different
    # levels the terrain steps between them without rising into either; paving_edge_gap_m outside the paving a line
    # at the ground around it (which meets the paving's top flush)
    tcfg = cfg["terrain"]
    step, gap, inset = float(tcfg["outline_step_m"]), float(a["paving_edge_gap_m"]), 0.1
    under = {k: (lambda xy, k=k: top_at[k](xy) - thick[k]) for k in pieces}
    U = unary_union([p for v in pieces.values() for p, _, b in v if not b]).intersection(inner)
    mesh_lines, grid_pts = [], []
    if not U.is_empty:
        for k, v in pieces.items():
            for poly, _, on_bridge in v:
                core = poly.intersection(inner).buffer(-inset, join_style=2, mitre_limit=2.0)
                if on_bridge or core.is_empty:
                    continue
                mesh_lines += clip_lines(with_z(open_rings(core, step), under[k]), inner)
                x0, y0, x1, y1 = core.bounds
                gx, gy = np.meshgrid(np.arange(math.floor(x0 / cell) * cell + GRID_OFFSET, x1 + cell, cell),
                                     np.arange(math.floor(y0 / cell) * cell + GRID_OFFSET, y1 + cell, cell))
                m = contains_xy(core.buffer(-0.3), gx, gy)
                if m.any():
                    q = np.column_stack([gx[m], gy[m]])
                    grid_pts.append(np.column_stack([q, under[k](q)]))
        mesh_lines += clip_lines(with_z(open_rings(U.buffer(gap, join_style=2, mitre_limit=2.0), step), beside_at), inner)
    grid_pts = np.vstack(grid_pts) if grid_pts else np.zeros((0, 3))
    valid = np.isfinite(z1) & contains_xy(inner, *np.meshgrid(
        gt[0] + (np.arange(z1.shape[1]) + 0.5) * gt[1], gt[3] + (np.arange(z1.shape[0]) + 0.5) * gt[5]))
    tol, pts = adaptive_points(z1, gt, valid, tcfg)
    if not U.is_empty:
        pts = pts[~contains_xy(U.buffer(gap + 0.3), pts[:, 0], pts[:, 1])]
    if mesh_lines:
        d, _ = cKDTree(np.vstack([l[:, :2] for l in mesh_lines])).query(pts[:, :2])
        pts = pts[d > 0.75]
    pts = np.vstack([pts, grid_pts])

    return {"z1": z1, "gt": gt, "zfilled": zfilled, "zf": zf, "z_ref": z_ref, "outline": outline, "pieces": pieces,
            "top_at": top_at, "under": under, "finished_at": finished_at, "mesh_lines": mesh_lines,
            "grid_pts": grid_pts, "pts": pts, "tol": tol, "step": step, "cell": cell}


# --------------------------------------------------------------------------- stage
def run(job, force=False):
    cfg, a = job.cfg, job.cfg["archicad"]
    result_path = job.w("archicad.json")
    ter, roads, ew, geo = (load_json(job.w(n)) for n in ("terrain.json", "roads.json", "earthworks.json", "georef.json"))
    if not all((ter, roads, ew, geo)):
        raise RuntimeError("run the earlier stages first (terrain, roads, earthworks)")
    wanted = {"design": file_signature(job.w("terrain_design.tif")), "roads": file_signature(job.w("roads.json")),
              "site": file_signature(job.w("site.pkl")),
              "buildings": file_signature(job.w("buildings.json")) if job.w("buildings.json").exists() else None,
              "earthworks": file_signature(job.w("earthworks.json")), **settings(cfg, "archicad", "terrain")}
    prev = load_json(result_path) or {}
    if not force and prev.get("saved") and prev.get("inputs") == wanted and Path(job.output_pln).exists():
        skip(f"archicad: {Path(job.output_pln).name} already holds this site model (--force redoes it)")
        return
    G = site_geometry(job, ter, ew)
    z1, gt, zfilled, zf, z_ref, outline = (G[k] for k in ("z1", "gt", "zfilled", "zf", "z_ref", "outline"))
    pieces, top_at, finished_at, cell = G["pieces"], G["top_at"], G["finished_at"], G["cell"]
    mesh_lines, grid_pts, pts, tol, step = (G[k] for k in ("mesh_lines", "grid_pts", "pts", "tol", "step"))
    site = load_site(job)


    _prepare_output(job)
    sw.FAILED.clear()
    ac = sw.make_patient(connect_project(job, job.output_pln))
    missing = ac.missing_tapir_commands(sw.NEEDED)
    if missing:
        raise ArchicadError(f"Tapir commands missing: {', '.join(missing)} - update Tapir (dwg2ac.bat addon install)")
    floor = 0
    # element lists come from the view that is active in Archicad: the floor plan holds the 2D elements too
    ac.tapir("ChangeWindow", {"windowType": "FloorPlan", "storyIndex": floor}, timeout=600)
    removed = sw.remove_on_layers(ac, (a["layer_prefix_site"], a["layer_prefix_dwg"]))
    if removed:
        ours = {i for n, i in el.layer_indices(ac).items() if n.startswith((a["layer_prefix_site"], a["layer_prefix_dwg"]))}
        left = sw.count_on_layers(ac, ours)
        if sum(left.values()):
            raise ArchicadError(f"elements of an earlier run could not be deleted ({left}) - is a view other than the "
                                "floor plan active, or are layers locked? Nothing was added, project NOT saved")
        log("archicad: deleted the elements of an earlier run")
    story = el.story_level(ac, floor)
    result = {"output_pln": job.output_pln, "saved": False, "inputs": wanted, "z_reference": z_ref, "created": {}}

    # ---- layers
    site_layers = {k: a[k] for k in SITE_LAYER_KEYS}
    used = Counter(p["layer"] for p in site["prims"]) if a["two_d"] else Counter()
    dwg_names = {raw: _layer_name(a["layer_prefix_dwg"], site["layers"].get(raw, {}).get("name", raw)) for raw in used}
    hidden = {dwg_names[r] for r in used if site["layers"].get(r, {}).get("off") or site["layers"].get(r, {}).get("frozen")}
    all_names = list(site_layers.values()) + sorted(set(dwg_names.values()))
    ac.tapir("CreateLayers", {"layerDataArray": [{"name": n, "isHidden": n in hidden, "isLocked": False}
                                                 for n in all_names], "overwriteExisting": True})
    idx = el.layer_indices(ac)
    L = {k: idx[n] for k, n in site_layers.items()}
    dwg_L = {raw: idx[n] for raw, n in dwg_names.items() if n in idx}
    detail(f"archicad: {len(all_names)} layers ({len(dwg_L)} from the drawing)")

    # ---- the terrain mesh
    rel, mode = el.probe_mesh(ac, floor, story)
    mw = MeshWriter(floor, z_ref, story, rel, mode)
    dense = segmentize(outline, step)
    ring = ring3(dense.exterior, zf)
    holes = [ring3(h, zf) for h in dense.interiors]
    all_z = np.concatenate([ring[:, 2], pts[:, 2]] + [l[:, 2] for l in mesh_lines])
    level = math.floor(float(all_z.min()) - z_ref - story) - 1.0
    extra = {"ridges": a["mesh_ridges"], "showLines": False}
    if a["favorite_terrain"]:
        extra["favoriteName"] = a["favorite_terrain"]
    mesh = mw.data(ring, holes, mesh_lines, pts, level, a["mesh_skirt_type"], float(a["mesh_skirt_depth_m"]), extra)
    log(f"archicad: terrain mesh: outline {len(ring):,}, {len(pts):,} points ({len(grid_pts):,} of them under the "
        f"paving; tolerance {tol:.2f} m elsewhere), {len(mesh_lines)} lines along the paving's edges ...")
    guids = el.created("terrain mesh", ac.tapir("CreateMeshes", {"meshesData": [mesh]}, timeout=3600).get("elements", []))
    if len(guids) != 1:
        raise ArchicadError("the terrain mesh could not be created - project NOT saved")
    el.set_layer(ac, guids, L["layer_terrain"], 500)
    result["created"]["terrain"] = guids
    terrain_bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(guids[0])]})["boundingBoxes3D"][0].get("boundingBox3D")
    expect_top = float(all_z.max()) - z_ref
    detail(f"archicad: terrain top at {terrain_bb and round(terrain_bb['zMax'], 2)} m (expected {expect_top:.2f})")
    if terrain_bb is None or abs(terrain_bb["zMax"] - expect_top) >= 0.1:
        raise ArchicadError("the terrain mesh is not at the expected height - project NOT saved")

    # ---- 3D bodies: Morph solids with their surfaces (streets, sidewalks, walls, buildings), trees as objects
    m_off = el.probe_morph(ac, floor)
    kind = sw.probe_solid(ac, floor)
    surf = sw.make_surfaces(ac, a["surfaces"])
    zm = lambda z: float(z) - z_ref
    bodies = {}
    for pkind, key, layer, skey, label in (
            ("existing", "roads_existing", "layer_roads_existing", "roads", "existing streets"),
            ("carriageway", "roads_proposed", "layer_roads_proposed", "roads", "new carriageways"),
            ("sidewalks", "sidewalks", "layer_sidewalks", "sidewalks", "sidewalks")):
        items = []
        for poly, t, _ in pieces.get(pkind, []):
            for piece in (q for tile in tiles(poly, 150.0) for q in solid_parts(tile)):  # each body stays light
                if piece.area < 2.0:
                    continue
                v, f = surface_body(piece, lambda xy, k=pkind: top_at[k](xy) - z_ref, t, cell)
                if f:
                    items.append(sw.morph_item(v, f, floor, m_off, kind, L[layer], surf.get(skey)))
        if items:
            bodies[key] = (items, label)
    lines = [{"floorInd": floor, "layerIndex": L["layer_road_lines"], "linePenIndex": 1 if e["kind"] == "proposed" else 3,
              "coordinates": sw.xy_list(e["xy"])} for e in roads["proposed"] + roads["existing"] if len(e["xy"]) >= 2]
    result["created"]["centre_lines"] = sw.batched_create(ac, "CreatePolylines", "polylinesData", lines, 500, "centre lines")

    bj = load_json(job.w("buildings.json")) or {}
    embed = float(cfg["buildings"]["embed_m"])
    for key, layer in (("proposed", "layer_buildings_proposed"), ("existing", "layer_buildings_existing")):
        items = []
        for it in bj.get(key, []):
            for poly in as_polygons(shape(it["polygon"]).simplify(0.05).buffer(0)):
                if poly.area < 1.0:
                    continue
                # down to the ground around it too: a street cut beside a building must not leave a gap under it
                around = terrain_under(poly.buffer(1.5), zfilled, gt)
                bottom = min(it["bottom_z"], around[1] - embed) if around else it["bottom_z"]
                v, f = prism(poly, zm(bottom), zm(it["top_z"]))
                items.append(sw.morph_item(v, f, floor, m_off, kind, L[layer], surf.get(f"buildings_{key}")))
        bodies[f"buildings_{key}"] = (items, f"{key} buildings")
    items = []
    for lv in bj.get("underground", []):
        for poly in as_polygons(shape(lv["polygon"]).simplify(0.1).buffer(0)):
            v, f = prism(poly, zm(lv["floor_z"] - lv["slab_m"]), zm(lv["floor_z"]))
            items.append(sw.morph_item(v, f, floor, m_off, kind, L["layer_underground"], surf.get("underground")))
    bodies["underground_levels"] = (items, "underground levels")
    items = []
    half = float(cfg["roads"]["earthworks"]["wall_thickness_m"]) / 2.0
    for seg in (ew.get("retaining_walls") or {}).get("segments") or []:
        poly = LineString(seg["xy"]).buffer(half, cap_style=2, join_style=2)
        v, f = prism(poly, zm(seg["bottom"]), zm(seg["top"]))
        items.append(sw.morph_item(v, f, floor, m_off, kind, L["layer_walls"], surf.get("walls")))
    bodies["retaining_walls"] = (items, "retaining walls")
    for key, (items, label) in bodies.items():
        if items:
            result["created"][key] = sw.batched_create(ac, "CreateMorphs", "morphsData", items, 20, label)
    log(f"archicad: 3D bodies ({kind} Morphs): " + ", ".join(f"{label} {len(result['created'].get(k, [])):,}"
                                                             for k, (items, label) in bodies.items() if items))
    # the tallest new building must stand where it was asked to
    made = result["created"].get("buildings_proposed") or []
    if made and len(made) == len(bodies["buildings_proposed"][0]):
        k = int(np.argmax([max(v["z"] for v in it["body"]["vertices"]) for it in bodies["buildings_proposed"][0]]))
        want = max(v["z"] for v in bodies["buildings_proposed"][0][k]["body"]["vertices"]) - m_off
        bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(made[k])]})["boundingBoxes3D"][0].get("boundingBox3D")
        detail(f"archicad: tallest new building: top at {bb and round(bb['zMax'], 2)} m (expected {want:.2f})")
        if bb is None or abs(bb["zMax"] - want) > 0.1:
            raise ArchicadError("a building is not at the expected height - project NOT saved")
        result["building_check"] = {"top_m": bb["zMax"], "expected_m": want}

    # ---- trees: library objects, on the finished ground, none on a carriageway
    trees = bj.get("trees", [])
    if trees:
        part = sw.library_part(ac, a["tree_objects"])
        if part is None:
            warn(f"archicad: none of the tree library parts {a['tree_objects']} is in the project's library - no trees")
        else:
            roadway = unary_union([shape(roads[k]) for k in ("carriageway_area", "existing_area") if roads.get(k)])
            xy = np.array([[t["x"], t["y"]] for t in trees])
            on_road = contains_xy(roadway, xy[:, 0], xy[:, 1]) if not roadway.is_empty else np.zeros(len(xy), bool)
            zt = finished_at(xy)
            o_off = sw.probe_object(ac, floor, part)
            items = [{"libraryPartName": part, "floorIndex": floor, "_layer": L["layer_trees"],
                      "coordinates": {"x": t["x"], "y": t["y"], "z": round(float(z) - z_ref + o_off, 3)},
                      "dimensions": {"x": 2 * t["crown_m"], "y": 2 * t["crown_m"], "z": t["height_m"]}}
                     for t, z, r in zip(trees, zt, on_road) if not r]
            result["created"]["trees"] = sw.batched_create(ac, "CreateObjects", "objectsData", items, 200, "trees")
            result["trees_on_streets_left_out"] = int(on_road.sum())
            log(f"archicad: {len(result['created']['trees']):,} trees ({part})"
                + (f"; {int(on_road.sum())} standing on a carriageway left out" if on_road.any() else ""))
    # ---- the drawing in 2D
    if a["two_d"]:
        pen_of, _ = sw.pen_mapper(ac)
        solid = sw.solid_fill_id(ac)
        for cmd, key, items, label in drawing_items(site, dwg_L, pen_of, solid, float(a["text_scale"]), floor):
            if items:
                result["created"][f"dwg_{label}"] = sw.batched_create(ac, cmd, key, items, int(a["batch_size"]),
                                                                      f"drawing {label}")

    # ---- place on the map (best effort)
    try:
        g2u, tr = Rigid2D.from_json(geo["transform"]), LonLatUTM(geo["epsg"])
        o = g2u.apply([[0.0, 0.0]])[0]
        lon, lat = tr.to_lonlat([o])[0]
        zone = geo["epsg"] % 100
        ac.tapir("SetGeoLocation", {"projectLocation": {"longitude": float(lon), "latitude": float(lat), "altitude": z_ref},
                                    "surveyPoint": {"position": {"eastings": float(o[0]), "northings": float(o[1]),
                                                                 "elevation": z_ref},
                                                    "geoReferencingParameters": {
                                                        "crsName": f"WGS 84 / UTM zone {zone}{'N' if geo['epsg'] < 32700 else 'S'}",
                                                        "geodeticDatum": "WGS 84", "mapProjection": "UTM",
                                                        "mapZone": str(zone)}}})
        detail(f"archicad: project located at {lat:.6f} N, {lon:.6f} E, project zero = {z_ref:.1f} m above sea level")
    except ArchicadError as e:
        warn(f"archicad: the geographic location could not be set ({e})")

    # ---- check, then save
    counts = {k: len(v) for k, v in result["created"].items()}
    ac.tapir("ChangeWindow", {"windowType": "FloorPlan", "storyIndex": floor}, timeout=600)
    landed = sw.count_on_layers(ac, set(L.values()) | set(dwg_L.values()))
    made, found = sum(counts.values()), sum(landed.values())
    log(f"archicad: check: {made:,} elements made, {found:,} found on the Site / DWG layers "
        f"({', '.join(f'{k} {v:,}' for k, v in sorted(landed.items()) if v)})")
    if found != made:
        raise ArchicadError(f"{made:,} elements were made but {found:,} are on the Site / DWG layers - project NOT saved")
    ac.watch.check()
    try:
        ac.tapir("ChangeWindow", {"windowType": "FloorPlan", "storyIndex": floor}, timeout=3600)
    except ArchicadError as e:
        warn(f"archicad: could not switch to the floor plan before saving ({e}) - saving anyway")
    ac.watch.check()
    ac.tapir("SaveProject", timeout=3600)
    ac.watch.check()
    ok(f"archicad: saved {job.output_pln}")
    if sw.FAILED:
        save_json(job.w("archicad_refused.json"), sw.FAILED)
        warn(f"archicad: {len(sw.FAILED)} elements were refused by Archicad ({", ".join(sorted({f.get('label', '?') for f in sw.FAILED}))}; details: "
             f"{job.w('archicad_refused.json')})")
    result.update({"saved": True, "created_counts": counts, "landed": landed, "terrain_top": terrain_bb,
                   "refused": len(sw.FAILED),
                   "mesh_points": int(len(pts)), "mesh_points_under_paving": int(len(grid_pts)),
                   "mesh_tolerance_m": tol, "paving_edge_lines": len(mesh_lines),
                   "created": {k: len(v) for k, v in result["created"].items()}})
    save_json(result_path, result)
