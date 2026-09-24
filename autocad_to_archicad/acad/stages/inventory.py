"""Stage inventory: the drawings in model space, which one is the site plan, and its layers.

A DWG set often holds several drawings side by side (site plan, sections, details, legend). They are found as groups
of geometry separated by empty space (drawing.region_gap_m); the site plan is the group with the most geometry, or
drawing.region. Everything later works on the site plan only, in metres.
Results: site.pkl (the site plan's primitives in metres + layer table), inventory.json, layers.csv.
"""
import csv
import pickle
from collections import Counter, defaultdict

import numpy as np
from scipy import ndimage

from ..config import settings
from ..io.dxf_model import prim_bounds, scale_prim
from ..util import detail, file_signature, load_json, log, save_json, skip


def _vertices(p):
    k = p["kind"]
    if k == "poly":
        return p["xy"]
    if k == "fill":
        return np.vstack(p["rings"])
    if k in ("arc", "circle"):
        return p["c"][None, :]
    return p["xy"][None, :]


def find_regions(prims, gap_m):
    """Groups of geometry at least gap_m apart: list of dicts (bbox in metres, primitive count), largest first."""
    pts = np.vstack([_vertices(p) for p in prims])
    owner = np.repeat(np.arange(len(prims)), [len(_vertices(p)) for p in prims])
    cell = gap_m / 2.0
    lo = pts.min(axis=0)
    ij = np.floor((pts - lo) / cell).astype(np.int64)
    shape = ij.max(axis=0) + 1
    if shape[0] * shape[1] > 60_000_000:  # absurd extents (stray geometry far away): coarser cells
        cell = float(max(pts.max(axis=0) - lo)) / 6000.0
        ij = np.floor((pts - lo) / cell).astype(np.int64)
        shape = ij.max(axis=0) + 1
    grid = np.zeros((shape[1], shape[0]), bool)
    grid[ij[:, 1], ij[:, 0]] = True
    lab, n = ndimage.label(ndimage.binary_dilation(grid, iterations=max(1, int(round(gap_m / cell / 2)))))
    comp = lab[ij[:, 1], ij[:, 0]]
    regions = []
    for c in range(1, n + 1):
        sel = comp == c
        if not sel.any():
            continue
        members = np.unique(owner[sel])
        p = pts[sel]
        regions.append({"bbox": [float(v) for v in (*p.min(axis=0), *p.max(axis=0))], "primitives": int(len(members)),
                        "_members": members})
    regions.sort(key=lambda r: -r["primitives"])
    return regions


def run(job, force=False):
    cfg = job.cfg
    out_json, site_path = job.w("inventory.json"), job.w("site.pkl")
    wanted = {"model": file_signature(job.w("model.pkl")), **settings(cfg, "drawing")}
    prev = load_json(out_json) or {}
    if not force and prev.get("inputs") == wanted and site_path.exists():
        skip(f"inventory: site plan already found ({prev['site']['primitives']:,} primitives)")
        return
    with open(job.w("model.pkl"), "rb") as f:
        model = pickle.load(f)
    s = model["unit_m"]
    prims = [scale_prim(p, s) for p in model["prims"]]
    region_cfg = cfg["drawing"]["region"]
    regions = find_regions(prims, float(cfg["drawing"]["region_gap_m"]))
    if region_cfg == "auto":
        site = regions[0]
        members = set(site["_members"].tolist())
    else:
        x1, y1, x2, y2 = (v * s for v in region_cfg)
        site = {"bbox": [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]}
        members = set()
        for i, p in enumerate(prims):
            b = prim_bounds(p)
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if site["bbox"][0] <= cx <= site["bbox"][2] and site["bbox"][1] <= cy <= site["bbox"][3]:
                members.add(i)
        site["primitives"] = len(members)
    site_prims = [p for i, p in enumerate(prims) if i in members]
    for r in regions:
        r.pop("_members", None)
    site.pop("_members", None)
    bx = site["bbox"]
    log(f"inventory: {len(regions)} drawing(s) in model space; site plan = {site['primitives']:,} primitives, "
        f"{bx[2] - bx[0]:,.0f} x {bx[3] - bx[1]:,.0f} m at x {bx[0]:,.0f}..{bx[2]:,.0f}, y {bx[1]:,.0f}..{bx[3]:,.0f}")
    for r in regions[1:6]:
        b = r["bbox"]
        detail(f"inventory: other drawing: {r['primitives']:,} primitives, {b[2] - b[0]:,.0f} x {b[3] - b[1]:,.0f} m "
               f"at x {b[0]:,.0f}, y {b[1]:,.0f}")

    per_layer = defaultdict(Counter)
    for p in site_prims:
        per_layer[p["layer"]][p["kind"]] += 1
    rows = []
    for raw, info in model["layers"].items():
        c = per_layer.get(raw, Counter())
        rows.append({"layer": raw, "shown_as": info["name"], "in_site_plan": sum(c.values()),
                     **{k: c.get(k, 0) for k in ("poly", "arc", "circle", "fill", "text", "point")},
                     "off": info["off"], "frozen": info["frozen"], "aci": info["color"]})
    rows.sort(key=lambda r: -r["in_site_plan"])
    with open(job.w("layers.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    used = sum(1 for r in rows if r["in_site_plan"])
    log(f"inventory: {used} layers used by the site plan (list: {job.w('layers.csv')})")
    with open(site_path, "wb") as f:
        pickle.dump({"prims": site_prims, "layers": model["layers"], "bbox": bx}, f, protocol=pickle.HIGHEST_PROTOCOL)
    save_json(out_json, {"inputs": wanted, "unit_m": s, "regions": regions, "site": site,
                         "layers_used": used, "blocks": Counter(p["block"] for p in site_prims if p["block"]).most_common(30)})
