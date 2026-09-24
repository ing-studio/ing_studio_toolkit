"""Stage documents: numbers and plans read from the project's PDFs (documents.files, --doc) - as data, no AI.

For every PDF:
  text     sheet ids, '<levels> <number> SQM' statements (e.g. 'B1 B2 21900 SQM'), 'QTY' counts, tables of
           'LABEL NUMBER' rows (e.g. area by function) with their legend colours
  scale    documents.scale, else a '1 : N' on the pages, else from the document itself: the area outlined on a level
           plan against the area the sheet states (rounded to a standard scale when within 2 %)
  plans    on sheets that state levels, the area outlined in documents.mark_rgb (pure red) is found by colour, taken on
           the centre of its outline, measured, and placed on the drawing: the page's linework is matched to the
           drawing's (every rotation, then fine, then ICP; the scale is known)
Derived: the programme (floor area by function, above and below ground, parking spaces) and the underground levels
(each level's outline in drawing metres) for the buildings and Archicad stages, and checks of stated against measured.
Result: documents.json.
"""
import math
import os
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from shapely.affinity import affine_transform
from shapely.geometry import mapping

from ..config import settings
from ..geometry.crs import Rigid2D
from ..geometry.register import densify_polylines, icp, peak_angle, rotation_search, to_rigid
from ..io import pdf_doc as P
from ..site import load_site, polylines
from ..util import detail, file_signature, load_json, log, save_json, skip, warn

STANDARD_SCALES = (100, 200, 250, 500, 1000, 1200, 1250, 1500, 2000, 2500, 5000, 10000)


def _files(cfg):
    return [os.path.abspath(f) for f in cfg["documents"]["files"] or []]


def _level_index(name):
    digits = "".join(c for c in name if c.isdigit())
    return int(digits) if digits else 0


def _round_scale(n):
    best = min(STANDARD_SCALES, key=lambda s: abs(math.log(n / s)))
    return best if abs(n / best - 1) <= 0.02 else round(n)


def page_to_drawing(poly_px, px_m, rigid):
    """A polygon in page pixels (y down) -> drawing metres."""
    a, b = math.cos(rigid.angle), math.sin(rigid.angle)
    # p_m = (x*px, -y*px); drawing = R p_m + t
    return affine_transform(poly_px, [a * px_m, b * px_m, b * px_m, -a * px_m, rigid.t[0], rigid.t[1]])


def register(img, px_m, site_pts, site_tree, exclude, d):
    """Page image -> drawing: Rigid2D of page metres (x right, y up) onto the drawing, match statistics, trusted?

    Every rotation (2 deg steps, FFT correlation of the rasterised lines), then fine (0.1 deg, parabola), then ICP.
    A dense drawing correlates a little with any placement, so the placement is trusted by the share of the page's
    lines that fall within 1 m of the drawing's lines, against the same share for the page turned away (baseline)."""
    pts = P.linework_points(img, step=2, exclude=exclude)
    pm = np.column_stack([pts[:, 0] * px_m, -pts[:, 1] * px_m])
    if len(pm) > 250_000:
        pm = pm[np.random.default_rng(0).choice(len(pm), 250_000, replace=False)]
    coarse = rotation_search(pm, site_pts, 2.0, np.arange(-180.0, 180.0, 2.0))
    fine = rotation_search(pm, site_pts, 1.0, np.arange(coarse["angle_deg"] - 2.0, coarse["angle_deg"] + 2.001, 0.1),
                           coarse["T"], 15.0)
    fine = rotation_search(pm, site_pts, 0.5, [peak_angle(fine)], fine["T"], 6.0)
    start = to_rigid(fine)
    rigid, stats = icp(pm, site_pts, start, limits=(3.0,) * 10 + (1.5,) * 10 + (0.75,) * 10)
    moved = float(np.max(np.hypot(*(rigid.apply(pm) - start.apply(pm)).T)))
    if moved > 6.0:
        rigid = start
    c = pm.mean(axis=0)
    base = []
    for turn in (45.0, 90.0, 180.0, 270.0):
        r = Rigid2D(rigid.angle + math.radians(turn), 0.0, 0.0)
        r.t = rigid.apply([c])[0] - r.R @ c
        dd, _ = site_tree.query(r.apply(pm))
        base.append(100.0 * float(np.mean(dd < 1.0)))
    dd, _ = site_tree.query(rigid.apply(pm))
    within = 100.0 * float(np.mean(dd < 1.0))
    stats = {"within_1m_pct": round(within, 1), "median_m": round(float(np.median(dd)), 2),
             "baseline_within_1m_pct": round(float(np.median(base)), 1), "rotation_deg": round(math.degrees(rigid.angle), 3),
             "points": int(len(pm)), "angle_peak_ratio": round(coarse["peak_ratio"], 2)}
    ok = within >= float(d["min_within_1m_pct"]) and within - stats["baseline_within_1m_pct"] >= float(d["min_lift_pct"])
    return rigid, stats, ok


def run(job, force=False):
    cfg = job.cfg
    d = cfg["documents"]
    out = job.w("documents.json")
    files = _files(cfg)
    wanted = {"files": [file_signature(f) for f in files if os.path.isfile(f)],
              "site": file_signature(job.w("site.pkl")), **settings(cfg, "documents")}
    prev = load_json(out) or {}
    if not force and prev.get("inputs") == wanted:
        skip(f"documents: already read ({len(prev.get('documents', []))} document(s))")
        return
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        raise RuntimeError(f"documents: file(s) not found: {', '.join(missing)}")
    result = {"inputs": wanted, "documents": [], "program": None, "underground": []}
    if not files:
        skip("documents: no project PDFs given (documents.files or --doc)")
        save_json(out, result)
        return
    site = load_site(job)
    site_pts = densify_polylines(polylines(site["prims"]), 0.5)
    site_tree = cKDTree(site_pts)
    rgb, tol, dpi = d["mark_rgb"], int(d["mark_tolerance"]), int(d["render_dpi"])
    prefixes = tuple(d["level_prefixes"])
    for path in files:
        doc = P.open_pdf(path)
        name = Path(path).name
        log(f"documents: reading {name} ({doc.page_count} pages) ...")
        pages, all_tables, counts = [], [], []
        text_scale = None
        for i, page in enumerate(doc):
            ws = P.words(page)
            text = P.page_text(ws)
            areas = P.area_statements(text, prefixes)
            # the same statement is often printed twice (Armenian and English): keep one
            uniq = []
            for a in areas:
                if a not in uniq:
                    uniq.append(a)
            info = {"page": i + 1, "sheet": P.sheet_of(ws, page.rect.width), "areas": uniq,
                    "counts": P.count_statements(text), "title": " / ".join(
                        " ".join(w[4] for w in lw) for _, lw in P.lines_of(ws)
                        if any(t in " ".join(w[4] for w in lw).upper() for t in ("UNDERGROUND", "AREA", "PLAN", "LEVEL"))
                    )[:160]}
            text_scale = text_scale or P.scale_of(text)
            for t in P.tables(page, ws):
                # a table ends at its TOTAL row; rows below it are a table of their own (e.g. parking spaces)
                cur = {"page": i + 1, "header": t["header"], "rows": []}
                for r in t["rows"]:
                    cur["rows"].append(r)
                    if r["label"].upper() in ("TOTAL", "ԸՆԴՀԱՆՈՒՐ", "ИТОГО", "ВСЕГО"):
                        all_tables.append(cur)
                        cur = {"page": i + 1, "header": "", "rows": []}
                if cur["rows"]:
                    all_tables.append(cur)
            counts += [{"page": i + 1, "label": l, "value": n} for l, n in info["counts"]]
            pages.append(info)

        # ---- plans: outlined areas on sheets that state levels
        plan_pages = [p for p in pages if any(levels for levels, _ in p["areas"]) or
                      (p["areas"] and d["read_total_outlines"])]
        marks = {}
        for p in plan_pages:
            img = P.render(doc[p["page"] - 1], dpi)
            found = P.marked_areas(img, rgb, tol, min_px=int(d["min_mark_px"]))
            if found:
                marks[p["page"]] = (img, max(found, key=lambda f: f[0].area))
        scale, scale_src = None, None
        if d["scale"] != "auto":
            scale, scale_src = float(d["scale"]), "documents.scale"
        elif text_scale:
            scale, scale_src = float(text_scale), "text on the sheets"
        else:
            est = []
            for p in plan_pages:
                if p["page"] not in marks:
                    continue
                for levels, value in p["areas"]:
                    if levels:
                        px_area = marks[p["page"]][1][0].area
                        per_level = value / len(levels)
                        est.append(math.sqrt(per_level / px_area) / (0.0254 / dpi))
            if est:
                raw = float(np.median(est))
                scale = float(_round_scale(raw))
                scale_src = (f"the sheets' own stated areas against the outlined areas (1:{raw:,.0f} from {len(est)} "
                             f"sheets, spread {100 * (max(est) - min(est)) / raw:.1f} %)")
        entry = {"file": name, "path": path, "pages": doc.page_count, "sheets": pages, "tables": all_tables,
                 "counts": counts, "scale": scale, "scale_source": scale_src, "plans": []}
        if marks and not scale:
            warn(f"documents: {name}: the drawing scale is unknown (no '1 : N' text, no stated areas) - set "
                 "documents.scale; its plans are not used")
        elif marks:
            px_m = 0.0254 / dpi * scale
            log(f"documents: {name}: scale 1:{scale:,.0f} ({scale_src}); placing its plans on the drawing ...")
            ref = None  # (page, rigid, stats, linework tree) of the first placed sheet
            for p in plan_pages:
                if p["page"] not in marks:
                    continue
                img, (poly_px, width_px, filled_px) = marks[p["page"]]
                excl = P.colour_mask(img, rgb, tol) | P.text_mask(doc[p["page"] - 1], img.shape[:2], dpi)
                rigid = stats = None
                if ref is not None:
                    pts = P.linework_points(img, step=4, exclude=excl)
                    dd, _ = ref[3].query(pts, distance_upper_bound=2.5)
                    same = float(np.mean(np.isfinite(dd)))
                    if same >= 0.75:  # the same drawing in the same place: the first sheet's placement holds
                        rigid, stats = ref[1], dict(ref[2], reused_from_page=ref[0], same_linework_pct=round(100 * same))
                if rigid is None:
                    rigid, stats, good = register(img, px_m, site_pts, site_tree, excl, d)
                    if not good:
                        warn(f"documents: {name} page {p['page']}: its plan could not be placed on the drawing "
                             f"({stats['within_1m_pct']}% of its lines within 1 m of the drawing's, "
                             f"{stats['baseline_within_1m_pct']}% when turned away); its outline is not used")
                        continue
                    if ref is None:
                        ref = (p["page"], rigid, stats, cKDTree(P.linework_points(img, step=4, exclude=excl)))
                poly = page_to_drawing(poly_px, px_m, rigid)
                measured = float(poly.area)
                for levels, value in (p["areas"] or [([], None)]):
                    per_level = value / len(levels) if (value and levels) else value
                    plan = {"page": p["page"], "sheet": p["sheet"], "levels": levels, "stated_m2": value,
                            "stated_per_level_m2": per_level, "measured_m2": round(measured, 1),
                            "ratio": round(measured / per_level, 4) if (per_level and levels) else None,
                            "outline_width_m": round(width_px * px_m, 2), "placement": stats,
                            "polygon": mapping(poly)}
                    entry["plans"].append(plan)
                    detail(f"documents: {name} page {p['page']} ({p['sheet']}): {' '.join(levels) or 'outline'} - "
                           f"stated {value or 0:,.0f} m2" + (f" ({len(levels)} levels, {per_level:,.0f} each)"
                                                             if len(levels) > 1 else "")
                           + (f", measured {measured:,.0f} m2 per level" if levels else
                              f", outline of {measured:,.0f} m2 (all levels together)")
                           + (f" ({100 * (measured / per_level - 1):+.1f} %)" if (per_level and levels) else "")
                           + f"; placed with {stats.get('within_1m_pct', '-')}% of its lines within 1 m of the drawing")
                    break
        result["documents"].append(entry)

    # ---- the programme and the underground levels, from all documents
    program = None
    below = [s.upper().rstrip("*") for s in d["below_ground_functions"]]
    for e in result["documents"]:
        for t in e["tables"]:
            head = t["header"].upper()
            if len(t["rows"]) >= 2 and any(k in head for k in ("AREA", "SQM", "ՄԱԿԵՐԵՍ", "ПЛОЩАД")):
                fn = {r["label"]: r["value"] for r in t["rows"] if r["label"].upper() not in
                      ("TOTAL", "ԸՆԴՀԱՆՈՒՐ", "ИТОГО", "ВСЕГО")}
                total = next((r["value"] for r in t["rows"] if r["label"].upper() in
                              ("TOTAL", "ԸՆԴՀԱՆՈՒՐ", "ИТОГО", "ВСЕГО")), sum(fn.values()))
                colours = {r["label"]: r["rgb"] for r in t["rows"] if r["rgb"]}
                above = {k: v for k, v in fn.items() if not any(k.upper().startswith(b) for b in below)}
                program = {"source": f"{e['file']} page {t['page']}", "functions_m2": fn, "total_m2": total,
                           "above_ground_m2": sum(above.values()), "below_ground_m2": total - sum(above.values()),
                           "above_ground_functions": list(above), "colours": colours}
                break
        spaces = [c for c in e["counts"] if "PARKING" in c["label"].upper() or c["label"].upper() == "QTY"]
        spaces += [{"page": t["page"], "label": r["label"], "value": r["value"]} for t in e["tables"] for r in t["rows"]
                   if "PARKING LOT" in r["label"].upper()]
        if program is not None and spaces:
            program["parking_spaces"] = int(spaces[0]["value"])
        if program:
            break
    result["program"] = program
    levels = {}
    for e in result["documents"]:
        for p in e["plans"]:
            for lv in p["levels"]:
                levels.setdefault(lv, {"level": lv, "index": _level_index(lv), "polygon": p["polygon"],
                                       "area_m2": p["measured_m2"], "stated_m2": p["stated_per_level_m2"],
                                       "source": f"{e['file']} page {p['page']} ({p['sheet']})"})
    result["underground"] = sorted(levels.values(), key=lambda v: v["index"])
    if program:
        log(f"documents: programme ({program['source']}): {program['total_m2']:,.0f} m2 - "
            + ", ".join(f"{k.lower()} {v:,.0f}" for k, v in program["functions_m2"].items())
            + (f"; {program['parking_spaces']:,} parking spaces" if program.get("parking_spaces") else ""))
    if result["underground"]:
        log(f"documents: underground levels {', '.join(v['level'] for v in result['underground'])} placed on the "
            f"drawing ({sum(v['area_m2'] for v in result['underground']):,.0f} m2 in all)")
    save_json(out, result)
