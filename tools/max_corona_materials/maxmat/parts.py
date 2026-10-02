"""The part map: every material of the model -> one of a small set of distinct Corona "part" materials.

The parts and their templates are settings (parts in config/default.json); which material becomes which part is
decided here, by the rules the Technogym set was converted with:
  1. materials named TG... (the maker's own): by the words of the name (belt, upholstery, logo, frame, plastic ...);
     a diamondblack / anthracitesilver finish is read as sandstone (the finish of the set);
  2. other materials: by keywords (chrome, rubber, leather ...), then by colour: a saturated colour is an accent
     (red, yellow, green, blue), a warm mid tone is sandstone, the rest a grey by its luminance.

Writes into the work folder (read by scripts/rebuild_parts.ms):
  part_materials.tsv  name \t template \t diffuse (r,g,b or '') \t gloss ('' = keep) \t ior ('' = keep)
  part_map.tsv        model material \t part
and into the output folder, for people:
  <model>_part_map.csv        model material, meshes, colour, part, rule
  <model>_part_materials.csv  part, template, diffuse, glossiness, IOR
"""
import colorsys
import csv
import re
from collections import Counter


def hsv(c):
    return colorsys.rgb_to_hsv(*(x / 255 for x in c))


def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def accent(c):
    """Return an accent part for saturated colours, else None."""
    h, s, v = hsv(c)
    if s < 0.35 or v < 0.25:
        return None
    h *= 360
    if h < 20 or h >= 340:
        return "TG_RED"
    if 35 <= h < 75:
        return "TG_YELLOW"
    if 75 <= h < 170:
        return "TG_GREEN"
    if 170 <= h < 260:
        return "TG_BLUE"
    return None


def grey_part(c):
    L = lum(c)
    if L < 18:
        return "TG_BLACK_PLASTIC"
    if L < 65:
        return "TG_PLASTIC_DARK_GREY"
    if L < 150:
        return "TG_PLASTIC_MID_GREY"
    if L < 225:
        return "TG_PLASTIC_LIGHT_GREY"
    return "TG_WHITE"


def logo_part(c):
    if accent(c) == "TG_YELLOW" or (hsv(c)[1] > 0.3 and lum(c) > 80):
        return "TG_LOGO_GOLD"
    return "TG_LOGO_DARK" if lum(c) < 70 else "TG_LOGO_WHITE"


def classify(name, c):
    """(part, the rule that chose it) of a material by its name and colour."""
    n = name.lower()
    tg = name.startswith("TG")
    if tg:
        if "red_button" in n:
            return "TG_RED", "TG red button"
        if "yellow" in n and "logo" not in n:
            return "TG_YELLOW", "TG yellow handles"
        if "fixed_black" in n:
            return "TG_BLACK_PLASTIC", "TG fixed black"
        if "satin_metal" in n or "disks_handle" in n:
            return "TG_METAL_SATIN", "TG satin metal"
        if "logo" in n or "sticker" in n:
            return logo_part(c), "TG logo/sticker"
        if "upholstery" in n:
            return "TG_UPHOLSTERY", "TG upholstery"
        if "belt" in n:
            return "TG_BELT", "TG belt"
        if "steps" in n:
            return "TG_SAND_PLASTIC_DARK", "TG steps"
        if re.search(r"metal_\d", n) and hsv(c)[1] < 0.04:
            return "TG_METAL_SATIN", "TG metal (neutral grey)"
        if re.search(r"frame|inlay|camme|metal_\d|accent", n):
            return ("TG_SAND_PLASTIC_DARK" if lum(c) < 80 else "TG_SAND_FRAME"), "TG frame"
        if "plastic" in n:
            return ("TG_SAND_PLASTIC_DARK" if lum(c) < 80 else "TG_SAND_PLASTIC"), "TG plastic"
    # generic (non-TG) materials: name keywords first, then colour
    if re.search(r"chrome|crop|stainless|steel|eleclassic|met11|melal|spring", n):
        return "TG_CHROME", "name: chrome/steel"
    if re.search(r"black_metal|matal_black|metal_sel_black", n):
        return "TG_BLACK_GLOSS", "name: black metal"
    if re.search(r"metal", n):
        return ("TG_CHROME" if lum(c) < 60 else "TG_METAL_SATIN"), "name: metal"
    if re.search(r"rubb|gomma|rubblk|elastic", n):
        return "TG_RUBBER", "name: rubber"
    if re.search(r"logo|sticker|numeri|qr_|allert", n):
        return logo_part(c), "name: logo/sticker"
    if re.search(r"leather|uphol|seat|pad\b", n):
        return ("TG_UPHOLSTERY_DARK" if lum(c) < 60 else "TG_UPHOLSTERY"), "name: upholstery"
    a = accent(c)
    if a:
        return a, "colour: accent"
    h, s, v = hsv(c)
    if s >= 0.08 and c[0] >= c[1] >= c[2] and 70 <= lum(c) <= 200:
        return "TG_SAND_PLASTIC", "colour: sandstone-like"
    return grey_part(c), "colour: neutral grey"


def part_map(materials):
    """[{source, meshes, skp_rgb, part, rule}] of the model's materials ([{name, meshes, rgb}]), most used first."""
    byname = {m["name"]: m for m in materials}
    rows = []
    for m in sorted(materials, key=lambda x: -x["meshes"]):
        name = m["name"]
        c = m.get("rgb") or [128, 128, 128]
        prefix = ""
        target = name
        if name.startswith("TG"):
            sand = re.sub(r"diamondblack|anthracitesilver", "sandstone", name)
            if sand != name:
                prefix = "finish->sandstone; "
                if sand in byname:
                    c = byname[sand].get("rgb") or c
            target = sand
        part, why = classify(target, c)
        rows.append(dict(source=name, meshes=m["meshes"], skp_rgb="%d,%d,%d" % tuple(c), part=part, rule=prefix + why))
    return rows


def check_parts(parts, rows, fallback):
    """Every part the rules chose (and the fallback) must be defined in the settings."""
    missing = sorted({r["part"] for r in rows} - set(parts) | ({fallback} - set(parts)))
    if missing:
        raise ValueError(f"parts used but not defined in the settings (parts): {', '.join(missing)}")


def write(parts, rows, work_dir, output_dir, stem):
    """The two .tsv files for the rebuild, the two .csv files for people; returns {part: (materials, meshes)}."""
    used = Counter(r["part"] for r in rows)
    meshes = Counter()
    for r in rows:
        meshes[r["part"]] += r["meshes"]
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    def text(v):
        return "" if v is None else ("%d,%d,%d" % tuple(v) if isinstance(v, list) else str(v))

    defined = [(p, d) for p, d in parts.items() if not p.startswith("_") and used[p]]
    with open(work_dir / "part_materials.tsv", "w", encoding="utf-8") as f:
        for p, (template, diffuse, gloss, ior) in defined:
            f.write("\t".join([p, template, text(diffuse), text(gloss), text(ior)]) + "\n")
    with open(work_dir / "part_map.tsv", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r["source"] + "\t" + r["part"] + "\n")
    with open(output_dir / f"{stem}_part_map.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "meshes", "skp_rgb", "part", "rule"])
        w.writeheader()
        w.writerows(rows)
    with open(output_dir / f"{stem}_part_materials.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["material", "based_on_reference", "diffuse_rgb", "glossiness", "ior"])
        for p, (template, diffuse, gloss, ior) in defined:
            w.writerow([p, template] + [text(v) or "reference" for v in (diffuse, gloss, ior)])
    return {p: (used[p], meshes[p]) for p, _ in defined}
