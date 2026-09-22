"""Stage reference: how point cloud coordinates map into the source PLN (placement + elevations).

Read once from the source PLN (opened in Archicad, never saved) and cached in elevation_reference.json and
transform.json, so later stages never need the source project again.

'object' placement: the PLN contains the point cloud object built from the same cloud -> the relief is fitted to
it (origin, rotation, Z; checked against its 3D box, min and max Z must agree).
'coordinates' placement: the cloud's own coordinates + placement.offset / rotation_deg.
No source PLN ('new_pln'): the cloud's own coordinates in a new PLN, Z = metres above sea level, the project origin
moved near the cloud when it is far from 0,0 (placement.new_pln_origin). Archicad is not needed for this.
"""
import math

import numpy as np
from shapely.geometry import box

from ..archicad.client import ArchicadError, eid
from ..archicad.elements import story_level as read_story_level
from ..archicad.session import connect_project
from ..geometry.transform import apply_transform
from ..util import detail, file_signature, load_json, log, save_json, skip, warn


def source_bounds(job):
    sb = load_json(job.c("cloud_summary.json"))["bounds"]
    return np.array([sb["minx"], sb["miny"], sb["minz"]]), np.array([sb["maxx"], sb["maxy"], sb["maxz"]])


# --------------------------------------------------------------------------- elevation reference
def project_zero_altitude(ac):
    """Project zero altitude a.s.l. = ElevationToSeaLevel - ElevationToProjectZero of any element."""
    elems = ac.api("API.GetAllElements")["elements"][:50]
    if not elems:
        return None
    pid = ac.api("API.GetPropertyIds", {"properties": [
        {"type": "BuiltIn", "nonLocalizedName": "General_ElevationToSeaLevel"},
        {"type": "BuiltIn", "nonLocalizedName": "General_ElevationToProjectZero"}]})["properties"]
    vals = ac.api("API.GetPropertyValuesOfElements", {"elements": elems, "properties": [
        {"propertyId": p["propertyId"]} for p in pid]})["propertyValuesForElements"]
    for pv in vals:
        try:
            sea, pz = (float(v["propertyValue"]["value"]) for v in pv["propertyValues"])
            return sea - pz
        except (KeyError, TypeError, ValueError):
            continue
    return None


def matching_point_cloud_objects(ac, job):
    """Objects whose 3D box has the input cloud's height range and a footprint a rotated copy of the cloud's XY
    extent can produce. Best match first; the configured library part name wins ties."""
    mins, maxs = source_bounds(job)
    sx, sy, sz = maxs - mins
    tol = job.cfg["placement"]["transform_tolerance_m"]
    objs = ac.api("API.GetElementsByType", {"elementType": "Object"})["elements"]
    if not objs:
        return []
    bbs = ac.api("API.Get3DBoundingBoxes", {"elements": objs})["boundingBoxes3D"]
    found = []
    for o, b in zip(objs, bbs):
        bb = b.get("boundingBox3D")
        if not bb:
            continue
        bx, by, bz = bb["xMax"] - bb["xMin"], bb["yMax"] - bb["yMin"], bb["zMax"] - bb["zMin"]
        if abs(bz - sz) > tol:
            continue
        # rotated rectangle: bx + by = (sx + sy)(|cos| + |sin|), between (sx + sy) and (sx + sy) * sqrt2
        if not ((sx + sy) - tol <= bx + by <= (sx + sy) * math.sqrt(2) + tol) or min(bx, by) < min(sx, sy) - tol:
            continue
        found.append({"guid": o["elementId"]["guid"], "bbox": bb, "score": abs(bz - sz) + abs(bx - sx) + abs(by - sy)})
    name = job.cfg["placement"].get("point_cloud_libpart_name")
    if found and name:
        pid = ac.api("API.GetPropertyIds", {"properties": [
            {"type": "BuiltIn", "nonLocalizedName": "General_LibraryPartName"}]})["properties"][0]["propertyId"]
        vals = ac.api("API.GetPropertyValuesOfElements", {"elements": [eid(f["guid"]) for f in found],
                                                          "properties": [{"propertyId": pid}]})["propertyValuesForElements"]
        for f, pv in zip(found, vals):
            v = pv["propertyValues"][0].get("propertyValue", {}).get("value", "")
            f["libpart"] = v
            if isinstance(v, str) and v.strip() == name:
                f["score"] -= 1e6
    return sorted(found, key=lambda f: f["score"])


def _coordinates_z_offset(job, pza):
    """Coordinates placement: source Z is either metres a.s.l. or already relative to project zero."""
    pl = job.cfg["placement"]
    mode = pl.get("source_z", "auto")
    if mode == "auto":
        mins, maxs = source_bounds(job)
        zmid = float(mins[2] + maxs[2]) / 2.0
        mode = "sea_level" if abs(zmid - pza) < abs(zmid) else "project_zero"
    off = float((pl.get("offset") or [0, 0, 0])[2])
    return (off - pza if mode == "sea_level" else off), mode


def detect_elevation_reference(ac, job):
    """source Z -> project zero / sea level offsets, read from the open output PLN."""
    mode = job.cfg["placement"].get("mode", "auto")
    pza = project_zero_altitude(ac)
    if pza is None:
        raise ArchicadError("Could not read the project zero altitude from the PLN (no elements with elevation)")
    ref = None
    if mode != "coordinates":
        cands = matching_point_cloud_objects(ac, job)
        if cands:
            c = cands[0]
            bb = c["bbox"]
            mins, maxs = source_bounds(job)
            dz_min, dz_max = bb["zMin"] - mins[2], bb["zMax"] - maxs[2]
            if abs(dz_min - dz_max) >= 0.01:
                raise ArchicadError(f"Point cloud Z range does not match the source ({dz_min:.3f} vs {dz_max:.3f}) - "
                                    "possible inversion/scaling; stopping")
            ref = {"placement": "object", "object_guid": c["guid"], "object_libpart": c.get("libpart"),
                   "matching_objects": len(cands), "dz_from_zmin": float(dz_min), "dz_from_zmax": float(dz_max),
                   "dz_source_to_project_zero": float(dz_min + dz_max) / 2.0,
                   "pln_point_cloud_z": [bb["zMin"], bb["zMax"]], "source_z": [float(mins[2]), float(maxs[2])]}
        elif mode == "object":
            raise ArchicadError("placement.mode is 'object' but no point cloud object in the PLN matches the input "
                                "cloud's extent")
        else:
            log("reference: no point cloud object in the PLN matches this cloud -> using its own coordinates")
    if ref is None:
        dz, zmode = _coordinates_z_offset(job, pza)
        ref = {"placement": "coordinates", "source_z": zmode, "dz_source_to_project_zero": dz}
    ref["project_zero_altitude"] = pza
    ref["source_to_sea_level"] = ref["dz_source_to_project_zero"] + pza
    return ref


def load_placement(job):
    """(elevation reference, transform, floor, source story level) cached by the reference stage."""
    ref, tr = load_json(job.p("elevation_reference.json")), load_json(job.p("transform.json"))
    if not ref or not tr or "transform" not in tr:
        raise RuntimeError("placement not known yet - run the reference stage first")
    return ref, tr["transform"], int(tr["floorIndex"]), float(tr["story_level"])


def _new_pln_origin(job):
    """XY of the point cloud that becomes the project origin of a new PLN."""
    origin = job.cfg["placement"]["new_pln_origin"]
    if isinstance(origin, list):
        return float(origin[0]), float(origin[1])
    mins, maxs = source_bounds(job)
    centre = (mins[:2] + maxs[:2]) / 2.0
    if origin == "keep" or max(abs(centre)) <= 1000.0:
        return 0.0, 0.0
    return float(round(centre[0], -2)), float(round(centre[1], -2))


def new_pln_placement(job, inputs):
    """No source PLN: the cloud's own coordinates (moved to a nearby origin), Z = m a.s.l. = project zero."""
    pl = job.cfg["placement"]
    x0, y0 = _new_pln_origin(job)
    off = pl.get("offset") or [0.0, 0.0, 0.0]
    t = dict(ox=float(off[0]), oy=float(off[1]), oz=float(off[2]), angle=math.radians(float(pl.get("rotation_deg", 0.0))),
             sx=x0, sy=y0, sz=0.0)
    ref = {"placement": "new_pln", "source_z": "sea_level", "dz_source_to_project_zero": float(off[2]),
           "project_zero_altitude": 0.0, "source_to_sea_level": float(off[2]), "new_pln_origin": [x0, y0],
           "inputs": inputs}
    save_json(job.p("transform.json"), {"placement": "new_pln", "floorIndex": 0, "story_level": 0.0, "transform": t})
    save_json(job.p("elevation_reference.json"), ref)
    if x0 or y0:
        log(f"reference: new PLN - point cloud point ({x0:.0f}, {y0:.0f}) is the project origin "
            "(placement.new_pln_origin)")
    else:
        log("reference: new PLN - the point cloud's own coordinates")


def run(job, force=False):
    inputs = load_json(job.c("cloud_summary.json"))["inputs"]
    if job.pln is None:
        new_pln_placement(job, inputs)
        return
    path = job.p("elevation_reference.json")
    ref, transform = load_json(path), load_json(job.p("transform.json"))
    if ref and transform and "transform" in transform and not force \
            and ref.get("source_pln") == file_signature(job.pln) and ref.get("inputs") == inputs:
        skip("reference: placement already known")
        return
    log("reference: opening the source PLN to read placement and elevations (it is never saved)")
    ac = connect_project(job, job.pln)
    ref = detect_elevation_reference(ac, job)
    ref["source_pln"] = file_signature(job.pln)
    ref["inputs"] = inputs
    resolve_placement(ac, job, ref)  # writes transform.json
    save_json(path, ref)
    log(f"reference: {ref['placement']} placement; source Z + {ref['dz_source_to_project_zero']:.4f} = project zero Z; "
        f"project zero = {ref['project_zero_altitude']:.3f} m a.s.l.")


# --------------------------------------------------------------------------- transform
def resolve_placement(ac, job, ref):
    """Source -> PLN transform for the open source PLN; saved to transform.json."""
    if ref["placement"] == "object":
        t, _, _ = derive_transform(ac, job, ref["object_guid"])
        dz_t = t["oz"] - t["sz"]
        if abs(dz_t - ref["dz_source_to_project_zero"]) > 0.05:
            raise ArchicadError(f"Vertical offset disagrees: transform {dz_t:.4f} vs bounding box "
                                f"{ref['dz_source_to_project_zero']:.4f}")
        return

    pl = job.cfg["placement"]
    floor = int(pl.get("floor_index", 0))
    story_level = read_story_level(ac, floor)
    off = pl.get("offset") or [0.0, 0.0, 0.0]
    t = dict(ox=float(off[0]), oy=float(off[1]), oz=float(ref["dz_source_to_project_zero"]),
             angle=math.radians(float(pl.get("rotation_deg", 0.0))), sx=0.0, sy=0.0, sz=0.0)
    mins, maxs = source_bounds(job)
    corners = np.array([[x, y, 0.0] for x in (mins[0], maxs[0]) for y in (mins[1], maxs[1])])
    p = apply_transform(t, corners)
    cloud_box = box(p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max())
    elems = ac.api("API.GetAllElements")["elements"]
    model_box = None
    if elems:
        bbs = [b["boundingBox3D"] for b in ac.api("API.Get3DBoundingBoxes", {"elements": elems})["boundingBoxes3D"]
               if "boundingBox3D" in b]
        if bbs:
            model_box = box(min(b["xMin"] for b in bbs), min(b["yMin"] for b in bbs),
                            max(b["xMax"] for b in bbs), max(b["yMax"] for b in bbs))
    overlaps = model_box is None or cloud_box.intersects(model_box)
    save_json(job.p("transform.json"), {"placement": "coordinates", "floorIndex": floor, "story_level": story_level,
                                        "transform": t, "source_z": ref.get("source_z"),
                                        "cloud_box_pln": list(cloud_box.bounds),
                                        "model_box_pln": list(model_box.bounds) if model_box else None,
                                        "overlaps_model": overlaps})
    log(f"reference: coordinates placement, offset {off}, rotation {pl.get('rotation_deg', 0.0)} deg, "
        f"Z {ref.get('source_z')}, floor {floor}")
    if not overlaps:
        warn("reference: the relief does not overlap the existing model; check placement.offset "
            f"(relief {tuple(round(v) for v in cloud_box.bounds)}, model {tuple(round(v) for v in model_box.bounds)})")


def derive_transform(ac, job, pc_guid):
    det = ac.tapir("GetDetailsOfElements", {"elements": [eid(pc_guid)]})["detailsOfElements"][0]
    d = det["details"]
    floor = int(det["floorIndex"])
    story_level = read_story_level(ac, floor)
    origin = d.get("origin") or d.get("pos") or {}
    ox, oy = float(origin.get("x", 0.0)), float(origin.get("y", 0.0))
    oz = float(origin.get("z", d.get("level", 0.0)))
    angle = float(d.get("angle", 0.0))
    bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(pc_guid)]})["boundingBoxes3D"][0]["boundingBox3D"]
    target = np.array([bb["xMin"], bb["xMax"], bb["yMin"], bb["yMax"], bb["zMin"], bb["zMax"]])

    mins, maxs = source_bounds(job)
    corners = np.array([[x, y, z] for x in (mins[0], maxs[0]) for y in (mins[1], maxs[1]) for z in (mins[2], maxs[2])])
    candidates = []
    for shift_name, shift in (("none", np.zeros(3)), ("min", mins), ("center", (mins + maxs) / 2)):
        for sign in (1.0, -1.0):
            for z_story in (True, False):
                t = dict(ox=ox, oy=oy, oz=oz + (story_level if z_story else 0.0), angle=sign * angle,
                         sx=float(shift[0]), sy=float(shift[1]), sz=float(shift[2]))
                p = apply_transform(t, corners)
                got = np.array([p[:, 0].min(), p[:, 0].max(), p[:, 1].min(), p[:, 1].max(), p[:, 2].min(), p[:, 2].max()])
                candidates.append((float(np.max(np.abs(got - target))), shift_name, sign, z_story, t))
    candidates.sort(key=lambda c: c[0])
    err, shift_name, sign, z_story, t = candidates[0]
    save_json(job.p("transform.json"), {
        "placement": "object", "object_guid": pc_guid, "floorIndex": floor, "story_level": story_level,
        "origin": [ox, oy, oz], "angle_rad": angle, "angle_deg": math.degrees(angle), "api_bbox": target.tolist(),
        "best": {"error_m": err, "shift": shift_name, "angle_sign": sign, "z_includes_story": z_story},
        "transform": t, "candidates": [(round(c[0], 4), c[1], c[2], c[3]) for c in candidates]})
    detail(f"reference: point cloud origin=({ox:.3f},{oy:.3f},{oz:.3f}) angle={math.degrees(angle):.4f} deg floor={floor} "
        f"story={story_level}; best fit shift={shift_name} sign={sign} err={err:.3f} m")
    if err > job.cfg["placement"]["transform_tolerance_m"]:
        raise ArchicadError(f"No placement hypothesis matches the point cloud bounding box (best error {err:.3f} m). "
                            "See transform.json")
    return t, floor, story_level
