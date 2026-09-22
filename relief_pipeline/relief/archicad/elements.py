"""Archicad element helpers: layers, batched creation, clean-up, probes, and contour lines in 3D (Morph ribbons)."""
import json

import numpy as np
from shapely.geometry import LineString

from ..util import log
from .client import ArchicadError, eid

RELIEF_TYPES = ("Mesh", "Spline", "PolyLine", "Text", "Morph")


def created(label, items):
    ok, bad = [], []
    for it in items:
        (ok if isinstance(it, dict) and "elementId" in it else bad).append(it)
    if bad:
        log(f"archicad: {label}: {len(bad)} failures, first: {json.dumps(bad[0])[:400]}")
    return [it["elementId"]["guid"] for it in ok]


def batched(ac, command, key, items, batch, label):
    guids = []
    for i in range(0, len(items), batch):
        res = ac.tapir(command, {key: items[i:i + batch]}, timeout=3600)
        guids += created(label, res.get("elements", []))
        log(f"archicad: {label}: {min(i + batch, len(items)):,}/{len(items):,} sent, {len(guids):,} created")
    return guids


def set_layer(ac, guids, layer_index, batch):
    for i in range(0, len(guids), batch):
        ac.tapir("SetDetailsOfElements", {"elementsWithDetails": [
            {"elementId": {"guid": g}, "details": {"layerIndex": layer_index}} for g in guids[i:i + batch]]})


def layer_indices(ac):
    attrs = ac.tapir("GetAttributesByType", {"attributeType": "Layer"})
    attrs = attrs.get("attributes", attrs)
    out = {}
    for at in attrs:
        at = at.get("attribute", at)
        out[at.get("name")] = int(at.get("index"))
    return out


def remove_relief_layers(ac, prefix):
    """Delete every relief element (mesh, spline, polyline, text, morph) on layers whose name starts with `prefix`,
    including layers of earlier pipeline versions; returns the number deleted. Tapir's GetElementsByType is used
    because Archicad's API.GetAllElements does not list 2D elements."""
    wanted = {i for n, i in layer_indices(ac).items() if n and n.startswith(prefix)}
    if not wanted:
        return 0
    elems = [e for t in RELIEF_TYPES for e in ac.tapir("GetElementsByType", {"elementType": t}).get("elements", [])]
    doomed = []
    for i in range(0, len(elems), 2000):
        chunk = elems[i:i + 2000]
        try:
            det = ac.tapir("GetDetailsOfElements", {"elements": chunk, "fields": ["layerIndex"]})["detailsOfElements"]
        except ArchicadError:  # an element type Tapir cannot read spoils the batch: ask one by one
            det = []
            for e in chunk:
                try:
                    det += ac.tapir("GetDetailsOfElements", {"elements": [e], "fields": ["layerIndex"]})["detailsOfElements"]
                except ArchicadError:
                    det.append(None)
        doomed += [e for e, d in zip(chunk, det) if isinstance(d, dict) and d.get("layerIndex") in wanted]
    for i in range(0, len(doomed), 2000):
        ac.tapir("DeleteElements", {"elements": doomed[i:i + 2000]})
    return len(doomed)


def story_level(ac, floor):
    return next(float(s["level"]) for s in ac.tapir("GetStories")["stories"] if int(s["index"]) == floor)


def ribbon_body(pts, half):
    """A contour line as a thin upright ribbon, centred on the line: the Morph body that makes it visible in 3D.

    The line lies exactly on the terrain, so half of the ribbon stands out of the surface and half is buried in it,
    which reads as a line on the terrain from every direction. One quad per segment - a Surface body, not a solid."""
    verts, polys = [], []
    for p in pts:
        verts.append({"x": p["x"], "y": p["y"], "z": round(p["z"] - half, 4)})
        verts.append({"x": p["x"], "y": p["y"], "z": round(p["z"] + half, 4)})
    for i in range(len(pts) - 1):
        b = 2 * i
        polys.append({"vertexIds": [b, b + 2, b + 3, b + 1]})
    return {"bodyType": "Surface", "vertices": verts, "polygons": polys}


def contour_3d_items(lines, tol, half, floor, to_xy, z_of):
    """One Morph per contour line, ready for CreateMorphs. The plan Splines keep the full curve; these are
    simplified to `tol`, because every vertex costs two Morph vertices and a face in the 3D model."""
    items, elevs, n_pts = [], [], 0
    for c in lines:
        xy = c["curve"]
        if tol > 0 and len(xy) > 2:
            xy = np.asarray(LineString(xy).simplify(tol).coords)
        if len(xy) < 2:
            continue
        z = z_of(c["elev_src"])
        pts = [dict(p, z=z) for p in to_xy(xy)]
        pts = [p for i, p in enumerate(pts) if i == 0 or (p["x"], p["y"]) != (pts[i - 1]["x"], pts[i - 1]["y"])]
        if len(pts) < 2:
            continue
        items.append({"basePoint": {"x": 0.0, "y": 0.0, "z": 0.0}, "floorIndex": floor,
                      "body": ribbon_body(pts, half)})
        elevs.append(float(c["elev_src"]))
        n_pts += len(pts)
    return items, elevs, n_pts


def check_3d_contours(ac, guids, items, elevs, t):
    """Ribbons read back from the 3D model: each must stand at the height of the contour it was made from."""
    ok_count = len(guids) == len(items)  # a failed creation would shift the pairing, so only check when all landed
    probe = [0, len(guids) - 1] if ok_count and guids else []
    worst, got_z = 0.0, None
    for i in probe:
        bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(guids[i])]})["boundingBoxes3D"][0]["boundingBox3D"]
        got_z = (bb["zMin"] + bb["zMax"]) / 2.0
        worst = max(worst, abs(got_z - (elevs[i] + t["oz"] - t["sz"])))
    return {"ribbons": len(guids), "of": len(items), "checked": len(probe), "last_z": got_z and round(got_z, 3),
            "max_dz": round(worst, 4), "ok": bool(probe) and worst < 0.05}


def probe_morph(ac, floor):
    """A throw-away ribbon to learn how Morph coordinates are referenced here; returns the offset to add to every
    z so that a line lands at the wanted height, and deletes what it made."""
    want = 7.0
    body = ribbon_body([{"x": -1000.0, "y": -1000.0, "z": want}, {"x": -980.0, "y": -1000.0, "z": want}], 0.1)
    try:
        res = ac.tapir("CreateMorphs", {"morphsData": [{"basePoint": {"x": 0.0, "y": 0.0, "z": 0.0},
                                                        "floorIndex": floor, "body": body}]})
    except ArchicadError as e:
        raise ArchicadError(f"Morphs cannot be created by this Tapir/Archicad ({e}) - set archicad.contours_3d "
                            "to false to write the plan contours only")
    ok = created("probe morph", res.get("elements", []))
    if not ok:
        raise ArchicadError("the probe Morph could not be created - set archicad.contours_3d to false")
    bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(ok[0])]})["boundingBoxes3D"][0]["boundingBox3D"]
    ac.tapir("DeleteElements", {"elements": [eid(ok[0])]})
    offset = want - (bb["zMin"] + bb["zMax"]) / 2.0
    log(f"archicad: probe -> Morph z offset {offset:+.3f} m (ribbon asked for {want}, landed at "
        f"{(bb['zMin'] + bb['zMax']) / 2.0:.3f})")
    return offset


def probe_mesh(ac, floor, level):
    """Tiny throw-away meshes to learn (1) whether vertex z is relative to the mesh level and
    (2) how single interior level points are accepted. Everything created here is deleted."""
    square = [{"x": -1000.0, "y": -1000.0, "z": 1.0}, {"x": -980.0, "y": -1000.0, "z": 2.0},
              {"x": -980.0, "y": -980.0, "z": 3.0}, {"x": -1000.0, "y": -980.0, "z": 2.0}]

    def make(sublines):
        data = {"floorIndex": floor, "level": 10.0, "skirtType": "SurfaceOnlyWithoutSkirt", "skirtLevel": 0.0,
                "polygonCoordinates": square}
        if sublines:
            data["sublines"] = sublines
        try:
            res = ac.tapir("CreateMeshes", {"meshesData": [data]})
        except Exception as e:
            return None, str(e)
        ok = created("probe mesh", res.get("elements", []))
        if not ok:
            return None, "not created"
        bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(ok[0])]})["boundingBoxes3D"][0]["boundingBox3D"]
        ac.tapir("DeleteElements", {"elements": [eid(ok[0])]})
        return bb["zMax"] - level, None

    zmax, err = make(None)
    if zmax is None:
        raise ArchicadError(f"Probe mesh could not be created: {err}")
    relative = abs(zmax - 13.0) < 0.05
    if not relative and abs(zmax - 3.0) > 0.05:
        raise ArchicadError(f"Unexpected probe mesh height {zmax}")
    peak = 8.0 if relative else 18.0  # interior point at 18 m above the story either way
    mode = None
    zmax, err = make([{"coordinates": [{"x": -990.0, "y": -990.0, "z": peak}]}])
    if zmax is not None and abs(zmax - 18.0) < 0.05:
        mode = "single"
    else:
        zmax, err = make([{"coordinates": [{"x": -990.0, "y": -990.0, "z": peak}, {"x": -989.99, "y": -990.0, "z": peak}]}])
        if zmax is not None and abs(zmax - 18.0) < 0.05:
            mode = "pair"
    if mode is None:
        raise ArchicadError(f"Mesh interior level points are not accepted by this Tapir/Archicad ({err})")
    log(f"archicad: probe -> vertex z {'relative to mesh level' if relative else 'story-relative'}; "
        f"interior points as '{mode}' level entries")
    return relative, mode
