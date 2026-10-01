"""The worksheet «Պատուհանների տեսքեր»: every window type drawn as a front view with its mark, width and height
dimensions, sills, quantity and opening, and under the drawings the table of the types with their count per story.

The drawing is first laid out as a list of primitives (polyline, dimension, text) in worksheet metres, which is
then placed in Archicad on the layer 'Window Types - Measurements' - and also turned into an SVG for the report and
the PDF, so all show the same thing.
Lengths on the sheet are model metres; text heights are paper millimetres, turned into metres with the scale.
The front views are schematic (frame, sashes, transom, glazing bars) - the dimensions are the real ones.

The layout follows the usual rules of a window schedule (ГОСТ 21.501 schemes of window fillings, ISO 129 dimensions):
- the views of a row stand on one line and their marks (Պ-01 ...) are written above them on one line;
- every view has its overall width below and its height on the left, as associative Archicad dimensions, 8 mm off
  the outline; the text under a view (sills, quantity, opening) is centred under it, on lines shared by the row;
- every view sits in a cell wide enough for its dimensions and its text, so nothing overlaps; the rows are spread to
  one width;
- text heights are the standard 5 mm (titles, marks) and 2.5 mm; the table columns are as wide as their text.
"""
from dataclasses import dataclass, field

from . import layers
from .archicad import ArchicadError
from .util import log, mm, warn
from .windows import sash_count

HAND_NAMES = {"L": "ձախ", "R": "աջ"}
OPENINGS = {"fixed glass": "անշարժ", "fixed": "անշարժ", "side hung": "կողային ծխնիով",
            "top hung": "վերին ծխնիով", "bottom hung": "ստորին ծխնիով", "tilt-turn": "պտտվող-ծալվող",
            "tilt and turn": "պտտվող-ծալվող", "sliding": "սահող"}

# on paper, mm
TITLE_MM, MARK_MM, TEXT_MM = 5.0, 5.0, 2.5
CHAR = 0.7          # width of a character / its height, with room to spare (Archicad's fonts measure 0.60-0.67)
DIM_GAP = 8.0       # from an outline to its dimension line
DIM_ROOM = 14.0     # beside a view: its height dimension with its figures, and air
LINE = 4.5          # from one line of 2.5 mm text to the next
CELL_GAP = 8.0      # between the text of two neighbouring cells, at least
ROW_GAP = 14.0      # between two rows of views
ROW_H, PAD = 8.0, 2.0   # table: row height, room left and right of a cell's text


def text_mm(s, size):
    """The width of `s` on paper (mm) at text height `size`, estimated on the safe side."""
    return len(s) * size * CHAR


@dataclass
class Poly:
    points: list                 # [(x, y)]
    key: str = ""                # dimensions refer to it by this key
    thick: bool = False          # outlines: drawn with worksheet.outline_pen when the config sets one


@dataclass
class Dim:
    key: str                     # the Poly it measures
    a: int                       # vertex numbers (1-based, as Archicad counts them)
    b: int
    at: tuple                    # a point of the dimension line
    direction: tuple             # (1, 0) horizontal, (0, 1) vertical


@dataclass
class Text:
    at: tuple
    text: str
    size: float                  # mm on paper
    align: str = "Center"        # Left | Center | Right
    anchor: str = "MiddleMiddle"
    bold: bool = False


@dataclass
class Drawing:
    items: list = field(default_factory=list)

    def add(self, item):
        self.items.append(item)
        return item

    def bounds(self):
        xs, ys = [], []
        for it in self.items:
            pts = it.points if isinstance(it, Poly) else [it.at]
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 1, 1)


def _rect(x0, y0, x1, y1, key="", thick=False):
    return Poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], key, thick)


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def front_view(d, t, ox, oy, key):
    """The schematic front view of type t with its bottom-left corner at (ox, oy)."""
    w, h, draw = t.width, t.height, t.sample.draw
    frame = min(max(_num(draw.get("gs_frame_width"), 0.06), 0.03), min(w, h) / 6)
    d.add(_rect(ox, oy, ox + w, oy + h, key=key, thick=True))  # the measured outline
    d.add(_rect(ox + frame, oy + frame, ox + w - frame, oy + h - frame))

    top = h - frame  # top of the sash area; a transom above it is a fixed light
    if draw.get("gs_UTrans") is True:
        tr = _num(draw.get("gs_UTrans_h"), 0)
        if frame * 3 < tr < h - frame * 3:
            d.add(Poly([(ox + frame, oy + tr), (ox + w - frame, oy + tr)]))
            d.add(Poly([(ox + frame, oy + tr + frame), (ox + w - frame, oy + tr + frame)]))
            top = tr

    n = sash_count(t.sample)
    cols = max(1, int(_num(draw.get("vgn_01"), 1)))
    rows = max(1, int(_num(draw.get("hgn_01"), 1)))
    # Graphisoft 27 windows: iMullionStyle_00 sets the glazing bars of every sash, _01, _02 ... of one; 2 = grid
    styles = [int(_num(v, 1)) for k, v in draw.items() if k.startswith("iMullionStyle_")]
    if styles and 2 not in styles:
        cols = rows = 1
    inner = w - 2 * frame
    sw = inner / n
    sash = frame * 0.6
    for i in range(n):
        x0, x1 = ox + frame + i * sw, ox + frame + (i + 1) * sw
        y0, y1 = oy + frame, oy + top
        if n > 1:
            d.add(_rect(x0 + sash / 2, y0 + sash / 2, x1 - sash / 2, y1 - sash / 2))
        gx0, gx1, gy0, gy1 = x0 + sash, x1 - sash, y0 + sash, y1 - sash
        if gx1 - gx0 <= 0 or gy1 - gy0 <= 0:
            continue
        for c in range(1, cols):
            x = gx0 + (gx1 - gx0) * c / cols
            d.add(Poly([(x, gy0), (x, gy1)]))
        for r in range(1, rows):
            y = gy0 + (gy1 - gy0) * r / rows
            d.add(Poly([(gx0, y), (gx1, y)]))


def opening(t):
    """How the type opens, in words: sliding for the sliding windows, else the sashes' opening types."""
    if "sliding" in t.part.lower():
        return OPENINGS["sliding"]
    kinds = []
    for k in sorted(n for n in t.sample.draw if n.startswith("gs_optype_")):
        v = str(t.sample.draw[k] or "").strip()
        v = OPENINGS.get(v.lower(), v)
        if v and v not in kinds:
            kinds.append(v)
    return " + ".join(kinds)


def info_lines(t):
    """The lines under a type's view: sills (three to a line), quantity, opening, opening side."""
    sills = [str(s) for s in t.sills()]
    lines = []
    for i in range(0, len(sills), 3):
        part = ", ".join(sills[i:i + 3]) + ("," if i + 3 < len(sills) else "")
        lines.append(("Պատուհանագոգ՝ " if i == 0 else "") + part)
    lines.append(f"Քանակ՝ {len(t.windows)} հատ")
    if opening(t):
        lines.append(f"Բացում՝ {opening(t)}")
    if t.hand in HAND_NAMES:
        lines.append(f"Բացման կողմ՝ {HAND_NAMES[t.hand]}")
    return lines


def _rows(types, p, limit):
    """The types in rows of cells [(type, lines, cell width mm)], no row wider than `limit` mm (a cell wider than
    that gets a row of its own)."""
    rows, row, used = [], [], 0.0
    for t in types:
        lines = info_lines(t)
        width = max(t.width / p + 2 * DIM_ROOM, max(text_mm(s, TEXT_MM) for s in lines) + CELL_GAP,
                    text_mm(t.label, MARK_MM) + CELL_GAP)
        if row and used + width > limit:
            rows.append(row)
            row, used = [], 0.0
        row.append([t, lines, width])
        used += width
    if row:
        rows.append(row)
    return rows


def layout(types, stories, cfg):
    """The whole sheet as a Drawing."""
    sc = cfg.get("worksheet", {})
    p = float(sc.get("scale", 50)) / 1000.0   # model metres per paper millimetre
    d = Drawing()

    # ---- title
    d.add(Text((0, 0), sc.get("title", "Պատուհանների տեսքեր"), TITLE_MM, "Left", "LeftBottom", True))
    d.add(Text((0, -2.5 * p), f"Մ 1:{sc.get('scale', 50)} · չափերը՝ մմ · պատուհանագոգը՝ հարկի հատակից",
               TEXT_MM, "Left", "LeftTop"))

    # ---- front views, in rows from the top down; every row spread to the width of the widest
    rows = _rows(types, p, float(sc.get("row_width_mm", 420)))
    full = max(sum(c[2] for c in row) for row in rows) if rows else 0
    row_top = -14 * p
    for n, row in enumerate(rows):
        if n < len(rows) - 1 or len(row) > 1 and sum(c[2] for c in row) > full * 0.75:
            extra = (full - sum(c[2] for c in row)) / len(row)
            for c in row:
                c[2] += extra
        h = max(t.height for t, _l, _w in row)
        mark_y = row_top - MARK_MM / 2 * p
        base = row_top - (MARK_MM + 6) * p - h      # every view of a row stands on this line
        first = base - (DIM_GAP + 5) * p           # the first line of text under the views
        x = 0.0
        for t, lines, width in row:
            cx = x + width * p / 2
            x0 = cx - t.width / 2
            front_view(d, t, x0, base, t.label)
            d.add(Text((cx, mark_y), t.label, MARK_MM, bold=True))
            d.add(Dim(t.label, 1, 2, (x0, base - DIM_GAP * p), (1, 0)))
            d.add(Dim(t.label, 1, 4, (x0 - DIM_GAP * p, base), (0, 1)))
            for i, line in enumerate(lines):
                d.add(Text((cx, first - i * LINE * p), line, TEXT_MM))
            x += width * p
        lowest = first - (max(len(c[1]) for c in row) - 1) * LINE * p
        row_top = lowest - ROW_GAP * p
    table(d, types, stories, sc, p, row_top - 4 * p)
    return d


def table(d, types, stories, sc, p, top):
    """The table «Պատուհանների մասնագիր» with its top-left corner at (0, top): per type its sizes, sills, count per
    story and in all, library part. The story columns share the heading «Քանակ ըստ հարկերի»."""
    floors = sorted({f for t in types for f in t.per_floor()})
    names = [stories.get(f, str(f)) for f in floors]
    head = ["Տիպ", "Լայնություն, մմ", "Բարձրություն, մմ", "Պատուհանագոգ, մմ"] + names + ["Ընդամենը", "Տարր"]
    body = []
    for t in types:
        pf = t.per_floor()
        body.append([t.label, str(mm(t.width)), str(mm(t.height)), ", ".join(str(s) for s in t.sills())]
                    + [str(pf.get(f, "")) for f in floors] + [str(len(t.windows)), t.part])
    body.append(["Ընդամենը", "", "", ""] + [str(sum(t.per_floor().get(f, 0) for t in types)) for f in floors]
                + [str(sum(len(t.windows) for t in types)), ""])
    widths = [max(text_mm(r[c], TEXT_MM) for r in [head] + body) + 2 * PAD for c in range(len(head))]
    group, g0, g1 = "Քանակ ըստ հարկերի", 4, 4 + len(floors)
    if floors:  # the story columns together at least as wide as their common heading
        short = text_mm(group, TEXT_MM) + 2 * PAD - sum(widths[g0:g1])
        for c in range(g0, g1):
            widths[c] += max(short, 0) / len(floors)
    xs = [0.0]
    for w in widths:
        xs.append(xs[-1] + w * p)

    d.add(Text((0, top), sc.get("table_title", "Պատուհանների մասնագիր"), TITLE_MM, "Left", "LeftBottom", True))
    y = top - 3 * p
    rh = ROW_H * p
    head_h = 2 * rh if floors else rh
    y_head = y - head_h
    y_bottom = y_head - len(body) * rh
    # lines: the frame and the line under the heading thick, the rest thin
    d.add(Poly([(xs[0], y), (xs[-1], y)], thick=True))
    if floors:
        d.add(Poly([(xs[g0], y - rh), (xs[g1], y - rh)]))
    d.add(Poly([(xs[0], y_head), (xs[-1], y_head)], thick=True))
    for i in range(1, len(body)):
        d.add(Poly([(xs[0], y_head - i * rh), (xs[-1], y_head - i * rh)]))
    d.add(Poly([(xs[0], y_bottom), (xs[-1], y_bottom)], thick=True))
    for c, xv in enumerate(xs):
        inside_group = floors and g0 < c < g1
        d.add(Poly([(xv, y - rh if inside_group else y), (xv, y_bottom)], thick=c in (0, len(xs) - 1)))
    # heading: the merged cells centred in the whole heading, the story names under their common heading
    for c, cell in enumerate(head):
        cx = (xs[c] + xs[c + 1]) / 2
        if floors and g0 <= c < g1:
            d.add(Text((cx, y - 1.5 * rh), cell, TEXT_MM, bold=True))
        else:
            d.add(Text((cx, y - head_h / 2), cell, TEXT_MM, bold=True))
    if floors:
        d.add(Text(((xs[g0] + xs[g1]) / 2, y - rh / 2), group, TEXT_MM, bold=True))
    for r, cells in enumerate(body):
        cy = y_head - (r + 0.5) * rh
        last = r == len(body) - 1
        for c, cell in enumerate(cells):
            if cell == "":
                continue
            if c == len(cells) - 1:
                d.add(Text((xs[c] + PAD * p, cy), cell, TEXT_MM, "Left", "LeftMiddle"))
            else:
                d.add(Text(((xs[c] + xs[c + 1]) / 2, cy), cell, TEXT_MM, bold=(c == 0 or last)))


# --------------------------------------------------------------------------- Archicad
def _worksheet(ac, name, ref):
    """The navigator item of the worksheet named `name`; created when it is not there yet."""
    def find():
        tree = ac.api("API.GetNavigatorItemTree", {"navigatorTreeId": {"type": "ProjectMap"}})
        stack = [tree["navigatorTree"]["rootItem"]]
        while stack:
            it = stack.pop()
            it = it.get("navigatorItem", it)
            if it.get("type") == "WorksheetItem" and it.get("name") == name:
                return it["navigatorItemId"]
            stack += it.get("children", [])
        return None
    nav = find()
    if nav is None:
        ac.tapir("CreateWorksheets", {"worksheetsData": [{"name": name, "referenceId": ref}]})
        nav = find()
        if nav is None:
            raise ArchicadError(f"the worksheet '{name}' was created but is not in the Project Map")
        log(f"sheet: worksheet '{ref} {name}' created")
    return nav


CLEARED_TYPES = ("PolyLine", "Line", "Text", "Dimension", "Hatch", "Arc", "Circle", "Label")


def _check_widths(ac, placed):
    """The layout reserves text_mm() for every text; Archicad says how wide each one really came out (its font and
    width factor are the template's). A wider one may touch its neighbour: say which."""
    wide = []
    for i in range(0, len(placed), 500):
        part = placed[i:i + 500]
        try:
            det = ac.tapir("GetDetailsOfElements", {"elements": [{"elementId": e["elementId"]} for _t, e in part],
                                                    "fields": ["details"]})["detailsOfElements"]
        except ArchicadError:
            return
        for (t, _e), dd in zip(part, det):
            box = (dd.get("details") or {}).get("style", {}).get("boxWidth")
            if box and box > text_mm(t.text, t.size) + 0.5:
                wide.append(f"'{t.text}' {box:.0f} mm")
    if wide:
        warn(f"sheet: {len(wide)} text(s) came out wider than the room left for them (a wide font in the Text tool?):"
             f" {', '.join(wide[:3])}")
    else:
        log(f"sheet: every text fits the room left for it ({len(placed)} checked)")


def place(ac, drawing, cfg):
    """Draws `drawing` into the worksheet, on the layer 'Window Types - Measurements' (config layers.types; made when
    the project does not have it). What an earlier run drew there is deleted first. Returns (worksheet, layer)."""
    sc = cfg.get("worksheet", {})
    name, ref = sc.get("name", "Պատուհանների տեսքեր"), sc.get("reference_id", "Պ")
    layer_name = layers.name(cfg, "types")
    layer = layers.ensure(ac, layer_name, layers.picker(cfg, "types"))
    nav = _worksheet(ac, name, ref)
    ac.tapir("ChangeWindow", {"navigatorItemId": nav})
    if ac.tapir("GetCurrentWindowType").get("currentWindowType") != "Worksheet":
        raise ArchicadError(f"could not open the worksheet '{name}' - nothing was drawn")
    db = ac.tapir("GetDatabaseIdFromNavigatorItemId", {"navigatorItemIds": [{"navigatorItemId": nav}]})
    db = db["databases"][0]["databaseId"]

    with layers.opened(ac, [layer_name]):
        old = []
        for typ in CLEARED_TYPES:
            try:
                old += ac.tapir("GetElementsByType", {"elementType": typ,
                                                      "databases": [{"databaseId": db}]})["elements"]
            except ArchicadError:
                pass
        if old:
            ac.tapir("DeleteElements", {"elements": old})
            log(f"sheet: {len(old)} element(s) of the previous run removed from the worksheet")

        polys = [it for it in drawing.items if isinstance(it, Poly)]
        thick_pen = sc.get("outline_pen")  # None: every line with the Polyline tool's pen
        made = ac.tapir("CreatePolylines", {"polylinesData": [
            {"coordinates": [{"x": x, "y": y} for x, y in pl.points], "layerIndex": int(layer["index"]),
             **({"linePenIndex": int(thick_pen)} if pl.thick and thick_pen else {})} for pl in polys]})["elements"]
        by_key = {pl.key: e["elementId"] for pl, e in zip(polys, made) if pl.key and "elementId" in e}

        dims = [it for it in drawing.items if isinstance(it, Dim) and it.key in by_key]
        made_dims = []
        if dims:
            made_dims = ac.tapir("CreateAssociativeDimensions", {"dimensionsData": [
                {"referencePoint": {"x": dm.at[0], "y": dm.at[1]},
                 "direction": {"x": dm.direction[0], "y": dm.direction[1]},
                 "witnessPoints": [{"elementId": by_key[dm.key], "inIndex": dm.a},
                                   {"elementId": by_key[dm.key], "inIndex": dm.b}]}
                for dm in dims]}).get("elements", [])
            bad = [e for e in made_dims if "elementId" not in e]
            if bad:
                warn(f"sheet: {len(bad)} dimension(s) could not be placed: {bad[0]}")

        texts = [it for it in drawing.items if isinstance(it, Text)]
        angle = ac.level_angle()  # the Text tool's default angle may follow a turned floor plan
        made_texts = ac.tapir("CreateTexts", {"textsData": [
            {"coordinate": {"x": t.at[0], "y": t.at[1], "z": 0}, "text": t.text, "height": t.size,
             "style": {"justification": t.align, "anchor": t.anchor, "bold": t.bold, "angle": angle,
                       "fixedSize": True}} for t in texts]})["elements"]
        failed = [e for e in list(made) + list(made_texts) if "elementId" not in e]
        if failed:
            warn(f"sheet: {len(failed)} line(s)/text(s) could not be drawn: {failed[0]} - is the tool's default layer "
                 "locked?")
        # texts and dimensions land on their tools' default layers: onto the measurements layer with them
        moved = [e["elementId"] for e in list(made_texts) + list(made_dims) if "elementId" in e]
        if moved:
            ac.tapir("SetDetailsOfElements", {"elementsWithDetails": [
                {"elementId": e, "details": {"layerIndex": int(layer["index"])}} for e in moved]})
        _check_widths(ac, [(t, e) for t, e in zip(texts, made_texts) if "elementId" in e])
    for command in ("RebuildView", "FitInWindow"):  # Archicad's screen may miss some of many new lines until rebuilt
        try:
            ac.tapir(command, {})
        except ArchicadError:
            pass
    log(f"sheet: '{ref} {name}' drawn on the layer '{layer_name}': {len(polys)} lines, {len(dims)} dimensions, "
        f"{len(texts)} texts")
    return f"{ref} {name}", layer_name


# --------------------------------------------------------------------------- SVG (for the report)
SVG_STYLE = ("polyline{fill:none;stroke:#000;stroke-width:.18}.thick{stroke-width:.45}.dim,.dimw{stroke:#444;"
             "stroke-width:.13}.tick{stroke:#222;stroke-width:.35}text{fill:#000;font-family:'Segoe UI',Sylfaen,"
             "sans-serif}.dimt{font-size:2.5px;text-anchor:middle;fill:#222}")


def paper_size(drawing, cfg):
    """The sheet's size on paper at its scale, mm (with a 10 mm margin)."""
    p = float(cfg.get("worksheet", {}).get("scale", 50)) / 1000.0
    x0, y0, x1, y1 = drawing.bounds()
    return (x1 - x0) / p + 20, (y1 - y0) / p + 20


def to_svg(drawing, cfg, paper=False):
    """The sheet as SVG; 1 unit = 1 paper mm. paper=True: true size in mm, with its own styles (for the PDF)."""
    p = float(cfg.get("worksheet", {}).get("scale", 50)) / 1000.0
    x0, y0, x1, y1 = drawing.bounds()
    pad = 10 * p
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    k = 1 / p

    def P(x, y):
        return f"{(x - x0) * k:.2f},{(y1 - y) * k:.2f}"

    w, h = (x1 - x0) * k, (y1 - y0) * k
    size = f' width="{w:.1f}mm" height="{h:.1f}mm"' if paper else ""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.1f} {h:.1f}"{size} class="sheet">'
           + (f"<style>{SVG_STYLE}</style>" if paper else "")]
    polys = {it.key: it for it in drawing.items if isinstance(it, Poly) and it.key}
    for it in drawing.items:
        if isinstance(it, Poly):
            out.append(f'<polyline points="{" ".join(P(*pt) for pt in it.points)}" '
                       f'class="{"thick" if it.thick else "thin"}"/>')
        elif isinstance(it, Dim) and it.key in polys:
            # drawn as on paper (ISO 129): extension lines from a small gap off the object to just past the
            # dimension line, 45° ticks at its ends, the figure above it
            a, b = polys[it.key].points[it.a - 1], polys[it.key].points[it.b - 1]
            gap, over, tick = 1.5 * p, 2.0 * p, 1.4 * p
            if it.direction == (1, 0):
                pa, pb = (a[0], it.at[1]), (b[0], it.at[1])
                value = abs(b[0] - a[0])
                s = 1 if it.at[1] > a[1] else -1
                ext = [((q[0], q[1] + s * gap), (q[0], it.at[1] + s * over)) for q in (a, b)]
            else:
                pa, pb = (it.at[0], a[1]), (it.at[0], b[1])
                value = abs(b[1] - a[1])
                s = 1 if it.at[0] > a[0] else -1
                ext = [((q[0] + s * gap, q[1]), (it.at[0] + s * over, q[1])) for q in (a, b)]
            out += [f'<polyline points="{P(*u)} {P(*v)}" class="dimw"/>' for u, v in ext]
            out.append(f'<polyline points="{P(*pa)} {P(*pb)}" class="dim"/>')
            out += [f'<polyline points="{P(q[0] - tick, q[1] - tick)} {P(q[0] + tick, q[1] + tick)}" class="tick"/>'
                    for q in (pa, pb)]
            mx, my = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
            rot = "" if it.direction == (1, 0) else f' transform="rotate(-90 {P(mx, my).replace(",", " ")})"'
            ax, ay = P(mx, my).split(",")
            out.append(f'<text x="{ax}" y="{float(ay) - 0.8:.2f}" class="dimt"{rot}>{mm(value)}</text>')
        elif isinstance(it, Text):
            anchor = {"Left": "start", "Center": "middle", "Right": "end"}[it.align]
            base = "auto" if it.anchor.endswith("Bottom") else "central"
            tx, ty = P(*it.at).split(",")
            out.append(f'<text x="{tx}" y="{ty}" font-size="{it.size:.1f}" text-anchor="{anchor}" '
                       f'dominant-baseline="{base}"{" font-weight=" + chr(34) + "bold" + chr(34) if it.bold else ""}>'
                       f'{_esc(it.text)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
