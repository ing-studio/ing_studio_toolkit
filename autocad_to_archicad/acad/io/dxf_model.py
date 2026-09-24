"""A DXF drawing as a flat list of simple primitives, as AutoCAD shows it in model space.

Blocks are exploded recursively (their transforms applied: scale, mirror, rotation, OCS), so every primitive is in
world coordinates. Entities on layer 0 inside a block take the layer of the block reference, ByBlock colours its
colour, ByLayer colours and line types the layer's. Curves (splines, ellipses, mirrored arcs) become polylines within
`tol` drawing units; plain arcs and circles are kept.

Primitive kinds (coordinates in drawing units, angles in radians):
  poly    xy (N, 2), closed
  arc     c (2), r, a0, a1 (counter-clockwise)
  circle  c (2), r
  fill    rings: list of (N, 2) boundary loops (hatches, solids); solid: bool; pattern
  text    xy (2), h, rot, text, just (Left|Center|Right)
  point   xy (2)
Common keys: layer, color (ACI 1-255), rgb (r, g, b) or None, lt (line type), top (index of the top-level entity it
came from), block (name of the outermost block reference, or None).
"""
import math
from collections import Counter

import ezdxf
import numpy as np
from ezdxf import path as zpath
from ezdxf.math import Vec3

from .armscii import maybe_decode

INSUNITS = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 14: 0.1}
SKIPPED = {"XLINE", "RAY", "IMAGE", "WIPEOUT", "OLE2FRAME", "3DSOLID", "REGION", "BODY", "SURFACE", "MESH",
           "ACAD_PROXY_ENTITY", "VIEWPORT", "UNDERLAY", "PDFUNDERLAY", "DWFUNDERLAY", "DGNUNDERLAY", "ACAD_TABLE"}
MTEXT_JUST = {1: "Left", 2: "Center", 3: "Right", 4: "Left", 5: "Center", 6: "Right", 7: "Left", 8: "Center", 9: "Right"}
TEXT_JUST = {0: "Left", 1: "Center", 2: "Right", 3: "Left", 4: "Center", 5: "Left"}


class Flattener:
    def __init__(self, doc, tol, decode_text=True):
        self.doc = doc
        self.tol = tol
        self.decode_text = decode_text
        self.prims = []
        self.skipped = Counter()
        self.proxies = Counter()
        self.decoded = set()
        self._layers = {}
        for layer in doc.layers:
            self._layers[layer.dxf.name] = layer

    # ------------------------------------------------------------------ attributes
    def _layer_color(self, name):
        layer = self._layers.get(name)
        if layer is None:
            return 7, None
        rgb = layer.rgb if layer.has_dxf_attrib("true_color") else None
        return abs(layer.color) or 7, rgb

    def _style(self, e, parent):
        """(layer, aci, rgb, linetype) of an entity, block rules applied."""
        layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
        if layer == "0" and parent is not None:
            layer = parent["layer"]
        color = e.dxf.color if e.dxf.hasattr("color") else 256
        rgb = e.rgb if e.dxf.hasattr("true_color") else None
        if color == 0:  # ByBlock
            color, rgb = (parent["color"], parent["rgb"]) if parent else (7, None)
        elif color == 256 or color is None:  # ByLayer
            if rgb is None:
                color, rgb = self._layer_color(layer)
            else:
                color = self._layer_color(layer)[0]
        lt = e.dxf.linetype if e.dxf.hasattr("linetype") else "BYLAYER"
        if lt.upper() == "BYBLOCK":
            lt = parent["lt"] if parent else "Continuous"
        if lt.upper() == "BYLAYER":
            lay = self._layers.get(layer)
            lt = lay.dxf.linetype if lay is not None else "Continuous"
        return {"layer": layer, "color": int(color), "rgb": tuple(rgb) if rgb else None, "lt": lt}

    # ------------------------------------------------------------------ geometry
    def _add(self, kind, style, top, block, **geom):
        self.prims.append(dict(kind=kind, layer=style["layer"], color=style["color"], rgb=style["rgb"], lt=style["lt"],
                               top=top, block=block, **geom))

    def _path_polys(self, p):
        """ezdxf Path -> list of (N, 2) arrays (one per sub-path)."""
        out = []
        for sub in p.sub_paths() if p.has_sub_paths else [p]:
            pts = np.array([(v.x, v.y) for v in sub.flattening(self.tol)], dtype=np.float64)
            if len(pts) >= 2:
                out.append(pts)
        return out

    def _text(self, e, style, top, block):
        t = e.dxftype()
        if t == "MTEXT":
            text = e.plain_text()
            ins = Vec3(e.dxf.insert)
            h = float(e.dxf.char_height)
            rot = math.radians(e.get_rotation())
            just = MTEXT_JUST.get(int(e.dxf.get("attachment_point", 1)), "Left")
        else:  # TEXT, ATTRIB
            text = e.plain_text()
            halign = int(e.dxf.get("halign", 0))
            valign = int(e.dxf.get("valign", 0))
            p = e.dxf.align_point if (halign or valign) and e.dxf.hasattr("align_point") else e.dxf.insert
            ocs = e.ocs()
            ins = ocs.to_wcs(Vec3(p))
            h = float(e.dxf.height)
            rot = math.radians(float(e.dxf.get("rotation", 0.0)))
            if ocs.uz.z < 0:  # mirrored text reads the other way in world coordinates
                rot = math.pi - rot
            just = TEXT_JUST.get(halign, "Left")
        text = (text or "").strip()
        if not text:
            return
        if self.decode_text:
            text, conv = maybe_decode(text)
            if conv:
                self.decoded.add(text)
        self._add("text", style, top, block, xy=np.array([ins.x, ins.y]), h=h, rot=rot, text=text, just=just)

    def _fill(self, e, style, top, block):
        rings = []
        try:
            paths = zpath.from_hatch(e)
        except Exception:
            self.skipped["HATCH (unreadable boundary)"] += 1
            return
        for p in paths:
            for pts in self._path_polys(p):
                if len(pts) >= 3:
                    rings.append(pts)
        if rings:
            self._add("fill", style, top, block, rings=rings, solid=bool(e.dxf.get("solid_fill", 0)),
                      pattern=e.dxf.get("pattern_name", "SOLID"))

    def entity(self, e, parent, top, block, depth=0):
        t = e.dxftype()
        if t in SKIPPED:
            (self.proxies if "PROXY" in t else self.skipped)[t] += 1
            return
        style = self._style(e, parent)
        if t == "INSERT":
            if depth > 12:
                self.skipped["INSERT (nested too deep)"] += 1
                return
            name = e.dxf.name
            for a in e.attribs:
                if not a.is_invisible:
                    self._text(a, self._style(a, style), top, block or name)
            try:
                children = list(e.virtual_entities())
            except Exception:
                self.skipped["INSERT (cannot explode)"] += 1
                return
            for c in children:
                self.entity(c, style, top, block or name, depth + 1)
            return
        if t in ("DIMENSION", "ARC_DIMENSION", "LEADER", "MULTILEADER", "MLINE"):
            try:
                for c in e.virtual_entities():
                    self.entity(c, style, top, block, depth + 1)
            except Exception:
                self.skipped[t] += 1
            return
        if t in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
            if t != "ATTDEF":
                self._text(e, style, top, block)
            return
        if t == "HATCH":
            self._fill(e, style, top, block)
            return
        if t in ("SOLID", "TRACE", "3DFACE"):
            pts = [Vec3(p) for p in (e.wcs_vertices() if hasattr(e, "wcs_vertices") else e.vertices())]
            ring = np.array([(p.x, p.y) for p in pts])
            if t != "3DFACE" and len(ring) == 4:
                ring = ring[[0, 1, 3, 2]]  # SOLID corner order is Z-shaped
            self._add("fill", style, top, block, rings=[ring], solid=True, pattern="SOLID")
            return
        if t == "POINT":
            p = Vec3(e.dxf.location)
            self._add("point", style, top, block, xy=np.array([p.x, p.y]))
            return
        if t == "CIRCLE":
            c = e.ocs().to_wcs(Vec3(e.dxf.center))
            self._add("circle", style, top, block, c=np.array([c.x, c.y]), r=float(e.dxf.radius))
            return
        if t == "ARC" and abs(e.dxf.extrusion[2] - 1.0) < 1e-9:
            c = Vec3(e.dxf.center)
            self._add("arc", style, top, block, c=np.array([c.x, c.y]), r=float(e.dxf.radius),
                      a0=math.radians(e.dxf.start_angle), a1=math.radians(e.dxf.end_angle))
            return
        try:
            p = zpath.make_path(e)
        except (TypeError, ValueError):
            self.skipped[t] += 1
            return
        closed = bool(getattr(e, "closed", False) or getattr(e, "is_closed", False))
        for pts in self._path_polys(p):
            is_closed = closed or (len(pts) > 2 and np.allclose(pts[0], pts[-1]))
            if is_closed and np.allclose(pts[0], pts[-1]):
                pts = pts[:-1]
            if len(pts) >= 2:
                self._add("poly", style, top, block, xy=pts, closed=bool(is_closed and len(pts) >= 3))


def header_units(doc):
    """Metres per drawing unit from $INSUNITS, or None when the drawing does not say."""
    return INSUNITS.get(int(doc.header.get("$INSUNITS", 0)))


def read_model(path, tol, decode_text=True):
    """(document, primitives, stats) of the model space of a DXF."""
    doc = ezdxf.readfile(str(path))
    fl = Flattener(doc, tol, decode_text)
    for i, e in enumerate(doc.modelspace()):
        fl.entity(e, None, i, None)
    layers = {}
    for layer in doc.layers:
        name = layer.dxf.name
        shown, conv = maybe_decode(name) if decode_text else (name, False)
        layers[name] = {"name": shown, "decoded": conv, "color": abs(layer.color) or 7,
                        "rgb": list(layer.rgb) if layer.has_dxf_attrib("true_color") else None,
                        "off": layer.is_off(), "frozen": layer.is_frozen(), "linetype": layer.dxf.linetype}
    stats = {"primitives": Counter(p["kind"] for p in fl.prims), "skipped": dict(fl.skipped),
             "proxies": dict(fl.proxies), "decoded_texts": len(fl.decoded),
             "decoded_layers": sorted(v["name"] for v in layers.values() if v["decoded"])}
    return doc, fl.prims, layers, stats


def prim_bounds(p):
    """(xmin, ymin, xmax, ymax) of a primitive."""
    k = p["kind"]
    if k == "poly":
        a = p["xy"]
    elif k in ("arc", "circle"):
        return p["c"][0] - p["r"], p["c"][1] - p["r"], p["c"][0] + p["r"], p["c"][1] + p["r"]
    elif k == "fill":
        a = np.vstack(p["rings"])
    else:
        a = p["xy"][None, :]
    return float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())


def scale_prim(p, s, dx=0.0, dy=0.0):
    """A copy of a primitive with coordinates multiplied by s and shifted by (dx, dy)."""
    q = dict(p)
    off = np.array([dx, dy])
    if "xy" in p:
        q["xy"] = p["xy"] * s + off
    if "c" in p:
        q["c"] = p["c"] * s + off
    if "r" in p:
        q["r"] = p["r"] * s
    if "rings" in p:
        q["rings"] = [r * s + off for r in p["rings"]]
    if "h" in p:
        q["h"] = p["h"] * s
    return q
