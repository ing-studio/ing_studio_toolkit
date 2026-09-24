"""Stage read: the drawing as DXF (a DWG through AutoCAD's console), then as a flat list of primitives.

Results: drawing.dxf, model.pkl (primitives in drawing units, layers, statistics), read.json.
Units (drawing.units overrides): $INSUNITS when the drawing has it, checked against the size of its closed outlines
(a drawing started from an inch template keeps inches while it is drawn in mm); without it a guess from the text
heights and the size of the drawing. The georef stage checks the unit again: it matches the drawing to the map at
scale 1.
"""
import pickle
import shutil
from collections import Counter
from pathlib import Path

import numpy as np

from ..config import UNITS, settings
from ..io.dwg_reader import dwg_to_dxf
from ..io.dxf_model import header_units, prim_bounds, read_model
from ..util import detail, load_json, log, save_json, skip, warn


TYPICAL_SHAPE_M = (3.0, 80.0, 15.0)  # median size of the closed outlines of a site plan (buildings, plots): range, usual


def typical_shape(prims):
    """Median diagonal (drawing units) of the closed outlines (buildings, plots), else of the fills. None if too few."""
    def diag(pts):
        return float(np.hypot(*(pts.max(axis=0) - pts.min(axis=0))))
    closed = [diag(p["xy"]) for p in prims if p["kind"] == "poly" and p.get("closed") and len(p["xy"]) >= 3]
    fills = [diag(np.vstack(p["rings"])) for p in prims if p["kind"] == "fill" and p["rings"]]
    for sizes in (closed, fills):
        sizes = [s for s in sizes if s > 0]
        if len(sizes) >= 20:
            return float(np.median(sizes))
    return None


def check_units(prims, unit_m):
    """(metres per unit, note) - the unit the drawing states, unless its outlines are then implausibly sized for a site
    plan; then the common unit that makes them the most usual size (a DWG started from an inch template keeps
    $INSUNITS = inches while it is drawn in mm)."""
    size = typical_shape(prims)
    if size is None:
        return unit_m, None
    lo, hi, usual = TYPICAL_SHAPE_M
    if lo <= size * unit_m <= hi:
        return unit_m, None
    fits = [(abs(np.log(size * m / usual)), name, m) for name, m in UNITS.items() if lo <= size * m <= hi]
    if not fits:
        return unit_m, None
    _, name, m = min(fits)
    return m, (f"with the stated unit ({unit_m:g} m) its typical closed shape would be {size * unit_m:,.0f} m across; "
               f"in {name} it is {size * m:,.1f} m - using {name}")


def guess_units(prims):
    """(metres per unit, evidence) from typical text heights, else the drawing size."""
    heights = np.array([p["h"] for p in prims if p["kind"] == "text" and p["h"] > 0])
    b = np.array([prim_bounds(p) for p in prims]) if prims else np.zeros((0, 4))
    size = 0.0
    if len(b):
        cx, cy = (b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2
        size = float(max(np.percentile(cx, 95) - np.percentile(cx, 5), np.percentile(cy, 95) - np.percentile(cy, 5)))
    ev = {"text_height_median": float(np.median(heights)) if len(heights) else None, "drawing_size_p5_p95": size}
    if len(heights) >= 5:
        h = float(np.median(heights))
        unit = "m" if h < 20 else "cm" if h < 300 else "mm"
        ev["rule"] = f"median text height {h:g} units -> {unit}"
    else:
        unit = "mm" if size > 20000 else "m"
        ev["rule"] = f"drawing size {size:,.0f} units -> {unit}"
    return UNITS[unit], unit, ev


def run(job, force=False):
    cfg = job.cfg
    out_json, model_path, dxf_path = job.w("read.json"), job.w("model.pkl"), job.w("drawing.dxf")
    wanted = {"drawing": job.drawing_signature(), **settings(cfg, "read", "drawing.units", "drawing.text_encoding")}
    prev = load_json(out_json) or {}
    if not force and prev.get("inputs") == wanted and model_path.exists():
        skip(f"read: {Path(job.drawing).name} already read ({prev['primitives_total']:,} primitives)")
        return
    if Path(job.drawing).suffix.lower() == ".dwg":
        log(f"read: converting {Path(job.drawing).name} to DXF with AutoCAD's console ...")
        conv = dwg_to_dxf(cfg, job.drawing, dxf_path)
    else:
        shutil.copyfile(job.drawing, dxf_path)
        conv = {"xrefs": [], "aec_export": False}

    # flattening tolerance needs the unit: header first, else a first read with a coarse tolerance to guess it
    import ezdxf
    doc = ezdxf.readfile(str(dxf_path))
    forced = cfg["drawing"]["units"]
    unit_m = UNITS[forced] if forced != "auto" else header_units(doc)
    evidence = {"source": "setting drawing.units" if forced != "auto" else "$INSUNITS" if unit_m else "guess"}
    decode = cfg["drawing"]["text_encoding"] == "auto"
    if unit_m is None:
        _, rough, _, _ = read_model(dxf_path, tol=1.0, decode_text=False)
        unit_m, name, ev = guess_units(rough)
        evidence.update(ev)
        warn(f"read: the drawing does not say its unit; guessed {name} ({ev['rule']}) - set drawing.units if wrong")
    tol = 0.01 / unit_m  # curves within 1 cm
    doc, prims, layers, stats = read_model(dxf_path, tol=tol, decode_text=decode)
    if forced == "auto" and evidence["source"] == "$INSUNITS":
        checked, note = check_units(prims, unit_m)
        if note:
            warn(f"read: the drawing's unit setting does not fit its shapes: {note} (set drawing.units if wrong)")
            evidence.update({"source": "$INSUNITS corrected by shape sizes", "stated_unit_m": unit_m, "rule": note})
            unit_m = checked
            doc, prims, layers, stats = read_model(dxf_path, tol=0.01 / unit_m, decode_text=decode)
    with open(model_path, "wb") as f:
        pickle.dump({"prims": prims, "layers": layers, "unit_m": unit_m}, f, protocol=pickle.HIGHEST_PROTOCOL)
    kinds = Counter(p["kind"] for p in prims)
    log(f"read: {len(prims):,} primitives ({', '.join(f'{k} {v:,}' for k, v in kinds.most_common())}), "
        f"{len(layers)} layers, unit = {unit_m:g} m")
    if stats["skipped"]:
        detail(f"read: not converted: {stats['skipped']}")
    if stats["proxies"]:
        warn(f"read: {sum(stats['proxies'].values())} custom (proxy) objects could not be read: {stats['proxies']}")
    if stats["decoded_layers"] or stats["decoded_texts"]:
        log(f"read: old Armenian font text turned into Armenian letters: {len(stats['decoded_layers'])} layer names "
            f"(e.g. {', '.join(stats['decoded_layers'][:2])}), {stats['decoded_texts']} texts")
    save_json(out_json, {"inputs": wanted, "conversion": conv, "unit_m": unit_m, "unit_evidence": evidence,
                         "primitives_total": len(prims), "primitives": dict(kinds), "layers": len(layers),
                         "skipped": stats["skipped"], "proxies": stats["proxies"],
                         "decoded_layers": stats["decoded_layers"], "decoded_texts": stats["decoded_texts"]})
