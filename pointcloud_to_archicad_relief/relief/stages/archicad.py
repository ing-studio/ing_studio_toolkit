"""Stage archicad: write the relief into <name>_ReliefOnly.pln in the output folder (name = source PLN, else cloud).

The relief-only PLN starts as a copy of Archicad's own template, so it holds no data of other add-ons and can be
written on any machine. Coordinates, stories and heights are those of the source PLN: bring the relief into the real
project with File > Interoperability > Merge, or place it as a Hotlink at the project origin.

Contents: ONE terrain Mesh, and the contour lines cut from it, one layer per cut size. A Spline is 2D (plan only),
so with archicad.contours_3d every line is also written as a thin upright Morph ribbon on the same layer, which is
real 3D geometry: turning a layer off hides both. Everything on the relief layers is deleted first, so the file
always holds exactly one relief.
"""
import json
import math
import shutil
from pathlib import Path

import numpy as np

from ..archicad import elements as el
from ..archicad.client import ArchicadError, eid
from ..archicad.session import connect_project, forget_project, project_is_open
from ..config import cut_sizes, settings
from ..geometry.transform import apply_transform, xy_to_pln
from ..io.relief_data import read_relief
from ..util import file_signature, load_json, log, save_json, tool
from .names import ARCHICAD_RESULT, CONTOURS_SUMMARY, RELIEF_FILE
from .reference import load_placement


def _xy(t, xy):
    return [{"x": round(float(x), 4), "y": round(float(y), 4)} for x, y in xy_to_pln(t, xy)]


def _prepare_output(job):
    """A fresh copy of the template, unless an Archicad has the output open: then its relief layers are replaced.
    Overwriting an open project would leave that instance showing something the file no longer holds, and its
    next save would undo this run."""
    out = Path(job.output_pln)
    if out.exists() and project_is_open(job.cfg["archicad"]["host"], out):
        log("archicad: the relief-only PLN is open in Archicad, so it is not recreated; its relief layers are replaced")
        return
    template = tool(job.cfg, "archicad_template")
    log(f"archicad: new relief-only PLN from {template}")
    out.parent.mkdir(parents=True, exist_ok=True)
    forget_project(out)
    Path(str(out) + ".lck").unlink(missing_ok=True)  # nothing has it open: a lock left by a killed Archicad
    shutil.copyfile(template, out)


def run(job, force=False):
    a = job.cfg["archicad"]
    result_path = job.p(ARCHICAD_RESULT)
    relief_sig = file_signature(job.p(RELIEF_FILE))
    ref, t, floor, source_story_level = load_placement(job)
    wanted = dict(settings(job.cfg, "archicad"), transform=t)
    prev = load_json(result_path) or {}
    if not force and prev.get("saved") and prev.get("relief") == relief_sig and prev.get("settings") == wanted \
            and Path(job.output_pln).exists():
        log(f"archicad: skip, {job.output_pln} already holds this relief (use --force to redo)")
        return
    summary = load_json(job.p(CONTOURS_SUMMARY)) or {}
    if abs(ref["source_to_sea_level"] - summary.get("source_to_sea_level", 1e9)) > 0.01:
        raise ArchicadError("The contours were built for another elevation reference - run the contours stage again")

    _prepare_output(job)
    ac = connect_project(job, job.output_pln)
    removed = el.remove_relief_layers(ac, a["layer_prefix"])
    if removed:
        log(f"archicad: deleted {removed:,} existing elements on the relief layers")
    baseline = [e["elementId"]["guid"] for e in ac.api("API.GetAllElements")["elements"]]
    story_level = el.story_level(ac, floor)
    if abs(story_level - source_story_level) > 1e-6:
        log(f"archicad: WARNING story {floor} is at {story_level} m here but {source_story_level} m in the source PLN; "
            "heights are written relative to project zero")

    result = {"output_pln": job.output_pln, "source_pln": job.pln, "saved": False, "relief": relief_sig,
              "settings": wanted, "removed_existing_relief_elements": removed, "baseline_elements": len(baseline),
              "created": {}, "elevation_reference": ref}

    def checkpoint(key, guids):
        result["created"][key] = guids
        save_json(result_path, result)

    # --- layers
    sizes = cut_sizes(job.cfg)
    pens = a["contour_pens"]
    layer_names = {"mesh": a["layer_mesh"]}
    layer_names.update({label: a["layer_contours"].format(size=label) for label in sizes})
    ac.tapir("CreateLayers", {"layerDataArray": [{"name": n, "isHidden": False, "isLocked": False}
                                                 for n in layer_names.values()], "overwriteExisting": True})
    all_layers = el.layer_indices(ac)
    li = {k: all_layers[n] for k, n in layer_names.items()}
    result["layers"] = {layer_names[k]: i for k, i in li.items()}
    log(f"archicad: layers {result['layers']}")
    mesh, layers = read_relief(job.p(RELIEF_FILE), list(sizes))
    bs = int(a["batch_size"])

    # --- probes first: a template that cannot take these elements must not cost a whole mesh before it says so
    z_relative, point_mode = el.probe_mesh(ac, floor, story_level)
    z_offset = el.probe_morph(ac, floor) if a["contours_3d"] else 0.0
    all_z = np.concatenate([mesh["outline"][:, 2], mesh["points"][:, 2]] + [h[:, 2] for h in mesh["holes"]])
    mesh_level = math.floor(float(all_z.min()) + (t["oz"] - t["sz"]) - story_level) - 1.0

    def to_xyz(p3):
        p = apply_transform(t, p3)
        p[:, 2] -= story_level + (mesh_level if z_relative else 0.0)
        return [{"x": round(float(x), 4), "y": round(float(y), 4), "z": round(float(zz), 4)} for x, y, zz in p]

    # --- ONE terrain mesh: exactly the vertices the contours were cut from
    data = {"floorIndex": floor, "level": mesh_level, "skirtType": a["mesh_skirt_type"],
            "skirtLevel": a["mesh_skirt_depth_m"], "ridges": a["mesh_ridges"], "showLines": False,
            "contourPen": a["mesh_contour_pen"], "levelPen": a["mesh_level_pen"],
            "polygonCoordinates": to_xyz(mesh["outline"])}
    if mesh["holes"]:
        data["holes"] = [{"polygonCoordinates": to_xyz(h)} for h in mesh["holes"]]
    coords = to_xyz(mesh["points"])
    if point_mode == "single":
        data["sublines"] = [{"coordinates": [c]} for c in coords]
    else:
        data["sublines"] = [{"coordinates": [c, dict(c, x=c["x"] + 0.01)]} for c in coords]
    log(f"archicad: creating one mesh: outline {len(mesh['outline']):,}, holes {len(mesh['holes'])}, "
        f"points {len(coords):,} ...")
    mesh_guids = el.created("mesh", ac.tapir("CreateMeshes", {"meshesData": [data]}, timeout=3600)
                            .get("elements", []))
    if len(mesh_guids) != 1:
        raise ArchicadError("the terrain mesh could not be created - project NOT saved")
    el.set_layer(ac, mesh_guids, li["mesh"], bs)
    checkpoint("mesh", mesh_guids)
    det = ac.tapir("GetDetailsOfElements", {"elements": [eid(mesh_guids[0])], "fields": ["details"]})["detailsOfElements"]
    got = ((det[0] or {}).get("details") or {}).get("polygonCoordinates") or []
    readback = [abs(float(g.get("z", np.nan)) - s["z"]) for s, g in zip(data["polygonCoordinates"][:50], got)]
    readback_max = float(np.nanmax(readback)) if readback else None
    log(f"archicad: mesh vertex read-back max |dz| = {readback_max}")

    # --- contour splines (the plan drawing), one layer per cut size
    for n, (label, lines) in enumerate(layers.items()):
        pen = pens[min(n, len(pens) - 1)]
        common = {"floorInd": floor, "layerIndex": li[label], "linePenIndex": pen}
        splines = [dict(common, closed=c["closed"], coordinates=_xy(t, c["ctrl"])) for c in lines if len(c["ctrl"]) >= 3]
        polys = [dict(common, coordinates=_xy(t, c["curve"])) for c in lines if len(c["ctrl"]) < 3]
        checkpoint(f"splines_{label}", el.batched(ac, "CreateSplines", "splinesData", splines, bs, f"contours {label}"))
        if polys:
            checkpoint(f"polylines_{label}", el.batched(ac, "CreatePolylines", "polylinesData", polys, bs,
                                                        f"contours {label} (short)"))

    # --- the same lines as Morph ribbons on the same layers (3D)
    if a["contours_3d"]:
        tol, half = float(a["contour_3d_simplify_m"]), float(a["contour_3d_height_m"]) / 2.0
        checks = {}
        for label, lines in layers.items():
            items, elevs, n_pts = el.contour_3d_items(
                lines, tol, half, floor, lambda xy: _xy(t, xy),
                lambda e: round(float(e) + (t["oz"] - t["sz"]) + z_offset, 4))
            log(f"archicad: 3D contours {label}: {len(items):,} ribbons, {n_pts:,} points ...")
            guids = el.batched(ac, "CreateMorphs", "morphsData", items, int(a["morph_batch_size"]), f"3D contours {label}")
            el.set_layer(ac, guids, li[label], bs)
            checkpoint(f"morphs_{label}", guids)
            checks[label] = el.check_3d_contours(ac, guids, items, elevs, t)
        result["contours_3d"] = checks
        log(f"archicad: 3D contour height check {json.dumps(checks)}")
        bad = [n for n, ck in checks.items() if not ck["ok"]]
        if bad:
            raise ArchicadError(f"the 3D contour lines of {', '.join(bad)} are not at the height of their contour "
                                "- project NOT saved")

    # --- verify, then save
    after = [e["elementId"]["guid"] for e in ac.api("API.GetAllElements")["elements"]]
    missing = sorted(set(baseline) - set(after))
    bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(mesh_guids[0])]})["boundingBoxes3D"][0].get("boundingBox3D")
    expected_top = float(all_z.max() + t["oz"] - t["sz"])
    top_ok = bb is not None and abs(bb["zMax"] - expected_top) < 0.05
    counts = {k: len(v) for k, v in result["created"].items()}
    log(f"archicad: created {counts}; mesh top zMax={bb and round(bb['zMax'], 3)} expected {expected_top:.3f} -> "
        f"{'OK' if top_ok else 'CHECK'}; original elements missing: {len(missing)}")
    if missing:
        raise ArchicadError(f"{len(missing)} original elements disappeared - project NOT saved; see {ARCHICAD_RESULT}")
    if not top_ok:
        raise ArchicadError("the mesh is not at the expected height - project NOT saved")

    ac.watch.check()
    # Archicad refuses to save while the 3D window is the active one, and creating elements can make it active
    try:
        ac.tapir("ChangeWindow", {"windowType": "FloorPlan", "storyIndex": floor}, timeout=3600)
    except ArchicadError as e:
        log(f"archicad: could not switch to the floor plan before saving ({e}) - saving anyway")
    ac.watch.check()
    ac.tapir("SaveProject", timeout=3600)
    ac.watch.check()
    log(f"archicad: project saved: {job.output_pln}")
    result.update({"saved": True, "elements_after": len(after), "created_counts": counts,
                   "mesh_points": int(len(mesh["points"])), "mesh_bbox": bb, "mesh_expected_top_z": expected_top,
                   "mesh_vertex_readback_max_dz": readback_max, "mesh_level": mesh_level,
                   "vertex_z_relative_to_level": z_relative, "interior_point_mode": point_mode})
    save_json(result_path, result)
