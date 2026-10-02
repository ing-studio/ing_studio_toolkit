"""Reading every window of the open project: what it is (library part, size, sashes, hand) and where it is."""
import re
from dataclasses import dataclass, field

from .archicad import ArchicadError, eid
from .util import log, warn

BATCH = 200  # elements per request: keeps each answer of GetGDLParametersOfElements a sensible size


@dataclass
class Window:
    guid: str
    id: str                 # its Element ID now
    floor: int              # story index
    part: str               # library part name
    width: float            # nominal width  (A), m
    height: float           # nominal height (B), m
    sill: float             # sill height from its story, m
    hand: str               # opening side ("L" / "R"), "" when the window has none
    params: dict = field(default_factory=dict)  # the GDL parameters that are part of the type (config type_params)
    draw: dict = field(default_factory=dict)    # the GDL parameters the elevation drawing uses
    x: float = 0.0          # centre on the plan, m
    y: float = 0.0
    editable: bool = True   # False: on a locked or hidden layer (or locked itself) - its ID cannot be changed
    layer: str = ""
    layer_index: int = 0
    owner: str = ""         # the wall it sits in


def _chunks(items, n=BATCH):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _rounded(value):
    """A GDL value fit for comparing types: numbers to the millimetre, arrays and strings as they are."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, list):
        return tuple(_rounded(v) for v in value)
    return value


DRAW_PARAMS = ("gs_frame_width", "vgn_01", "hgn_01", "gs_UTrans", "gs_UTrans_h") \
    + tuple(f"iMullionStyle_{i:02d}" for i in range(9)) \
    + tuple(f"gs_optype_{i:02d}" for i in range(1, 9))
# iMullionStyle: glazing bars, 1 none, 2 grid; _00 all sashes, _01... one. gs_optype_NN: how sash NN opens
# ("Fixed Glass", "Side Hung" ...) in the Graphisoft windows that have it


def read_windows(ac, cfg):
    """All windows of the project that belong to it (windows inside hotlinked modules are left out: their ID
    can only be changed in the module's own file)."""
    listed = ac.api("API.GetElementsByType", {"elementType": "Window"})["elements"]
    log(f"windows: {len(listed)} in the project")
    if not listed:
        return []
    guids = [e["elementId"]["guid"] for e in listed]
    details, gdl, boxes, editable = [], [], [], set()
    for part in _chunks(guids):
        els = [eid(g) for g in part]
        details += ac.tapir("GetDetailsOfElements", {"elements": els, "fields": [
            "id", "floorIndex", "layerIndex", "details", "hotlinkId"]})["detailsOfElements"]
        gdl += ac.tapir("GetGDLParametersOfElements", {"elements": els})["gdlParametersOfElements"]
        boxes += ac.api("API.Get2DBoundingBoxes", {"elements": els})["boundingBoxes2D"]
        editable |= {e["elementId"]["guid"] for e in ac.tapir("FilterElements", {
            "elements": els, "filters": ["IsEditable"]}).get("elements", [])}
    layers = {a.get("index"): a.get("name", "") for a in
              ac.tapir("GetAttributesByType", {"attributeType": "Layer"}).get("attributes", [])}

    hand_param = cfg.get("hand_param", "ac_OpeningSide")
    type_params = cfg.get("type_params", [])
    windows, hotlinked = [], 0
    for guid, d, g, b in zip(guids, details, gdl, boxes):
        if d.get("hotlinkId"):
            hotlinked += 1
            continue
        det = d.get("details", {})
        if "error" in det or "libPart" not in det:
            warn(f"windows: {guid} ({d.get('id', '')}) could not be read: {det.get('error', det)} - left out")
            continue
        p = {x["name"]: x.get("value") for x in g.get("parameters", [])}
        box = b.get("boundingBox2D", {})
        windows.append(Window(
            guid=guid, id=d.get("id", ""), floor=int(d.get("floorIndex", 0)), part=det["libPart"]["name"],
            width=float(det["width"]), height=float(det["height"]), sill=float(det.get("sillHeight", 0.0)),
            hand=str(p.get(hand_param) or "").strip().upper(),
            params={n: _rounded(p[n]) for n in type_params if n in p},
            draw={n: p[n] for n in DRAW_PARAMS if n in p},
            x=(box.get("xMin", 0) + box.get("xMax", 0)) / 2, y=(box.get("yMin", 0) + box.get("yMax", 0)) / 2,
            editable=guid in editable, layer=layers.get(d.get("layerIndex"), str(d.get("layerIndex", ""))),
            layer_index=int(d.get("layerIndex", 0)), owner=det.get("ownerElementId", {}).get("guid", "")))
    if hotlinked:
        warn(f"windows: {hotlinked} window(s) inside hotlinked modules left out - number them in the module's file")
    return windows


def none_found(ac):
    """The message for a project without windows - saying what it has instead, when that explains it."""
    seen = []
    for typ, what in (("Opening", "wall openings"), ("Door", "doors")):
        try:
            n = len(ac.api("API.GetElementsByType", {"elementType": typ})["elements"])
        except ArchicadError:
            n = 0
        if n:
            seen.append(f"{n} {what}")
    return ("there are no windows in this project (elements made with the Window tool)"
            + (f" - it has {' and '.join(seen)}; openings and objects drawn as windows are not numbered"
               if seen else ""))


def count(ac):
    """How many windows the open project has (a quick look, before any work)."""
    return len(ac.api("API.GetElementsByType", {"elementType": "Window"})["elements"])


def sash_count(window):
    """The number of sashes: from the part name for the Graphisoft sliding windows ('3-Sash Sliding Window 27'),
    else 1."""
    m = re.search(r"(\d+)\s*-\s*sash", window.part, re.I)
    return int(m.group(1)) if m else 1


def stories(ac):
    """{story index: display name}."""
    out = {}
    for s in ac.tapir("GetStories").get("stories", []):
        i = int(s.get("index", 0))
        name = (s.get("uName") or s.get("name") or "").strip()
        level = float(s.get("level", 0.0))
        out[i] = name or f"Հարկ {i} ({level:+.2f})"
    return out
