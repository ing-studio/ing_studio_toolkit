"""The report of a run, next to the project in output\\: <project>_windows.html (types with a 3D preview, the sheet,
every window's old and new ID) and <project>_windows.csv (one row per window, for Excel)."""
import csv
import html
from pathlib import Path

from .sheet import HAND_NAMES, to_svg
from .util import log, mm

CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#d2d2d7;--head:#f5f5f7;--accent:#0a6ebd}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1e;--fg:#f2f2f7;--muted:#a1a1a6;--line:#3a3a3c;--head:#2c2c2e;
--accent:#64aaff}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,"Segoe UI",sans-serif;margin:0;padding:24px 16px}
main{max-width:1200px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}
.muted{color:var(--muted)}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);
padding:6px 8px;text-align:left;vertical-align:middle}th{background:var(--head);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}td img{width:72px;height:72px;object-fit:contain;
background:#fff;border-radius:4px}.id{font-weight:700;color:var(--accent);white-space:nowrap}
.wrap{overflow-x:auto}.warn{background:#fff4d6;color:#5c4400;padding:8px 12px;border-radius:6px;margin:4px 0}
svg.sheet{width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px}
svg.sheet polyline{fill:none;stroke:#000;stroke-width:.18}svg.sheet .thick{stroke-width:.45}
svg.sheet .dim,svg.sheet .dimw{stroke:#444;stroke-width:.13}svg.sheet .tick{stroke:#222;stroke-width:.35}svg.sheet text{fill:#000;font-family:system-ui,sans-serif}
svg.sheet .dimt{font-size:2.5px;text-anchor:middle;fill:#333}
"""


def previews(ac, types):
    """{label: base64 PNG} - Archicad's 3D preview of one window of each type."""
    out = {}
    for t in types:
        try:
            r = ac.tapir("GetElementPreviewImage", {"elementId": {"guid": t.sample.guid}, "imageType": "3D",
                                                    "width": 160, "height": 160})
            img = r.get("previewImage") or next((v for v in r.values() if isinstance(v, str) and len(v) > 100), None)
            if img:
                out[t.label] = img
        except Exception:
            pass  # a report without that picture
    return out


def write(folder, project, types, stories, changes, drawing, cfg, images, warnings, dry_run):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(project).stem or "project"
    floors = sorted({f for t in types for f in t.per_floor()})
    e = html.escape

    rows = []
    for t in types:
        pf = t.per_floor()
        img = f'<img alt="" src="data:image/png;base64,{images[t.label]}">' if t.label in images else ""
        rows.append(f'<tr><td>{img}</td><td class="id">{e(t.label)}</td><td class="n">{mm(t.width)}</td>'
                    f'<td class="n">{mm(t.height)}</td><td class="n">{e(", ".join(map(str, t.sills())))}</td>'
                    + "".join(f'<td class="n">{pf.get(f, "")}</td>' for f in floors)
                    + f'<td class="n"><b>{len(t.windows)}</b></td><td>{e(HAND_NAMES.get(t.hand, ""))}</td>'
                    f'<td>{e(t.part)}</td></tr>')
    ch = "".join(f'<tr><td>{e(stories.get(w.floor, str(w.floor)))}</td><td>{e(old or "—")}</td>'
                 f'<td class="id">{e(new)}</td><td class="muted">{e(w.guid)}</td></tr>' for w, old, new in changes)
    total = sum(len(t.windows) for t in types)
    verb = "would get" if dry_run else "got"
    page = f"""<!doctype html><html lang="hy"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Window types</title><style>{CSS}</style>
</head><body><main>
<h1>Պատուհանների մասնագիր — {e(stem)}</h1>
<p class="muted">{total} windows, {len(types)} types. {len(changes)} window(s) {verb} a new ID
{"(dry run: nothing was changed in Archicad)" if dry_run else ""}.</p>
{"".join(f'<div class="warn">{e(w)}</div>' for w in warnings)}
<h2>Types</h2><div class="wrap"><table><tr><th></th><th>ID</th><th class="n">Width</th><th class="n">Height</th>
<th class="n">Sill</th>{"".join(f'<th class="n">{e(stories.get(f, str(f)))}</th>' for f in floors)}
<th class="n">Total</th><th>Hand</th><th>Library part</th>
</tr>{"".join(rows)}</table></div>
<h2>Worksheet «{e(cfg.get("worksheet", {}).get("name", ""))}»</h2>{to_svg(drawing, cfg)}
<h2>Changed IDs</h2><div class="wrap"><table><tr><th>Story</th><th>Old ID</th><th>New ID</th><th>GUID</th></tr>
{ch or '<tr><td colspan="4" class="muted">none</td></tr>'}</table></div>
</main></body></html>"""
    page_path = folder / f"{stem}_windows.html"
    page_path.write_text(page, encoding="utf-8")

    csv_path = folder / f"{stem}_windows.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel reads the Armenian letters
        wr = csv.writer(f)
        wr.writerow(["ID", "story", "width_mm", "height_mm", "sill_mm", "hand", "library_part", "old_id", "guid"])
        old_ids = {w.guid: old for w, old, _ in changes}
        for t in types:
            for w in t.windows:
                wr.writerow([t.label, stories.get(w.floor, w.floor), mm(w.width), mm(w.height), mm(w.sill), w.hand,
                             w.part, old_ids.get(w.guid, w.id), w.guid])
    log(f"report: {page_path}")
    return page_path
