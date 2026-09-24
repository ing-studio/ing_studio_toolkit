"""Stage report: <drawing>_FromDWG_report.html next to the PLN - what was built, how it was placed, the street
profiles against the rules, cut and fill, and everything that needs a look. One self-contained file (pictures inside)."""
import base64
import html
import io
import time
from pathlib import Path

import numpy as np
from shapely.geometry import shape

from .. import __version__
from ..geometry.crs import LonLatUTM, Rigid2D
from ..geometry.raster import read_raster
from ..geometry.register import densify_polylines
from ..site import load_site, on_layers, polylines
from ..util import load_json, ok

CSS = """
body{font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#f6f6f4;color:#1d1d1b}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px} h2{font-size:18px;margin:32px 0 8px;border-bottom:1px solid #ccc;padding-bottom:4px}
h3{font-size:15px;margin:18px 0 6px} .muted{color:#666} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.warnc{color:#9a6700;font-weight:600} .tile{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px 12px} .tile b{display:block;font-size:20px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px} th,td{border:1px solid #ddd;padding:4px 6px;text-align:left}
th{background:#eee} td.num{text-align:right;font-variant-numeric:tabular-nums} .bad{color:#b3261e;font-weight:600} .good{color:#1b6e2e}
img{max-width:100%;background:#fff;border:1px solid #ddd;border-radius:4px} ul.warn li{margin:4px 0}
code{background:#eee;padding:1px 4px;border-radius:3px}
"""


def _png(fig):
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=90, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _img(src, alt):
    return f'<img src="{src}" alt="{html.escape(alt)}">'


def _table(rows, head, num=()):
    out = ["<table><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in head) + "</tr>"]
    for r in rows:
        out.append("<tr>" + "".join(f'<td class="{"num" if i in num else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>")
    return "".join(out) + "</table>"


def fig_georef(job, geo, site):
    import matplotlib.pyplot as plt
    g2u, tr = Rigid2D.from_json(geo["transform"]), LonLatUTM(geo["epsg"])
    P = g2u.apply(densify_polylines(polylines(on_layers(site, geo["building_layers"])), 1.0))
    ways = load_json(job.w("osm.json"))["ways"]
    c = np.array(geo["site_centre_utm"])
    fig, axs = plt.subplots(1, 2, figsize=(15, 7.5))
    for ax, r in zip(axs, (700, 120)):
        for w in ways:
            if "highway" in w["tags"]:
                continue
            q = tr.to_utm(w["lonlat"])
            if np.abs(q.mean(axis=0) - c).max() < r * 1.3:
                ax.plot(q[:, 0], q[:, 1], color="0.2", lw=0.6)
        m = (np.abs(P - c) < r).all(axis=1)
        ax.scatter(P[m, 0], P[m, 1], s=0.3, color="#d62728")
        ax.set_xlim(c[0] - r, c[0] + r)
        ax.set_ylim(c[1] - r, c[1] + r)
        ax.set_aspect("equal")
        ax.set_title(f"drawing buildings (red) on OpenStreetMap (black), {2 * r} m wide", fontsize=10)
        ax.tick_params(labelsize=7)
    return _png(fig)


def fig_site(job, ter, roads, ew):
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    z1, gt, _ = read_raster(job.w("terrain_design.tif"))
    dz, _, _ = read_raster(job.w("cutfill.tif"))
    ext = [gt[0], gt[0] + gt[1] * z1.shape[1], gt[3] + gt[5] * z1.shape[0], gt[3]]
    ls = LightSource(azdeg=315, altdeg=45)
    shade = ls.hillshade(np.nan_to_num(z1, nan=np.nanmin(z1)), vert_exag=1.5, dx=gt[1], dy=gt[1])
    out = []
    fig, ax = plt.subplots(figsize=(15, 9))
    ax.imshow(np.where(np.isfinite(z1), shade, np.nan), extent=ext, cmap="gray")
    im = ax.imshow(z1, extent=ext, cmap="terrain", alpha=0.45)
    plt.colorbar(im, ax=ax, shrink=0.6, label="altitude m")
    for key, col in (("existing_area", "#555555"), ("carriageway_area", "#d62728"), ("sidewalk_area", "#ff7f0e")):
        if roads.get(key):
            g = shape(roads[key])
            for p in getattr(g, "geoms", [g]):
                ax.fill(*p.exterior.xy, color=col, alpha=0.45, lw=0)
    for e in roads["proposed"]:
        xy = np.array(e["xy"])
        ax.plot(xy[:, 0], xy[:, 1], color="#8b0000", lw=0.9)
        if e["s"][-1] > 60:
            m = xy[len(xy) // 2]
            ax.text(m[0], m[1], e["name"].split()[-1], fontsize=8, color="#8b0000", weight="bold")
    for t in roads["summary"].get("tie_ins", []):
        bad = abs(t.get("mismatch_m", 0)) > 0.1
        ax.plot(*t["xy"], "o", color="#b3261e" if bad else "#1b6e2e", ms=6)
    wpath = job.w("walls.npy")
    if wpath.exists():
        w = np.load(wpath)
        if len(w):
            ax.plot(w[:, 0], w[:, 1], ".", color="#e6b800", ms=0.6)
    ax.set_aspect("equal")
    ax.set_title("site model: existing streets (grey), new carriageways (red), sidewalks (orange), retaining walls "
                 "(yellow), street ends tied in (green) / off by > 0.1 m (red)", fontsize=10)
    out.append(_png(fig))
    fig, ax = plt.subplots(figsize=(15, 9))
    im = ax.imshow(np.where(np.abs(np.nan_to_num(dz)) > 0.05, dz, np.nan), extent=ext, cmap="RdBu",
                   vmin=-8, vmax=8)
    ax.imshow(np.where(np.isfinite(z1), shade, np.nan), extent=ext, cmap="gray", alpha=0.25)
    plt.colorbar(im, ax=ax, shrink=0.6, label="fill (+) / cut (-) m")
    ax.set_aspect("equal")
    ax.set_title(f"cut and fill: cut {ew['cut_m3']:,} m3, fill {ew['fill_m3']:,} m3", fontsize=10)
    out.append(_png(fig))
    return out


def fig_profile(e, cfg):
    import matplotlib.pyplot as plt
    s, z, g = np.array(e["s"]), np.array(e["z"]), np.array(e["ground"], dtype=float)
    grade = np.array(e["grade"], dtype=float) * 1000
    lim = np.array(e["limit"]) * 1000
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 4.6), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
    a1.fill_between(s, g, z, where=z >= g, color="#1f77b4", alpha=0.25, label="fill")
    a1.fill_between(s, g, z, where=z < g, color="#d62728", alpha=0.25, label="cut")
    a1.plot(s, g, color="#2ca02c", lw=1.2, label="ground")
    a1.plot(s, z, color="#111", lw=1.6, label="design (axis)")
    a1.set_ylabel("altitude m")
    a1.legend(fontsize=8, ncol=4, loc="best")
    a1.grid(alpha=0.3)
    a2.step(s, grade, where="post", color="#111", lw=1)
    a2.plot(s, lim, color="#b3261e", lw=0.8, ls="--")
    a2.plot(s, -lim, color="#b3261e", lw=0.8, ls="--")
    a2.set_ylabel("grade per mille")
    a2.set_xlabel("chainage m")
    a2.grid(alpha=0.3)
    a1.set_title(e["name"], fontsize=10)
    return _png(fig)


def fig_buildings(job, bj, docs, roads):
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    fig, ax = plt.subplots(figsize=(15, 10))
    ex = [np.asarray(shape(b["polygon"]).exterior.coords) for b in bj["existing"]]
    if ex:
        h = np.array([b["height_m"] for b in bj["existing"]])
        pc = PolyCollection(ex, array=h, cmap="Greys", edgecolor="0.5", linewidths=0.3, clim=(0, 40))
        ax.add_collection(pc)
    pr = [np.asarray(shape(b["polygon"]).exterior.coords) for b in bj["proposed"]]
    if pr:
        n = np.array([b["storeys"] for b in bj["proposed"]])
        pc = PolyCollection(pr, array=n, cmap="viridis", edgecolor="k", linewidths=0.4, clim=(1, max(12, n.max())))
        ax.add_collection(pc)
        plt.colorbar(pc, ax=ax, shrink=0.6, label="storeys of the new buildings")
        for b in bj["proposed"]:
            if b["source"] == "no shadow in the drawing (assumed)":
                g = shape(b["polygon"])
                ax.plot(*g.exterior.xy, color="#b3261e", lw=1.0, ls="--")
    for d in bj.get("demolished", []):
        g = shape(d["polygon"])
        ax.fill(*g.exterior.xy, facecolor="none", edgecolor="#b3261e", hatch="xxx", lw=0.6)
    for lv in bj.get("underground", []):
        g = shape(lv["polygon"])
        ax.plot(*g.exterior.xy, lw=1.0, label=f"{lv['level']} (floor {lv['floor_z']:.1f} m)")
    if bj["trees"]:
        t = np.array([[q["x"], q["y"]] for q in bj["trees"]])
        ax.plot(t[:, 0], t[:, 1], ".", color="#2ca02c", ms=2)
    for e in roads["proposed"]:
        xy = np.array(e["xy"])
        ax.plot(xy[:, 0], xy[:, 1], color="#8b0000", lw=0.7)
    pts = [np.asarray(shape(b["polygon"]).exterior.coords) for b in bj["proposed"]] or ex
    if pts:
        allp = np.vstack(pts)
        pad = 60
        ax.set_xlim(allp[:, 0].min() - pad, allp[:, 0].max() + pad)
        ax.set_ylim(allp[:, 1].min() - pad, allp[:, 1].max() + pad)
    ax.set_aspect("equal")
    if bj.get("underground"):
        ax.legend(fontsize=7, loc="lower left")
    ax.set_title("new buildings by storeys (red dashes: no shadow drawn, 1 storey assumed), existing buildings (grey "
                 "by height; red cross-hatch: to be demolished), underground levels from the documents, trees (green), "
                 "new street axes", fontsize=9)
    return _png(fig)


def _warn_list(items):
    return "<ul class='warn'>" + "".join(f"<li>{w}</li>" for w in items) + "</ul>"


def run(job, force=False):
    import matplotlib
    matplotlib.use("Agg")
    from .. import norms
    cfg = job.cfg
    rd, inv, geo, ter, roads, ew, acj, bj, docs, lj = (load_json(job.w(n)) for n in (
        "read.json", "inventory.json", "georef.json", "terrain.json", "roads.json", "earthworks.json", "archicad.json",
        "buildings.json", "documents.json", "layers.json"))
    if not all((rd, inv, geo, ter, roads, ew, lj)):
        raise RuntimeError("run the earlier stages first")
    bj = bj or {"existing": [], "proposed": [], "demolished": [], "underground": [], "trees": [], "checks": {}}
    docs = docs or {"documents": [], "program": None, "underground": []}
    site = load_site(job)
    summ = roads["summary"]
    std = summ.get("standard") or {}
    prof, rck = cfg["roads"]["profile"], cfg["roads"]["checks"]
    warnings = list(roads.get("warnings", []))
    for x in rd["conversion"].get("xrefs", []):
        if not x["loaded"]:
            warnings.insert(0, f"The drawing refers to <code>{html.escape(x['name'])}</code> "
                               f"({html.escape(x['path'])}), which was not found: its content is missing.")
    ue = rd["unit_evidence"]
    if ue.get("source") == "guess":
        warnings.insert(0, f"The drawing does not state its unit; {rd['unit_m']:g} m per unit was assumed "
                           f"({html.escape(ue['rule'])}) and confirmed by the map match.")
    elif "corrected" in ue.get("source", ""):
        warnings.insert(0, f"The drawing says its unit is {ue['stated_unit_m']:g} m, but its shapes only make sense "
                           f"in {rd['unit_m']:g} m ({html.escape(ue['rule'])}); the map match confirmed it.")
    walls = ew["retaining_walls"]
    if walls.get("length_m"):
        warnings.append(f"Retaining walls needed along about {walls['length_m']:,.0f} m (yellow on the site map; "
                        f"{walls.get('modelled_m', 0):,.0f} m modelled on 'Site - Retaining walls').")
    for b in ew.get("bridges", []):
        warnings.append(f"{html.escape(b['street'])} {b['from_m']:.0f}–{b['to_m']:.0f} m would stand up to "
                        f"{b['max_height_m']:.0f} m above the ground: a bridge / viaduct (the ground is left as it is "
                        "under it).")
    if ew.get("loose_paved_m2"):
        warnings.append(f"{ew['loose_paved_m2']:,} m² of paved area has no street axis through it (ramps, parking): "
                        "left on the existing ground.")
    alt = ter.get("altitude", {})
    if alt.get("method") == "world_terrain":
        warnings.append(f"Altitudes come from the open world terrain model (±{alt.get('mad_m')} m spread): set "
                        "<code>cloud.z_to_altitude</code> from a surveyed benchmark for exact altitudes.")
    bchk = bj.get("checks", {})
    assumed = [b for b in bj["proposed"] if b["source"] == "no shadow in the drawing (assumed)"]
    if assumed:
        warnings.append(f"{len(assumed)} new building outlines ({sum(b['area_m2'] for b in assumed):,.0f} m²) have no "
                        "shadow in the drawing: shown 1 storey high (red dashes on the buildings map).")
    ex_assumed = [b for b in bj["existing"] if "assumed" in b["source"]]
    if ex_assumed:
        warnings.append(f"{len(ex_assumed)} of {len(bj['existing'])} existing buildings have no height in "
                        "OpenStreetMap: their height is assumed (see Buildings).")
    sp = bchk.get("spacing")
    if sp and sp["close_pairs"]:
        warnings.append(f"{len(sp['close_pairs'])} gaps between new buildings are under {sp['closer_than_m']} m "
                        f"({sp['under_fire_min']} under the 6 m fire distance): " + ", ".join(
                            f"at ({c['at'][0]:.0f}, {c['at'][1]:.0f}) {c['gap_m']:.1f} m" for c in sp["close_pairs"][:8]))
    if bj.get("demolished"):
        warnings.append(f"{len(bj['demolished'])} existing buildings ({sum(d['area_m2'] for d in bj['demolished']):,.0f} m²) "
                        "stand where the drawing has new buildings or streets: left out as to be demolished (red "
                        "cross-hatch on the buildings map, listed under Buildings).")
    if "site.lonlat" not in geo.get("lonlat_source", "site.lonlat"):
        warnings.append(f"The site was found from the {html.escape(geo['lonlat_source'])} and confirmed by the building "
                        "match (see Placement).")

    n_ex, n_pr = len(bj["existing"]), len(bj["proposed"])
    tiles = [("site plan", f"{inv['site']['bbox'][2] - inv['site']['bbox'][0]:,.0f} × "
                           f"{inv['site']['bbox'][3] - inv['site']['bbox'][1]:,.0f} m"),
             ("terrain", f"{ter['area_ha']} ha"), ("existing streets", f"{len(roads['existing'])} pieces"),
             ("new streets", f"{summ.get('length_m', 0) / 1000:.2f} km"),
             ("steepest new grade", f"{max((e['checks']['max_grade_permille'] for e in roads['proposed']), default=0):.0f} ‰"),
             ("cut / fill", f"{ew['cut_m3'] / 1000:,.0f}k / {ew['fill_m3'] / 1000:,.0f}k m³"),
             ("buildings", f"{n_ex} existing, {n_pr} new, {len(bj.get('demolished', []))} demolished"),
             ("trees", f"{(acj or {}).get('created', {}).get('trees', len(bj['trees'])):,}"),
             ("underground levels", f"{len(bj.get('underground', []))}")]
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
             f"content='width=device-width,initial-scale=1'><title>Site model report</title><style>{CSS}</style></head>"
             f"<body><main><h1>Site model: {html.escape(Path(job.drawing).name)}</h1>"
             f"<div class='muted'>autocad_to_archicad {__version__} · {time.strftime('%Y-%m-%d %H:%M')} · "
             f"{html.escape(job.output_pln)}</div><h2>Summary</h2><div class='grid'>"
             + "".join(f"<div class='tile'><span class='muted'>{k}</span><b>{v}</b></div>" for k, v in tiles) + "</div>"]
    parts.append("<h2>Needs a look</h2>" + _warn_list(warnings))

    # ---- layers
    shown = lj.get("shown", {})
    rows = []
    for role, names in lj["roles"].items():
        for r in names:
            rows.append([role.replace("_", " "), f"<code>{html.escape(shown.get(r, r))}</code>",
                         "setting" if lj["how"].get(role) == "setting" else html.escape(lj["evidence"].get(r, "same name as a layer found"))])
        if not names:
            rows.append([role.replace("_", " "), "—", "none found"])
    parts.append("<h2>What the layers hold</h2><p>Worked out from the drawing's geometry and OpenStreetMap (a role can be "
                 "fixed with <code>--set layers.&lt;role&gt;=[\"*NAME*\"]</code>).</p>"
                 + _table(rows, ["role", "layer", "why"]))

    # ---- site
    parts.append("<h2>Site model</h2>" + "".join(_img(s, "site map") for s in fig_site(job, ter, roads, ew)))
    parts.append(_table([[k.replace("_", " "), f"{v:,}" if isinstance(v, (int, float)) else v] for k, v in (
        ("cut m³", ew["cut_m3"]), ("fill m³", ew["fill_m3"]), ("balance m³ (fill − cut)", ew["balance_m3"]),
        ("deepest cut m", ew["max_cut_m"]), ("highest fill m", ew["max_fill_m"]),
        ("area changed m²", ew["changed_area_m2"]), ("new carriageway m²", ew["areas_m2"]["carriageway"]),
        ("new sidewalks m²", ew["areas_m2"]["sidewalks"]), ("existing street surface m²", ew["areas_m2"]["existing_streets"]),
        ("retaining walls m (found / modelled)", f"{walls.get('length_m', 0):,.0f} / {walls.get('modelled_m', 0):,.0f}"),
        ("bridges / viaducts m", sum(b["length_m"] for b in ew.get("bridges", []))),
        ("ground left as it is under buildings m²", ew.get("kept_under_buildings_m2", 0)),
        ("street surface cut back at buildings m²", round(sum((summ.get("cut_at_buildings_m2") or {}).values()))),
        ("ground eased onto existing streets' edges m³ (not counted above)", ew.get("existing_edges_eased_m3", 0)))],
        ["earthworks", "value"], num=(1,)))
    parts.append(f"<p>Street surfaces are continuous: a point takes the height of the centre line nearest to it, "
                 f"interpolated along that line; where streets meet their surfaces blend over "
                 f"{prof['junction_blend_m']} m (streets side by side on clearly different levels keep a step), and "
                 f"every surface is smoothed over {prof['surface_smoothing_m']} m. Layering: each paved surface is a "
                 f"body lying on the terrain, which runs {prof['pavement_m']} m below a carriageway and "
                 f"{prof['kerb_m'] + prof['pavement_m']:.2f} m below a sidewalk (so it passes under the kerb without a "
                 f"step); around the paving the ground meets its edge flush: side slopes "
                 f"1:{cfg['roads']['earthworks']['fill_slope_h_per_v']} (fill) / "
                 f"1:{cfg['roads']['earthworks']['cut_slope_h_per_v']} (cut) at new streets, eased within "
                 f"{cfg['roads']['existing']['edge_blend_m']} m at existing ones.</p>")

    # ---- rules
    parts.append("<h2>New streets: the rules applied</h2>")
    if std:
        parts.append(f"<p>Class <b>{html.escape(std.get('class', ''))}</b> of ՀՀՇՆ 30-01-2023 Table 29 on "
                     f"<b>{std['terrain']}</b> terrain ({html.escape(std.get('terrain_source', ''))}): design speed "
                     f"<b>{std['design_speed_kmh']} km/h</b>, lane {std['lane_m']} m × {std['lanes']}, sidewalk at least "
                     f"{std['sidewalk_m']} m; max grade <b>{std['max_grade_permille']} ‰</b>"
                     + (f" ({std['exceptional_grade_permille']} ‰ allowed on stretches up to "
                        f"{std['exceptional_max_length_m']} m)" if std.get("exceptional_grade_permille") else "")
                     + f", min radius {std['min_radius_m']} m, vertical curves: crest ≥ {std['crest_radius_m']} m, sag ≥ "
                     f"{std['sag_radius_m']} m ({html.escape(std.get('source', ''))}). Serpentine bends (radius &lt; "
                     f"{prof['serpentine_radius_m']} m): grade ≤ {prof['serpentine_max_grade_permille']} ‰, radius ≥ "
                     f"{prof['serpentine_min_radius_m']} m. Drainage ≥ {prof['min_grade_permille']} ‰, cross fall "
                     f"{prof['carriageway_crossfall_permille']} ‰, kerb {prof['kerb_m']} m. Junction kerb radius ≥ "
                     f"{rck['kerb_radius_m']} m ({rck['kerb_radius_constrained_m']} m constrained), dead-end turning place "
                     f"{rck['dead_end_turning_m']} m, wheelchair routes ≤ {rck['accessible_grade_permille']} ‰. Centre "
                     f"lines: {html.escape(summ.get('centre_lines', ''))}.</p>")
    rows, short = [], 0
    for e in roads["proposed"]:
        c = e["checks"]
        if c["length_m"] < 20:
            short += 1
            continue
        gcls = "bad" if c["max_grade_permille"] > c["limit_permille"] + 0.5 and not any(e.get("exceptional") or []) else ""
        r_ok = c["min_radius_m"] is None or c["min_radius_m"] >= std.get("min_radius_m", 0)
        serp = c["min_radius_m"] is not None and c["min_radius_m"] < prof["serpentine_min_radius_m"]
        sw_w = e.get("sidewalk_widths_m") or [None, None]
        acc = e.get("accessibility") or {}
        rows.append([html.escape(e["name"]), f"{c['length_m']:,.0f}",
                     f"<span class='{gcls}'>{c['max_grade_permille']:.0f}</span>"
                     + (" (exc.)" if any(e.get("exceptional") or []) else ""),
                     f"<span class='{'bad' if serp else '' if r_ok else 'warnc'}'>{c['min_radius_m'] if c['min_radius_m'] else '—'}</span>",
                     f"{c['max_cut_m']:.2f}", f"{c['max_fill_m']:.2f}",
                     " / ".join("—" if w is None else f"{w:.1f}" for w in sw_w),
                     f"{acc.get('over_limit_m', 0):.0f}", ", ".join(f"{a:.0f}–{b:.0f}" for a, b in c["flat_stretches"]) or "—"])
    parts.append(_table(rows, ["street", "length m", "max grade ‰", "min bend radius m", "max cut m", "max fill m",
                               "sidewalks m (left / right)", "m steeper than 1:12", "flatter than drainage min (m)"],
                        num=(1, 2, 3, 4, 5, 7)))
    if short:
        parts.append(f"<p class='muted'>{short} short connecting pieces (under 20 m, at junctions) are not listed.</p>")
    if summ.get("exceptional_stretches"):
        parts.append("<p>The exceptional grade is used on: " + ", ".join(
            f"{html.escape(x['street'])} {x['from_m']:.0f}–{x['to_m']:.0f} m ({x['length_m']:.0f} m)"
            for x in summ["exceptional_stretches"] if x["length_m"] >= 5) + ".</p>")
    ck = summ.get("checks", {})
    if ck.get("kerb_radii"):
        parts.append("<h3>Junctions: kerb radius</h3>" + _table(
            [[f"({k[1][0]:.0f}, {k[1][1]:.0f})",
              html.escape(k[2]) if isinstance(k[2], str) else ("—" if k[2] is None else
                                                               f"<span class='{'bad' if k[2] < rck['kerb_radius_constrained_m'] else '' if k[2] >= rck['kerb_radius_m'] else 'warnc'}'>{k[2]:.1f}</span>")]
             for k in ck["kerb_radii"]], ["junction at (drawing m)", "tightest kerb corner m"], num=(1,)))
    if summ.get("tie_ins"):
        parts.append("<h3>Street ends joined to existing streets</h3>")
        parts.append(_table([[html.escape(t["existing"]), f"({t['xy'][0]:.0f}, {t['xy'][1]:.0f})", f"{t['z']:.2f}",
                              f"<span class='{'bad' if abs(t.get('mismatch_m', 0)) > 0.1 else 'good'}'>"
                              f"{t.get('mismatch_m', 0):+.2f}</span>",
                              f"{t['regraded_existing_m']:+.2f}" if t.get("regraded_existing_m") else "—"]
                             for t in summ["tie_ins"]],
                            ["existing street", "at (drawing m)", "its height m", "new street off by m",
                             "existing street regraded by m"], num=(2, 3, 4)))
        for d in summ.get("regraded_existing", []):
            parts.append(f"<p>{html.escape(d['street'])} is regraded at ({d['at'][0]:.0f}, {d['at'][1]:.0f}) by "
                         f"{d['change_m']:+.2f} m, tapering off over {d['over_m']:.0f} m "
                         f"({cfg['roads']['existing']['regrade_grade_permille']} ‰), so the new street joins it at "
                         "its height.</p>")
    for e in sorted(roads["proposed"], key=lambda e: -e["s"][-1]):
        if e["s"][-1] >= 50:
            parts.append(_img(fig_profile(e, cfg), e["name"]))

    # ---- buildings
    if n_ex or n_pr or bj["trees"]:
        parts.append("<h2>Buildings, trees, underground levels</h2>")
        parts.append(_img(fig_buildings(job, bj, docs, roads), "buildings"))
        sh = bchk.get("shadows") or {}
        if sh.get("storey_step_m"):
            parts.append(f"<p>New buildings: {n_pr} outlines. Their storeys are read from the shadows drawn in the plan "
                         f"({sh['shadows']} shadow outlines, cast along {sh['direction_deg']:.1f}°): each shadow is the "
                         f"footprint slid by a length that grows with the building's height, and the lengths are whole "
                         f"multiples of <b>{sh['storey_step_m']:.3f} m per storey</b> ({100 * sh['fit']:.0f}% of them; "
                         f"{html.escape(sh.get('step_source') or '')}). Height = {cfg['buildings']['ground_storey_m']} m "
                         f"ground storey + {cfg['buildings']['storey_m']} m per further storey."
                         + ("" if bchk.get("programme") else
                            f" The drawing alone cannot tell this step from half of it ({sh['storey_step_m'] / 2:.3f} m, "
                            "twice the storeys): the project's floor area (<code>--doc</code>) or "
                            "<code>buildings.shadow_per_storey_m</code> decides that.") + "</p>")
        from collections import Counter
        src = Counter(b["source"] for b in bj["proposed"])
        st = Counter(b["storeys"] for b in bj["proposed"] if b["source"] != "no shadow in the drawing (assumed)")
        parts.append(_table([[html.escape(k), v] for k, v in src.items()] +
                            [[f"{k} storeys", v] for k, v in sorted(st.items())], ["new buildings", "outlines"], num=(1,)))
        pg = bchk.get("programme")
        if pg:
            cls_ = "good" if pg["ratio"] and 0.85 <= pg["ratio"] <= 1.15 else "bad"
            parts.append(f"<p>Check against the documents: floor area of the new buildings "
                         f"({html.escape(pg['area'])}, footprint × storeys, {pg['buildings_compared']} outlines) = "
                         f"<b>{pg['model_gfa_m2']:,} m²</b>; {html.escape(pg['source'])} gives "
                         f"{pg['documents_above_ground_m2']:,.0f} m² above ground → <span class='{cls_}'>"
                         f"{100 * (pg['ratio'] - 1):+.0f}%</span> (outer outlines include walls and balconies).</p>")
        exs = Counter(b["source"] if "usual" not in b["source"] else "usual storeys of its OSM building type (assumed)"
                      for b in bj["existing"])
        parts.append(_table([[html.escape(k), v] for k, v in exs.most_common()], ["existing buildings: height from",
                                                                                   "buildings"], num=(1,)))
        if bj.get("demolished"):
            parts.append("<h3>Existing buildings to be demolished</h3>" + _table(
                [[f"({d['at'][0]:.0f}, {d['at'][1]:.0f})", f"{d['area_m2']:,.0f}", f"{d['covered_m2']:,.0f}",
                  html.escape(d["by"]), d["storeys"]] for d in bj["demolished"]],
                ["at (drawing m)", "footprint m²", "covered m²", "mostly by", "storeys"], num=(1, 2, 4)))
        if bj.get("underground"):
            gl = bchk.get("underground_ground_level", {})
            parts.append(f"<p>Underground levels from the documents, stacked {cfg['buildings']['underground']['storey_m']} m "
                         f"apart under the ground floor at {gl.get('z', float('nan')):.1f} m ({html.escape(gl.get('source', ''))}).</p>")
            parts.append(_table([[lv["level"], f"{lv['floor_z']:.1f}", f"{lv['area_m2']:,.0f}",
                                  f"{lv['stated_m2']:,.0f}" if lv.get("stated_m2") else "—", html.escape(lv["source"])]
                                 for lv in bj["underground"]],
                                ["level", "floor altitude m", "area m² (measured)", "stated m²", "from"], num=(1, 2, 3)))

    # ---- documents
    if docs.get("documents"):
        parts.append("<h2>Project documents (read as data)</h2>")
        for d in docs["documents"]:
            parts.append(f"<p><b>{html.escape(d['file'])}</b>, {d['pages']} pages; drawing scale 1:{d['scale']:,.0f} "
                         f"({html.escape(d.get('scale_source') or 'unknown')}).</p>" if d.get("scale") else
                         f"<p><b>{html.escape(d['file'])}</b>, {d['pages']} pages.</p>")
            if d["plans"]:
                parts.append(_table([[p["page"], html.escape(p["sheet"] or ""), " ".join(p["levels"]) or "outline",
                                      f"{p['stated_m2']:,.0f}" if p.get("stated_m2") else "—",
                                      f"{p['measured_m2']:,.0f}",
                                      f"<span class='{'good' if p['ratio'] and abs(p['ratio'] - 1) <= 0.03 else ''}'>"
                                      f"{100 * (p['ratio'] - 1):+.1f}%</span>" if p.get("ratio") else "—",
                                      f"{p['placement'].get('within_1m_pct', '—')}%"] for p in d["plans"]],
                                    ["page", "sheet", "levels", "stated m² (all levels)", "measured m² per level",
                                     "measured vs stated", "its lines within 1 m of the drawing"], num=(0, 3, 4, 5, 6)))
            for t in d["tables"]:
                if len(t["rows"]) >= 2:
                    parts.append(_table([[html.escape(r["label"]), f"{r['value']:,.0f}"] for r in t["rows"]],
                                        [f"table on page {t['page']}: {t['header'][:60]}", "value"], num=(1,)))
        prog = docs.get("program")
        if prog:
            rules = cfg["documents"]["parking_rules"]
            dem = norms.parking_demand(prog["functions_m2"], rules)
            lo = sum(r[3] for r in dem if r[3] is not None)
            hi = sum(r[4] for r in dem if r[4] is not None)
            parts.append("<h3>Parking demand (ՀՀՇՆ 30-01-2023 Table 56)</h3>" + _table(
                [[html.escape(r[0]), f"{r[1]:,.0f}", html.escape(r[2]),
                  "—" if r[3] is None else f"{r[3]:,.0f}–{r[4]:,.0f}"] for r in dem],
                ["function", "m²", "rule", "spaces"], num=(1, 3)))
            if prog.get("parking_spaces"):
                ok_ = prog["parking_spaces"] >= hi
                parts.append(f"<p>Needed about <b>{lo:,.0f}–{hi:,.0f}</b> spaces (hotel by its class, not counted); the "
                             f"documents provide <span class='{'good' if ok_ else 'bad'}'><b>{prog['parking_spaces']:,}</b></span>"
                             f" ({prog['below_ground_m2']:,.0f} m² of parking, "
                             f"{prog['below_ground_m2'] / prog['parking_spaces']:.0f} m² per space).</p>")
            plans = [shape(p["polygon"]) for d in docs["documents"] for p in d["plans"]]
            if plans:
                from shapely.ops import unary_union
                plot = unary_union(plans).area
                far = prog["above_ground_m2"] / plot
                cov = sum(b["area_m2"] for b in bj["proposed"] if b["source"] != "no shadow in the drawing (assumed)") / plot
                parts.append(f"<h3>Density (ՀՀՇՆ 30-01-2023 Table 8)</h3><p>With the outline of all underground levels "
                             f"({plot:,.0f} m²) standing in for the plot: floor area ratio Pկ1 = "
                             f"{prog['above_ground_m2']:,.0f} / {plot:,.0f} = <b>{far:.2f}</b>, coverage Pկ2 ≈ "
                             f"<b>{100 * min(cov, 1):.0f}%</b>. Table 8 limits: multi-functional public zone 3.0 / 100 %, "
                             f"specialised public 2.4 / 80 %, mixed (rebuilt) 1.6 / 60 %, high-rise housing (rebuilt) "
                             f"1.6 / 60 %. Measure again with the real plot (red lines) once it is known.</p>")

    # ---- norms and laws
    parts.append("<h2>Norms and laws to keep in mind</h2>")
    parts.append(_table([[html.escape(a), html.escape(b), html.escape(c)] for a, b, c in norms.REGISTER],
                        ["norm / law", "what it governs here", "in this model"]))

    parts.append("<h2>Placement</h2>")
    parts.append(f"<p>The drawing was matched to OpenStreetMap buildings: rotation "
                 f"{geo['transform']['rotation_deg']:+.3f}°, drawing 0,0 = UTM zone {geo['epsg'] % 100} "
                 f"({geo['transform']['tx']:,.2f}, {geo['transform']['ty']:,.2f}); peak ratio "
                 f"{geo.get('peak_ratio', float('nan')):.2f}; {geo.get('icp', {}).get('within_1m_pct', '—')}% of the "
                 f"outlines within 1 m of OSM (median {geo.get('icp', {}).get('median_m', '—')} m). Site centre "
                 f"{geo['site_centre_lonlat'][1]:.5f} N, {geo['site_centre_lonlat'][0]:.5f} E. Where to look came from: "
                 f"{html.escape(geo.get('lonlat_source', 'site.lonlat'))}.</p>")
    parts.append(_img(fig_georef(job, geo, site), "drawing on OpenStreetMap"))
    if "cloud_to_drawing" in ter:
        t = ter["cloud_to_drawing"]
        parts.append(f"<p>The point cloud terrain was placed on the drawing by its building gaps: rotation "
                     f"{t['rotation_deg']:+.3f}° (map grid convergence here {geo['grid_convergence_deg']:+.3f}°), "
                     f"cloud 0,0 = drawing ({t['tx']:.2f}, {t['ty']:.2f}) m, peak ratio "
                     f"{ter['placement'].get('peak_ratio', float('nan')):.2f}. Altitude = cloud height "
                     f"{ter['z_to_altitude']:+.2f} m ({html.escape(alt.get('method', ''))}).</p>")

    parts.append("<h2>Existing streets</h2>")
    parts.append(_table([[html.escape(e["name"] or "—"), e["cls"], f"{e['s'][-1]:,.0f}",
                          f"{2 * float(np.median(e['half_w'])):.1f}", e["width_source"]]
                         for e in sorted(roads["existing"], key=lambda e: -e["s"][-1])[:60]],
                        ["name", "OSM class", "length m", "width m", "width from"], num=(2, 3)))

    parts.append("<h2>Drawing</h2>")
    conv = rd["conversion"]
    parts.append(f"<p>{rd['primitives_total']:,} primitives read ({', '.join(f'{k} {v:,}' for k, v in rd['primitives'].items())}); "
                 f"{'AutoCAD Architecture objects exported to plain AutoCAD; ' if conv.get('aec_export') else ''}"
                 f"site plan: {inv['site']['primitives']:,} primitives on {inv['layers_used']} layers, the other "
                 f"{len(inv['regions']) - 1} drawings in model space were left out.</p>")
    if rd.get("decoded_layers"):
        parts.append("<p>Layer names in old Armenian font encoding, shown in Armenian: "
                     + ", ".join(f"<code>{html.escape(n)}</code>" for n in rd["decoded_layers"]) + "</p>")
    if acj and acj.get("saved"):
        parts.append("<h2>Archicad file</h2>" + _table(
            [[k.replace("_", " "), f"{v:,}"] for k, v in acj["created_counts"].items()], ["made", "elements"], num=(1,)))
        parts.append(f"<p>Project zero = {acj['z_reference']:.1f} m above sea level; the terrain mesh has "
                     f"{acj['mesh_points']:,} points ({acj.get('mesh_points_under_paving', 0):,} of them under the "
                     f"paving, on the street bodies' grid) and {acj.get('paving_edge_lines', 0)} lines along the "
                     "paving's edges. Streets, sidewalks, "
                     "walls and buildings are Morph solids with their own surfaces (" + ", ".join(
                         html.escape(v["name"]) for k, v in cfg["archicad"]["surfaces"].items() if not k.startswith("_"))
                     + f"); trees are library objects ({acj.get('trees_on_streets_left_out', 0)} standing on a "
                     "carriageway left out).</p>")
    parts.append("<p class='muted'>Street and building data © OpenStreetMap contributors (ODbL).</p></main></body></html>")
    Path(job.output_report).parent.mkdir(parents=True, exist_ok=True)
    Path(job.output_report).write_text("".join(parts), encoding="utf-8")
    ok(f"report: {job.output_report}")
