"""The plans with the window IDs: an ID label on every window in Archicad, and the plan pages of the PDF.

The plan pages are drawn from Archicad's own floor plan outlines of the walls, columns, doors and windows
(floorPlanPolygons), story by story; every window gets a tag with its ID just outside its wall, joined to it by a
short line. The ID labels placed in Archicad sit at the same spot, on a layer of their own,
'Window IDs - Floor Plans', so they can be shown, hidden or redone apart from the model.
"""
import math
from dataclasses import dataclass

from . import layers
from .archicad import ArchicadError, eid
from .sheet import _esc
from .util import log, warn

PLAN_TYPES = ("Wall", "Column", "Door", "Window")
PAPER = (420.0, 297.0)             # A3 landscape, mm
MARGIN = 12.0
TITLE_H = 18.0
SCALES = (50, 100, 150, 200, 250, 500)
TAG_GAP = 0.45                     # m from the wall face to the tag
TAG_SPACING = 1.8                  # m between two tags at least (a tag is ~2 m long at 1:150)


@dataclass
class Tag:
    label: str
    guid: str                      # the window's
    floor: int
    at: tuple                      # the window's centre
    tag: tuple                     # where the ID is written
    symbol: list = None            # the window drawn across its wall opening (closed polygon)
    glass: list = None             # the glass line along the wall


def _walls(ac, guids):
    out = {}
    guids = [g for g in guids if g]
    for i in range(0, len(guids), 200):
        part = guids[i:i + 200]
        det = ac.tapir("GetDetailsOfElements", {"elements": [eid(g) for g in part], "fields": ["details"]})
        for g, d in zip(part, det["detailsOfElements"]):
            out[g] = d.get("details", {})
    return out


def tags(ac, types, geometry):
    """For every window: its symbol across the wall opening, and where its ID goes - off the wall, on the side away
    from the middle of its story, pushed further out when it would sit on another ID."""
    windows = [(t.label, w) for t in types for w in t.windows]
    walls = _walls(ac, list({w.owner for _, w in windows}))
    wall_polys = {g: polys for f in geometry for typ, g, polys in geometry[f] if typ == "Wall"}
    middle = {}
    for f in {w.floor for _, w in windows}:
        pts = [(w.x, w.y) for _, w in windows if w.floor == f]
        middle[f] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    out = []
    for label, w in windows:
        wall = walls.get(w.owner, {})
        b, e = wall.get("begCoordinate"), wall.get("endCoordinate")
        c = (w.x, w.y)
        if not (b and e and (e["x"] - b["x"] or e["y"] - b["y"])):
            out.append(Tag(label, w.guid, w.floor, c, (c[0], c[1] + TAG_GAP + 0.3)))
            continue
        n = math.hypot(e["x"] - b["x"], e["y"] - b["y"])
        d = ((e["x"] - b["x"]) / n, (e["y"] - b["y"]) / n)
        nv = (-d[1], d[0])

        def along(p):
            return (p[0] - b["x"]) * d[0] + (p[1] - b["y"]) * d[1]

        def across(p):
            return (p[0] - b["x"]) * nv[0] + (p[1] - b["y"]) * nv[1]

        def at(s, t):
            return (b["x"] + d[0] * s + nv[0] * t, b["y"] + d[1] * s + nv[1] * t)

        s_c, t_c = along(c), across(c)
        # the wall's faces at the opening: the jamb corners of the wall's own outline next to the window
        ts = [across(p) for poly in wall_polys.get(w.owner, []) for p in poly
              if abs(along(p) - s_c) <= w.width / 2 + 0.03]
        thick = max(wall.get("begThickness", 0.3), wall.get("endThickness", 0.3))
        if ts and max(ts) - min(ts) <= thick * 1.5 + 0.05:
            t0, t1 = min(ts), max(ts)
        else:
            t0, t1 = t_c - thick / 2, t_c + thick / 2
        s0, s1, tm = s_c - w.width / 2, s_c + w.width / 2, (t0 + t1) / 2
        centre = at(s_c, tm)
        mx, my = middle[w.floor]
        side = 1 if (centre[0] - mx) * nv[0] + (centre[1] - my) * nv[1] >= 0 else -1
        off = (t1 - t0) / 2 + TAG_GAP
        pos = at(s_c, tm + side * off)
        for _ in range(6):  # another ID is already there: further out
            if all(math.hypot(pos[0] - o.tag[0], pos[1] - o.tag[1]) >= TAG_SPACING for o in out if o.floor == w.floor):
                break
            off += TAG_SPACING * 0.6
            pos = at(s_c, tm + side * off)
        out.append(Tag(label, w.guid, w.floor, centre, pos,
                       [at(s0, t0), at(s1, t0), at(s1, t1), at(s0, t1), at(s0, t0)], [at(s0, tm), at(s1, tm)]))
    return out


def floor_plan_db(ac, show=False):
    """The database of the floor plan. show=True also brings the floor plan to the front: Tapir creates and deletes
    elements in the window in front, whatever database they are listed from."""
    tree = ac.api("API.GetNavigatorItemTree", {"navigatorTreeId": {"type": "ProjectMap"}})
    stack = [tree["navigatorTree"]["rootItem"]]
    while stack:
        it = stack.pop()
        it = it.get("navigatorItem", it)
        if it.get("type") == "StoryItem":
            if show:
                ac.tapir("ChangeWindow", {"navigatorItemId": it["navigatorItemId"]})
                if ac.tapir("GetCurrentWindowType").get("currentWindowType") != "FloorPlan":
                    raise ArchicadError("could not bring the floor plan to the front")
            db = ac.tapir("GetDatabaseIdFromNavigatorItemId", {"navigatorItemIds": [
                {"navigatorItemId": it["navigatorItemId"]}]})
            return db["databases"][0]["databaseId"]
        stack += it.get("children", [])
    raise ArchicadError("the project has no story in its Project Map")


def element_id_autotext(ac):
    """The autotext that shows an element's Element ID in a label: <PROPERTY-guid> of the built-in property
    General_ElementID (the same key in every language version of Archicad)."""
    prop = ac.api("API.GetPropertyIds", {"properties": [{"type": "BuiltIn", "nonLocalizedName": "General_ElementID"}]})
    return f"<PROPERTY-{prop['properties'][0]['propertyId']['guid'].upper()}>"


def place_ids(ac, tag_list, cfg, size_mm=2.5, window_layers=()):
    """An ID label on every tagged window, on the layer 'Window IDs - Floor Plans' (config layers.ids), made when the
    project does not have it. What an earlier run put on that layer is removed first. Returns the layer's name.

    The labels are Archicad's associative labels, the way window marks are kept in a drawing set: each one belongs to
    its window and shows the window's own Element ID through autotext, so it moves with the window and changes with
    its ID. The mark sits off the wall in a rounded frame, with a leader to a dot on the window; it reads level in the
    plan even when the plan is turned (Set Orientation). Archicad attaches no label to a window it cannot show, so
    the windows' hidden or locked layers (window_layers) are opened for the moment and put back. Should Archicad
    refuse labels, plain texts are placed."""
    layer_name = layers.name(cfg, "ids")
    # the floor plan in front first: Archicad keeps the layers' visibility per open tab, so a layer shown while
    # another tab is in front is hidden again when the floor plan comes to the front
    db = floor_plan_db(ac, show=True)
    layer = layers.ensure(ac, layer_name, layers.picker(cfg, "ids"), window_layers)
    ok = []
    with layers.opened(ac, [layer_name] + sorted(set(window_layers) - {layer_name})):
        old = []
        for typ in ("Text", "Label"):  # Archicad's own GetElementsByType does not know these types; Tapir's does
            els = ac.tapir("GetElementsByType", {"elementType": typ, "databases": [{"databaseId": db}]})["elements"]
            for i in range(0, len(els), 500):
                part = els[i:i + 500]
                det = ac.tapir("GetDetailsOfElements", {"elements": part, "fields": ["layerIndex"]})
                old += [e for e, d in zip(part, det["detailsOfElements"]) if d.get("layerIndex") == layer["index"]]
        if old:
            ac.tapir("DeleteElements", {"elements": old})
            log(f"plans: {len(old)} ID mark(s) of an earlier run removed")
        if not tag_list:
            return layer_name
        style = {"height": size_mm, "bold": True, "angle": ac.level_angle(), "justification": "Center",
                 "anchor": "MiddleMiddle", "fixedSize": True, "usedFill": False, "textFrameShape": "Pill",
                 "contourOffset": 0.8}
        kind = "label"
        try:
            text = element_id_autotext(ac)
            made = ac.tapir("CreateLabels", {"labelsData": [
                {"labelClass": "Text", "parentElementId": {"guid": tg.guid}, "text": text, "floorInd": tg.floor,
                 "begCoordinate": {"x": tg.at[0], "y": tg.at[1]}, "midCoordinate": {"x": tg.tag[0], "y": tg.tag[1]},
                 "endCoordinate": {"x": tg.tag[0], "y": tg.tag[1]}, "style": style,
                 "leaderLine": {"hasLeaderLine": True, "framed": True, "leaderShape": "Segmented",
                                "anchorPoint": "Middle", "arrowType": "FullCircle", "arrowVisible": True,
                                "arrowSize": 1.0, "contourOffset": 0.8, "hideWithBaseElem": True}}
                for tg in tag_list]}).get("elements", [])
        except ArchicadError as e:
            warn(f"plans: Archicad refused the ID labels ({e}) - the IDs are placed as plain texts")
            kind, made = "text", ac.tapir("CreateTexts", {"textsData": [
                {"coordinate": {"x": tg.tag[0], "y": tg.tag[1], "z": 0.0}, "floorIndex": tg.floor, "text": tg.label,
                 "style": {**style, "textFrameShape": "Rectangle", "usedContour": True}}
                for tg in tag_list]}).get("elements", [])
        ok = [e["elementId"] for e in made if "elementId" in e]
        if len(ok) < len(tag_list):
            bad = next((e for e in made if "elementId" not in e), made)
            warn(f"plans: {len(tag_list) - len(ok)} ID {kind}(s) could not be placed: {bad} - is the {kind.title()} "
                 "tool's default layer locked?")
        if ok:  # the tool puts them on its own default layer: onto the IDs layer with them
            ac.tapir("SetDetailsOfElements", {"elementsWithDetails": [
                {"elementId": e, "details": {"layerIndex": layer["index"]}} for e in ok]})
    try:
        ac.tapir("RebuildView", {})
    except ArchicadError:
        pass
    log(f"plans: {len(ok)} window ID {kind}(s) placed on the layer '{layer_name}'")
    return layer_name


def outlines(ac, floors):
    """{story: [(type, guid, [polygon])]} of the plan elements of the given stories."""
    out = {f: [] for f in floors}
    for typ in PLAN_TYPES:
        els = ac.api("API.GetElementsByType", {"elementType": typ})["elements"]
        for i in range(0, len(els), 100):
            part = els[i:i + 100]
            try:
                det = ac.tapir("GetDetailsOfElements", {"elements": part,
                                                        "fields": ["floorIndex", "floorPlanPolygons"]})
            except ArchicadError as e:
                warn(f"plans: {typ} outlines not read: {e}")
                break
            for el, d in zip(part, det["detailsOfElements"]):
                f = d.get("floorIndex")
                if f in out:
                    polys = [[(p["x"], p["y"]) for p in poly.get("coordinates", [])]
                             for poly in d.get("floorPlanPolygons") or []]
                    out[f].append((typ, el["elementId"]["guid"], [p for p in polys if len(p) > 1]))
    return out


# --------------------------------------------------------------------------- the PDF pages
STYLE = {"Wall": 'fill="#d9d9d9" stroke="#000" stroke-width="0.3"',
         "Column": 'fill="#8c8c8c" stroke="#000" stroke-width="0.3"',
         "Door": 'fill="#fff" stroke="#000" stroke-width="0.18"',
         "Window": 'fill="#fff" stroke="#000" stroke-width="0.18"'}


def page_svgs(project, stories, geometry, tag_list, types, rotation=0.0):
    """One A3 page per story: the plan at the largest standard scale that fits, the tags, a title. `rotation` is the
    floor plan's view rotation (Set Orientation), so the pages show the plan turned as it is on screen."""
    pages = []
    count = {f: sum(1 for tg in tag_list if tg.floor == f) for f in geometry}
    cos, sin = math.cos(rotation), math.sin(rotation)

    def turn(p):
        return (p[0] * cos - p[1] * sin, p[0] * sin + p[1] * cos)

    for f in sorted(geometry):
        pts = [turn(p) for _t, _g, polys in geometry[f] for poly in polys for p in poly] + \
              [turn(tg.tag) for tg in tag_list if tg.floor == f]
        if not pts:
            continue
        x0, x1 = min(p[0] for p in pts) - 1, max(p[0] for p in pts) + 1
        y0, y1 = min(p[1] for p in pts) - 1, max(p[1] for p in pts) + 1
        room_w, room_h = PAPER[0] - 2 * MARGIN, PAPER[1] - 2 * MARGIN - TITLE_H
        scale = next((s for s in SCALES if (x1 - x0) * 1000 / s <= room_w and (y1 - y0) * 1000 / s <= room_h),
                     SCALES[-1])
        k = 1000.0 / scale
        ox = MARGIN + (room_w - (x1 - x0) * k) / 2
        oy = MARGIN + TITLE_H + (room_h - (y1 - y0) * k) / 2

        def P(x, y):
            x, y = turn((x, y))
            return f"{ox + (x - x0) * k:.2f},{oy + (y1 - y) * k:.2f}"

        body = []
        for typ in PLAN_TYPES:  # walls first, windows on top
            for t, _g, polys in geometry[f]:
                if t != typ:
                    continue
                for poly in polys:
                    body.append(f'<polygon points="{" ".join(P(*p) for p in poly)}" {STYLE[typ]}/>')
        for tg in (t for t in tag_list if t.floor == f and t.symbol):
            body.append(f'<polygon points="{" ".join(P(*p) for p in tg.symbol)}" fill="#fff" stroke="#000" '
                        f'stroke-width="0.35"/><polyline points="{" ".join(P(*p) for p in tg.glass)}" fill="none" '
                        'stroke="#1a5fb4" stroke-width="0.6"/>')
        r = 3.2
        for tg in (t for t in tag_list if t.floor == f):
            body.append(f'<line x1="{P(*tg.at).split(",")[0]}" y1="{P(*tg.at).split(",")[1]}" '
                        f'x2="{P(*tg.tag).split(",")[0]}" y2="{P(*tg.tag).split(",")[1]}" '
                        'stroke="#c00" stroke-width="0.2"/>')
            tx, ty = map(float, P(*tg.tag).split(","))
            w = 2.1 * len(tg.label) + 2.4
            body.append(f'<rect x="{tx - w / 2:.2f}" y="{ty - r:.2f}" width="{w:.2f}" height="{2 * r:.2f}" '
                        f'rx="{r:.2f}" '
                        'fill="#fff" stroke="#c00" stroke-width="0.3"/>'
                        f'<text x="{tx:.2f}" y="{ty:.2f}" font-size="3.2" font-weight="bold" fill="#c00" '
                        f'text-anchor="middle" dominant-baseline="central">{_esc(tg.label)}</text>')
        title = (f'<text x="{MARGIN}" y="{MARGIN + 7}" font-size="6" font-weight="bold">'
                 f'{_esc(stories.get(f, str(f)))} — Պատուհանների տեղադրություն</text>'
                 f'<text x="{MARGIN}" y="{MARGIN + 13}" font-size="3.5" fill="#555">{_esc(project)} · '
                 f'Մ 1:{scale} · {count.get(f, 0)} պատուհան</text>'
                 f'<line x1="{MARGIN}" y1="{MARGIN + TITLE_H - 2}" x2="{PAPER[0] - MARGIN}" '
                 f'y2="{MARGIN + TITLE_H - 2}" stroke="#000" stroke-width="0.3"/>')
        pages.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAPER[0]}mm" height="{PAPER[1]}mm" '
                     f'viewBox="0 0 {PAPER[0]} {PAPER[1]}" font-family="Segoe UI, Sylfaen, sans-serif">'
                     + title + "".join(body) + "</svg>")
    return pages
