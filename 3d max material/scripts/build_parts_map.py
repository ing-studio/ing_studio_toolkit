"""Collapse the 332 FBX materials into a small set of distinct Corona "part" materials.

Writes:
  part_materials.tsv  name \t template \t diffuse(r,g,b or '') \t gloss('' = keep) \t ior('' = keep)
  part_map.tsv        source material \t part material name
  part_map.csv        same, human readable with reasons (copied next to the output)
"""
import colorsys
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

W = Path(__file__).parent
fbx = json.load(open(W / "fbx_materials.json"))
byname = {m["name"]: m for m in fbx}

# Part material definitions: name -> (reference template, diffuse or None = keep reference, gloss, ior)
PARTS = {
    # sandstone family: three clearly different tones/finishes
    "TG_SAND_FRAME":          ("Material #899",        (140, 127, 113), 0.68, 1.8),   # lighter, glossier painted metal
    "TG_SAND_PLASTIC":        ("Material #2147464532", None, None, None),             # reference sandstone plastic
    "TG_SAND_PLASTIC_DARK":   ("Material #908",        None, None, None),             # reference dark sandstone
    "TG_UPHOLSTERY":          ("Material #4",          (124, 115, 108), None, None),
    "TG_UPHOLSTERY_DARK":     ("Material #4",          (38, 38, 37), None, None),
    "TG_BELT":                ("Material #978",        (46, 46, 46), None, None),
    "TG_LOGO_WHITE":          ("Material #2",          (245, 245, 245), None, None),
    "TG_LOGO_GOLD":           ("Material #2",          (190, 174, 58), None, None),
    "TG_LOGO_DARK":           ("Material #2",          (25, 25, 25), None, None),
    "TG_BLACK_PLASTIC":       ("Material #902",        None, None, None),
    "TG_BLACK_GLOSS":         ("Material #901",        None, None, None),
    "TG_CHROME":              ("Material #29",         None, None, None),
    "TG_METAL_SATIN":         ("Material #974",        (185, 185, 185), None, None),
    "TG_RUBBER":              ("Material #10911",      (20, 20, 20), None, None),
    "TG_PLASTIC_DARK_GREY":   ("Material #975",        (42, 42, 42), None, None),
    "TG_PLASTIC_MID_GREY":    ("Material #975",        (90, 90, 90), None, None),
    "TG_PLASTIC_LIGHT_GREY":  ("Material #975",        (196, 196, 196), None, None),
    "TG_WHITE":               ("Material #976",        (245, 245, 245), None, None),
    "TG_YELLOW":              ("Material #903",        (230, 215, 80), None, None),
    "TG_RED":                 ("Material #977",        (200, 10, 10), None, None),
    "TG_GREEN":               ("Material #975",        (30, 170, 60), None, None),
    "TG_BLUE":                ("Material #975",        (20, 90, 200), None, None),
}


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


rows = []
for m in sorted(fbx, key=lambda x: -x["meshes"]):
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

used = Counter(r["part"] for r in rows)
mesh = Counter()
for r in rows:
    mesh[r["part"]] += r["meshes"]

with open(W / "part_materials.tsv", "w", encoding="utf8") as f:
    for p, (t, d, g, i) in PARTS.items():
        if used[p]:
            f.write("\t".join([p, t, "" if d is None else "%d,%d,%d" % d, "" if g is None else str(g), "" if i is None else str(i)]) + "\n")
with open(W / "part_map.tsv", "w", encoding="utf8") as f:
    for r in rows:
        f.write(r["source"] + "\t" + r["part"] + "\n")
with open(W / "part_map.csv", "w", newline="", encoding="utf8") as f:
    w = csv.DictWriter(f, fieldnames=["source", "meshes", "skp_rgb", "part", "rule"])
    w.writeheader()
    w.writerows(rows)

for p in PARTS:
    if used[p]:
        print(f"{p:24} {used[p]:4} source materials {mesh[p]:7} meshes")
print("part materials:", sum(1 for p in PARTS if used[p]))
