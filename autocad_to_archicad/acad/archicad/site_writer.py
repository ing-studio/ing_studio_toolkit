"""Archicad helpers of this tool (the connection and batching are the relief tool's): clean-up of our layers, pens
for AutoCAD colours, the solid fill, hatches without holes, mesh payloads."""

import numpy as np
from ezdxf.colors import aci2rgb
from shapely.geometry import LineString, Polygon
from shapely.ops import split

from ..util import detail, warn
from .client import ArchicadError
from .elements import layer_indices

OUR_TYPES = ("Mesh", "PolyLine", "Line", "Arc", "Circle", "Hatch", "Text", "Spline", "Hotspot", "Morph", "Object")
NEEDED = ("CreateMeshes", "CreateMorphs", "CreateObjects", "CreateSurfaces", "GetAvailableLibraryParts",
          "CreatePolylines", "CreateArcs", "CreateCircles", "CreateHatches", "CreateTexts", "CreateHotspots",
          "CreateLayers", "GetAttributesByType", "GetPenTables", "GetFills", "SetDetailsOfElements",
          "GetElementsByType", "GetDetailsOfElements", "DeleteElements", "SaveProject", "ChangeWindow", "GetStories")


def _face(f):
    if isinstance(f, tuple):  # a flat face with holes
        outer, holes = f
        d = {"vertexIds": [int(i) for i in outer]}
        if holes:
            d["holes"] = [{"vertexIds": [int(i) for i in h]} for h in holes]
        return d
    return {"vertexIds": [int(i) for i in f]}


def morph_item(verts, faces, floor, z_shift, body_type, layer, surface=None):
    """A CreateMorphs payload of a body (vertices (x, y, z model), faces: vertex id lists or (outer, [holes]));
    z_shift = the probe's offset; surface = attribute id of its surface."""
    item = {"basePoint": {"x": 0.0, "y": 0.0, "z": 0.0}, "floorIndex": floor, "_layer": layer,
            "body": {"bodyType": body_type,
                     "vertices": [{"x": float(x), "y": float(y), "z": round(float(z) + z_shift, 4)} for x, y, z in verts],
                     "polygons": [_face(f) for f in faces]}}
    if surface:
        item["surfaceId"] = surface
    return item


def make_surfaces(ac, surfaces):
    """The surfaces of archicad.surfaces made (or updated) in the PLN: {key: attribute id}."""
    keys = [k for k in surfaces if not k.startswith("_")]
    res = ac.tapir("CreateSurfaces", {"surfaceDataArray": [
        {"name": surfaces[k]["name"], "materialType": "Matte", "ambientReflection": 60, "diffuseReflection": 80,
         "surfaceColor": dict(zip(("red", "green", "blue"), (float(c) for c in surfaces[k]["rgb"])))} for k in keys],
        "overwriteExisting": True})
    out = {}
    for k, r in zip(keys, res.get("attributeIds", [])):
        if isinstance(r, dict) and "attributeId" in r:
            out[k] = r["attributeId"]
        else:
            warn(f"archicad: the surface {surfaces[k]['name']} could not be made ({r})")
    return out


def library_part(ac, names):
    """The first of `names` the project's library has, or None."""
    try:
        parts = ac.tapir("GetAvailableLibraryParts", {"filterByTypeId": "Object"}, timeout=600).get("libraryParts", [])
    except ArchicadError as e:
        warn(f"archicad: the library could not be listed ({e})")
        return None
    have = {p.get("documentName") for p in parts}
    return next((n for n in names if n in have), None)


def probe_object(ac, floor, name):
    """Offset to add to an object's z so it stands where asked (a probe object is made and deleted)."""
    from .client import eid
    want = 7.0
    res = ac.tapir("CreateObjects", {"objectsData": [{"libraryPartName": name, "floorIndex": floor,
                                                      "coordinates": {"x": -1000.0, "y": -1000.0, "z": want},
                                                      "dimensions": {"x": 2.0, "y": 2.0, "z": 4.0}}]})
    ok = [g for g in res.get("elements", []) if isinstance(g, dict) and "elementId" in g]
    if not ok:
        raise ArchicadError(f"the library part {name} could not be placed ({res})")
    bb = ac.api("API.Get3DBoundingBoxes", {"elements": [eid(ok[0]["elementId"]["guid"])]})["boundingBoxes3D"][0]
    ac.tapir("DeleteElements", {"elements": [eid(ok[0]["elementId"]["guid"])]})
    got = (bb.get("boundingBox3D") or {}).get("zMin", want)
    return want - got


def probe_solid(ac, floor):
    """'Solid' when this Archicad makes closed Morph bodies from faces, else 'Surface' (a closed surface looks the
    same). The probe cube is deleted."""
    from .client import eid
    v = [(-1000.0, -1000.0, 0.0), (-990.0, -1000.0, 0.0), (-990.0, -990.0, 0.0), (-1000.0, -990.0, 0.0),
         (-1000.0, -1000.0, 5.0), (-990.0, -1000.0, 5.0), (-990.0, -990.0, 5.0), (-1000.0, -990.0, 5.0)]
    f = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    for kind in ("Solid", "Surface"):
        item = morph_item(v, f, floor, 0.0, kind, None)
        item.pop("_layer")
        try:
            res = ac.tapir("CreateMorphs", {"morphsData": [item]})
        except ArchicadError:
            continue
        ok = [g for g in res.get("elements", []) if isinstance(g, dict) and "elementId" in g]
        if ok:
            ac.tapir("DeleteElements", {"elements": [eid(ok[0]["elementId"]["guid"])]})
            return kind
    raise ArchicadError("Morph bodies cannot be created by this Tapir / Archicad")


def remove_on_layers(ac, prefixes):
    """Delete every element on layers whose name starts with one of `prefixes`; returns the number deleted."""
    names = {n: i for n, i in layer_indices(ac).items() if n and any(n.startswith(p) for p in prefixes)}
    wanted = set(names.values())
    if not wanted:
        return 0
    # Archicad does not delete elements on hidden or locked layers (someone may have switched ours off to look)
    ac.tapir("CreateLayers", {"layerDataArray": [{"name": n, "isHidden": False, "isLocked": False} for n in names],
                              "overwriteExisting": True})
    elems, seen = [], set()
    for t in OUR_TYPES:
        try:
            got = ac.tapir("GetElementsByType", {"elementType": t}).get("elements", [])
        except ArchicadError:
            continue
        for e in got:  # circles are listed among the arcs too: each element once
            g = e["elementId"]["guid"]
            if g not in seen:
                seen.add(g)
                elems.append(e)
    doomed = []
    for i in range(0, len(elems), 2000):
        chunk = elems[i:i + 2000]
        try:
            det = ac.tapir("GetDetailsOfElements", {"elements": chunk, "fields": ["layerIndex"]})["detailsOfElements"]
        except ArchicadError:
            det = []
            for e in chunk:
                try:
                    det += ac.tapir("GetDetailsOfElements", {"elements": [e], "fields": ["layerIndex"]})["detailsOfElements"]
                except ArchicadError:
                    det.append(None)
        doomed += [e for e, d in zip(chunk, det) if isinstance(d, dict) and d.get("layerIndex") in wanted]
    for i in range(0, len(doomed), 2000):
        try:
            ac.tapir("DeleteElements", {"elements": doomed[i:i + 2000]})
        except ArchicadError:  # one bad element spoils the batch: the rest one by one
            for e in doomed[i:i + 2000]:
                try:
                    ac.tapir("DeleteElements", {"elements": [e]})
                except ArchicadError:
                    pass
    return len(doomed)


def count_on_layers(ac, layer_idx):
    """{element type: count} of the elements on the given layer indices (what really landed in the project)."""
    out, seen = {}, set()
    for t in OUR_TYPES:
        try:
            elems = ac.tapir("GetElementsByType", {"elementType": t}).get("elements", [])
        except ArchicadError:
            continue
        elems = [e for e in elems if e["elementId"]["guid"] not in seen]  # circles come with the arcs too
        seen.update(e["elementId"]["guid"] for e in elems)
        n = 0
        for i in range(0, len(elems), 2000):
            det = ac.tapir("GetDetailsOfElements", {"elements": elems[i:i + 2000], "fields": ["layerIndex"]})["detailsOfElements"]
            n += sum(1 for d in det if isinstance(d, dict) and d.get("layerIndex") in layer_idx)
        if n:
            out[t] = n
    return out


def _attr_ids(ac, kind):
    res = ac.tapir("GetAttributesByType", {"attributeType": kind})
    items = res.get("attributes", res) if isinstance(res, dict) else res
    out = []
    for a in items:
        a = a.get("attribute", a) if isinstance(a, dict) else a
        if isinstance(a, dict) and "attributeId" in a:
            out.append(a)
    return out


def pen_mapper(ac):
    """(aci, rgb) -> index of the pen with the nearest colour in the active model pen table."""
    colours = {}
    try:
        tables = _attr_ids(ac, "PenTable")
        res = ac.tapir("GetPenTables", {"attributeIds": [{"attributeId": t["attributeId"]} for t in tables]})
        active = None
        for pt in res.get("penTables", []):
            pt = pt.get("penTable", pt)
            if pt.get("isActiveForModel") or active is None:
                active = pt
        for pen in (active or {}).get("pens", []):
            c = pen.get("color") or pen.get("colour") or {}
            idx = pen.get("index")
            if idx and c:
                colours[int(idx)] = (c.get("red", 0) * 255, c.get("green", 0) * 255, c.get("blue", 0) * 255)
    except (ArchicadError, KeyError, TypeError) as e:
        warn(f"archicad: the pen table could not be read ({e}); every line gets pen 1")
    if not colours:
        return lambda aci, rgb: 1, {}
    idx = np.array(sorted(colours))
    cols = np.array([colours[i] for i in idx], dtype=np.float64)
    memo = {}

    def pen(aci, rgb):
        key = (aci, tuple(rgb) if rgb else None)
        if key not in memo:
            c = np.array(rgb if rgb else aci2rgb(aci if 1 <= aci <= 255 else 7), dtype=np.float64)
            if c.sum() > 3 * 245:  # white in AutoCAD (on black) = black on paper
                c = np.zeros(3)
            memo[key] = int(idx[np.argmin(((cols - c) ** 2).sum(axis=1))])
        return memo[key]
    detail(f"archicad: {len(colours)} pens in the model pen table")
    return pen, colours


def solid_fill_id(ac):
    try:
        fills = _attr_ids(ac, "Fill")
        res = ac.tapir("GetFills", {"attributeIds": [{"attributeId": f["attributeId"]} for f in fills]})
        for f in res.get("fills", []):
            f = f.get("fill", f)
            if f.get("subType") == "Solid" and "attributeId" in f:
                return f["attributeId"]
    except (ArchicadError, KeyError, TypeError) as e:
        warn(f"archicad: fills could not be read ({e}); hatches get the default fill")
    return None


def without_holes(poly, depth=0):
    """A polygon with holes as pieces without holes (cut through each hole), for hatches that take one outline."""
    if not poly.interiors or depth > 12:
        return [poly]
    h = poly.interiors[0]
    cx = Polygon(h).centroid.x
    x0, y0, x1, y1 = poly.bounds
    parts = split(poly, LineString([(cx, y0 - 1), (cx, y1 + 1)]))
    out = []
    for p in parts.geoms:
        if p.area > 1e-6:
            out += without_holes(p, depth + 1)
    return out


def xy_list(pts, nd=4):
    return [{"x": round(float(x), nd), "y": round(float(y), nd)} for x, y in pts]


def clean_xy(pts, nd=4, ring=False):
    """Rounded points without repeats (Archicad refuses zero-length segments); for a ring also without the closing
    repeat of the first point."""
    a = np.round(np.asarray(pts, dtype=np.float64), nd)
    keep = np.r_[True, np.any(np.diff(a, axis=0) != 0, axis=1)]
    a = a[keep]
    if ring:
        while len(a) > 1 and np.all(a[0] == a[-1]):
            a = a[:-1]
    return a


def hatch_rings(poly, nd=4):
    """Outlines Archicad accepts for a (hole-free) polygon: rounded, without repeats, repaired if rounding made it
    self-intersect."""
    ring = clean_xy(np.asarray(poly.exterior.coords), nd, ring=True)
    if len(ring) < 3:
        return []
    p = Polygon(ring)
    if p.is_valid:
        return [ring]
    out = []
    for part in (p.buffer(0).geoms if hasattr(p.buffer(0), "geoms") else [p.buffer(0)]):
        if part.geom_type == "Polygon" and part.area > 1e-4:
            for q in without_holes(part):
                r = clean_xy(np.asarray(q.exterior.coords), nd, ring=True)
                if len(r) >= 3 and Polygon(r).is_valid:
                    out.append(r)
    return out


def xyz_list(pts, nd=4):
    return [{"x": round(float(x), nd), "y": round(float(y), nd), "z": round(float(z), nd)} for x, y, z in pts]


FAILED = []  # payloads Archicad refused, kept for the report / diagnosis
BUSY = "ongoing user input"


def make_patient(ac, wait_s=300):
    """Archicad answers 'ongoing user input' while someone works in its window (a tool in use, a dialog open):
    wait and retry instead of failing. The relief tool's client is used unchanged; only this instance is wrapped."""
    import time
    from .client import SafetyStop
    raw = ac.api
    told = [False]

    def api(command, params=None, timeout=900):
        t_end = time.time() + wait_s
        while True:
            try:
                return raw(command, params, timeout)
            except SafetyStop:
                raise
            except ArchicadError as e:
                if BUSY not in str(e) or time.time() > t_end:
                    raise
                if not told[0]:
                    warn("archicad: Archicad is busy with user input (a tool in use or a dialog open in the window "
                         "this tool opened) - waiting; finish or press Esc there")
                    told[0] = True
                time.sleep(5)
    ac.api = api
    return ac


def batched_create(ac, command, key, items, batch, label, set_layer_batch=500):
    """Create in batches; items may carry '_layer' (set afterwards when the command has no layerIndex) and '_src'
    (what it came from, for the failure list). Returns the guids in order (failures skipped)."""
    guids = []
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        send = [{k: v for k, v in it.items() if not k.startswith("_")} for it in chunk]
        res = ac.tapir(command, {key: send}, timeout=3600)
        got = res.get("elements", [])
        ok = [(it, g) for it, g in zip(chunk, got) if isinstance(g, dict) and "elementId" in g]
        if len(ok) != len(chunk):
            bad = [(it, g) for it, g in zip(chunk, got) if not (isinstance(g, dict) and "elementId" in g)]
            FAILED.extend({"command": command, "label": label, "error": g, "item": it} for it, g in bad)
            detail(f"archicad: {label}: {len(bad)} of {len(chunk)} not created ({str(bad[0][1])[:160]})")
        guids += [g["elementId"]["guid"] for _, g in ok]
        late = [({"elementId": g["elementId"], "details": {"layerIndex": it["_layer"]}}) for it, g in ok if "_layer" in it]
        for j in range(0, len(late), set_layer_batch):
            ac.tapir("SetDetailsOfElements", {"elementsWithDetails": late[j:j + set_layer_batch]})
        detail(f"archicad: {label}: {min(i + batch, len(items)):,}/{len(items):,} sent, {len(guids):,} created")
    return guids
