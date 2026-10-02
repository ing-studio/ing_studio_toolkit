"""What a project PDF says, read as data (PyMuPDF; no image recognition by AI):

  words        every word with its box (PDF points, y down), so lines and tables are rebuilt from positions
  statements   '<levels> <number> SQM' (e.g. 'B1 B2 21900 SQM'), the drawing scale '1 : 1200', sheet ids ('A102')
  tables       rows 'LABEL ... NUMBER' stacked under a header (AREA / SQM / QTY), with the colour of the legend
               swatch in front of each row
  plans        the page rendered as an image; the area marked with a coloured outline (e.g. pure red) found by colour,
               filled, turned into a polygon on the centre of the outline, and measured with the drawing scale
  linework     edge pixels of the drawing on the page, to match the page to the DWG
"""
import re

import numpy as np
from scipy import ndimage

SQM = r"(?:SQM|SQ\.?\s*M|M2|M²|m2|m²|ՔՄ|քմ|кв\.?\s*м)"
NUMBER = r"\d{1,3}(?:[ ,.]\d{3})+|\d+"


def open_pdf(path):
    import pymupdf
    return pymupdf.open(path)


def words(page):
    """[(x0, y0, x1, y1, text)] of a page, in reading order."""
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words", sort=True)]


def lines_of(ws, tol=3.0):
    """Words grouped into text lines by their vertical centre: [(y, [words left to right])]."""
    out = []
    for w in sorted(ws, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if out and abs(out[-1][0] - yc) <= tol:
            out[-1][1].append(w)
        else:
            out.append([yc, [w]])
    return [(y, sorted(ws_, key=lambda w: w[0])) for y, ws_ in out]


def to_number(text):
    t = text.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}([,.]\d{3})+", t):
        t = re.sub(r"[,.]", "", t)
    try:
        return float(t)
    except ValueError:
        return None


def page_text(ws):
    return " ".join(w[4] for w in ws)


def scale_of(text):
    """Drawing scale N of '1 : N' (N between 50 and 20000), else None."""
    for m in re.finditer(r"(?<![\d.])1\s*[:/]\s*(\d{2,5})(?![\d.])", text):
        n = int(m.group(1))
        if 50 <= n <= 20000:
            return n
    return None


def sheet_of(ws, page_w):
    """Sheet number such as A102 (the top-right-most match)."""
    cands = [w for w in ws if re.fullmatch(r"[A-Z]{1,2}-?\d{2,4}", w[4])]
    if not cands:
        return None
    return max(cands, key=lambda w: w[0] - w[1])[4]


def area_statements(text, level_prefixes=("B",)):
    """'B1 B2 21900 SQM' -> [(['B1', 'B2'], 21900.0)]; also 'TOTAL 127900 SQM' -> [([], 127900.0)]."""
    pre = "".join(level_prefixes)
    out = []
    pat = rf"((?:\b[{pre}]-?\d{{1,2}}\b\s*)*)\s*({NUMBER})\s*{SQM}"
    for m in re.finditer(pat, text):
        levels = re.findall(rf"[{pre}]-?\d{{1,2}}", m.group(1))
        v = to_number(m.group(2))
        if v and v >= 10:
            out.append((levels, v))
    return out


def count_statements(text):
    """'QTY 2560' / 'PARKING LOT 2560' style counts: [(label, n)]."""
    out = []
    for m in re.finditer(r"((?:[A-Z]+\s+){0,3})QTY\s*(\d{1,6})", text):
        out.append(((m.group(1).strip() or "QTY"), int(m.group(2))))
    return out


def tables(page, ws=None, min_value=1.0):
    """Tables of 'LABEL NUMBER' rows: [{"header": str, "rows": [{"label", "value", "rgb"}], "bbox"}].

    A row is a text line whose last word is a number and whose other words are letters; rows whose numbers stand in
    one column (right edges within 25 pt) and follow each other closely form a table; the line above the first row
    (if it holds no number) is its header. The fill colour of a small filled rectangle left of a row's label is the
    row's legend colour."""
    ws = ws if ws is not None else words(page)
    lines = lines_of(ws)
    rows = []
    for y, lw in lines:
        v = to_number(lw[-1][4])
        label = [w for w in lw[:-1] if re.search(r"[^\W\d_]", w[4])]
        if v is None or v < min_value or not label or len(label) != len(lw) - 1:
            continue
        rows.append({"y": y, "label": " ".join(w[4] for w in label), "value": v, "x_num": lw[-1][2],
                     "x_label": label[0][0], "h": lw[-1][3] - lw[-1][1]})
    swatches = []
    try:
        for d in page.get_drawings():
            r, fill = d.get("rect"), d.get("fill")
            if fill is not None and r is not None and 4 < r.width < 120 and 4 < r.height < 60:
                swatches.append((r.x0, r.y0, r.x1, r.y1, tuple(int(round(c * 255)) for c in fill[:3])))
    except Exception:
        pass
    out = []
    for r in rows:
        sw = [s for s in swatches if s[1] - 2 <= r["y"] <= s[3] + 2 and s[2] <= r["x_label"] + 2]
        r["rgb"] = list(max(sw, key=lambda s: s[2])[4]) if sw else None
        if out and abs(out[-1]["x_num"] - r["x_num"]) <= 25 and r["y"] - out[-1]["rows"][-1]["y"] <= 4.5 * r["h"] + 10:
            out[-1]["rows"].append(r)
            continue
        out.append({"x_num": r["x_num"], "rows": [r]})
    for t in out:
        y0 = t["rows"][0]["y"]
        above = [(y, lw) for y, lw in lines if y0 - 60 < y < y0 - 1 and to_number(lw[-1][4]) is None]
        t["header"] = " ".join(w[4] for w in above[-1][1]) if above else ""
        if len(above) >= 2:
            t["header"] = " ".join(w[4] for w in above[-2][1]) + " " + t["header"]
        t["rows"] = [{"label": r["label"], "value": r["value"], "rgb": r["rgb"]} for r in t["rows"]]
        del t["x_num"]
    return out


# --------------------------------------------------------------------------- the page as an image
def render(page, dpi):
    """RGB image (H, W, 3) uint8 of the page at dpi."""
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3]


def colour_mask(img, rgb, tol):
    d = np.abs(img.astype(np.int16) - np.array(rgb, np.int16)[None, None, :]).max(axis=2)
    return d <= tol


def mask_polygons(mask, min_px=2000):
    """Filled regions of a boolean image as shapely polygons in pixel coordinates (x right, y down)."""
    from osgeo import gdal, ogr
    from shapely import wkb
    lab, n = ndimage.label(mask)
    if not n:
        return []
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    keep = np.isin(lab, np.nonzero(sizes >= min_px)[0] + 1)
    if not keep.any():
        return []
    H, W = keep.shape
    ds = gdal.GetDriverByName("MEM").Create("", W, H, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((0, 1, 0, 0, 0, 1))
    band = ds.GetRasterBand(1)
    band.WriteArray(keep.astype(np.uint8))
    vds = ogr.GetDriverByName("MEM").CreateDataSource("")
    lyr = vds.CreateLayer("p")
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, band, lyr, 0)
    out = []
    for f in lyr:
        g = wkb.loads(bytes(f.GetGeometryRef().ExportToWkb()))
        if g.is_valid and g.area >= min_px:
            out.append(g)
    return out


def marked_areas(img, rgb, tol, min_px=2000):
    """Areas outlined in colour `rgb`: [(polygon on the centre of the outline (px), outline width px, filled px)].

    The outline pixels are found by colour, the area they enclose is filled; the polygon of the filled area is then
    moved in by half the outline width, so it runs on the centre line of the drawn outline (what a measured area
    means on a drawing)."""
    ink = colour_mask(img, rgb, tol)
    filled = ndimage.binary_fill_holes(ink)
    out = []
    for poly in mask_polygons(filled, min_px):
        inside = poly.buffer(0.5)
        from shapely import contains_xy
        yy, xx = np.nonzero(ink)
        sel = contains_xy(inside, xx + 0.5, yy + 0.5)
        width = float(sel.sum()) / max(poly.exterior.length, 1.0)
        centre = poly.buffer(-width / 2.0, join_style=2).simplify(1.0)
        if not centre.is_empty and centre.area > 0:
            out.append((centre, width, float(poly.area)))
    return out


def text_mask(page, shape, dpi, pad=3):
    """Pixels covered by the page's words (titles, notes, stamps): left out of the linework."""
    m = np.zeros(shape, bool)
    for w in words(page):
        x0, y0, x1, y1 = (int(v * dpi / 72.0) for v in w[:4])
        m[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
    return m


def linework_points(img, step=2, exclude=None, contrast=25.0):
    """The drawn lines of the page (x right, y down), every `step` pixels: pixels clearly darker than their
    surroundings - thin lines on white and on light fills, and the borders of fills; `exclude` masks pixels out."""
    lum = img.astype(np.float32).mean(axis=2)
    line = (ndimage.maximum_filter(lum, 5) - lum) > contrast
    if exclude is not None:
        line &= ~exclude
    yy, xx = np.nonzero(line[::step, ::step])
    return np.column_stack([xx * step + 0.5, yy * step + 0.5]).astype(np.float64)
