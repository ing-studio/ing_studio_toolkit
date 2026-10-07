"""Sand Stone finish: scenes of Technogym equipment re-finished in the Sand Stone Collection's materials.

What it decides (the 3ds Max work is scripts/refinish_sandstone.ms):
  1. which equipment is black (a diamondblack / anthracitesilver finish, or mostly dark) and whether the same product
     is in the scenes in Sand Stone too (a "twin": the same size within 1.5 cm). A black twin is removed, and so is
     black equipment hidden in its scene (put away as not needed); a black product with no twin, shown in its scene,
     is kept, re-finished in Sand Stone and put on its own layer (RECOLOURED_LAYER);
  2. the colour swatches some models carry (small cubes in pure red, green, blue, yellow beside a machine) and the
     free-space zones drawn on the floor (flat rectangles behind treadmills) are removed;
  3. every material of the scenes becomes one of the Sand Stone materials (MATERIALS), by the rules of parts.py
     (name, then colour) and a few overrides for parts those rules cannot tell apart (ROLE_TO_SANDSTONE, OVERRIDES).

Files in the work folder (read by the MAXScript):
  sandstone_materials.tsv   one line per Sand Stone material: its settings (MATERIAL_FIELDS)
  <scene>_actions.tsv       equipment \t keep|remove|recolour \t why
  sandstone_map.tsv         scene material \t Sand Stone material
  sandstone_swatches.tsv    the swatch materials (a node made only of these, small and simple, is removed)
  sandstone_zones.tsv       the free-space zone materials (a flat node made only of these, big, is removed)
"""
import csv
import re
from pathlib import Path

from . import parts

RECOLOURED_LAYER = "Sand Stone - recoloured (was black)"
TWIN_TOLERANCE_CM = 1.5

# The Sand Stone materials. Colours are sRGB; tile_mm is the size of one texture tile on the object (triplanar
# mapping, so the texture needs no UVs); round_mm the Corona Round Edges radius (renders), chamfer_mm the most a real
# chamfer may take off a sharp edge (scripts/chamfer_edges.ms: the geometry). Maps are corona_materials.maps
# files (without .png). Colours are from the catalogue's swatches: Speckled Stone (200,196,184), Clay (120,103,92),
# Warm Titanium (170,155,135 as photographed; as a metal's reflectance a little lighter).
MATERIALS = {
    "SS_Warm_Titanium": dict(metal=1, rgb=(192, 185, 172), rough=0.45, rough_map="warm_titanium_rough",
                             bump_map="warm_titanium_bump", bump=0.25, tile_mm=40, coat=0.15, coat_rough=0.3,
                             round_mm=2.5, chamfer_mm=4.0),
    "SS_Speckled_Stone": dict(rgb=(200, 196, 184), albedo="speckled_stone_albedo", rough=0.46,
                              rough_map="speckled_stone_rough", bump_map="speckled_stone_bump", bump=0.12,
                              tile_mm=120, round_mm=3.0, chamfer_mm=5.0),
    "SS_Clay_Upholstery": dict(rgb=(120, 103, 92), albedo="clay_leather_albedo", rough=0.58,
                               rough_map="clay_leather_rough", bump_map="clay_leather_bump", bump=0.45, tile_mm=80,
                               ior=1.45, sheen=0.35, sheen_rgb=(206, 188, 172), sheen_rough=0.45, round_mm=5.0,
                               chamfer_mm=10.0),
    "SS_Clay_Soft_Touch": dict(rgb=(104, 89, 79), rough=0.55, bump_map="stipple_bump", bump=0.12, tile_mm=30,
                               ior=1.48, round_mm=2.0, chamfer_mm=3.0),
    "SS_Umber": dict(rgb=(88, 76, 67), rough=0.5, bump_map="stipple_bump", bump=0.1, tile_mm=30, round_mm=2.0,
                     chamfer_mm=3.0),
    "SS_Espresso_Rubber": dict(rgb=(64, 54, 48), rough=0.72, bump_map="stipple_bump", bump=0.15, tile_mm=20,
                               ior=1.52, round_mm=1.5, chamfer_mm=2.0),
    "SS_Clay_Urethane": dict(rgb=(118, 101, 89), rough=0.36, bump_map="stipple_bump", bump=0.05, tile_mm=40,
                             round_mm=2.5, chamfer_mm=3.0),
    "SS_Ivory": dict(rgb=(226, 220, 208), rough=0.4, bump_map="stipple_bump", bump=0.05, tile_mm=40, round_mm=2.0,
                     chamfer_mm=3.0),
    "SS_Taupe": dict(rgb=(130, 119, 108), rough=0.45, bump_map="stipple_bump", bump=0.06, tile_mm=40, round_mm=2.0,
                     chamfer_mm=3.0),
    "SS_Running_Belt": dict(rgb=(58, 54, 50), albedo="belt_albedo", rough=0.7, rough_map="belt_rough",
                            bump_map="belt_bump", bump=0.4, tile_mm=50, chamfer_mm=1.0),
    "SS_Polished_Steel": dict(metal=1, rgb=(232, 232, 236), rough=0.05, round_mm=1.0, chamfer_mm=1.0),
    "SS_Brushed_Steel": dict(metal=1, rgb=(206, 206, 210), rough=0.30, rough_map="brushed_rough",
                             bump_map="brushed_bump", bump=0.05, tile_mm=60, round_mm=1.0, chamfer_mm=1.0),
    "SS_TG_Yellow": dict(rgb=(232, 190, 44), rough=0.32, bump_map="stipple_bump", bump=0.05, tile_mm=30,
                         round_mm=1.5, chamfer_mm=2.0),
    "SS_Red_Button": dict(rgb=(185, 22, 20), rough=0.22, round_mm=1.5, chamfer_mm=1.5),
    "SS_Screen_Glass": dict(rgb=(5, 5, 6), rough=0.02, ior=1.52, chamfer_mm=1.0),
    # a console screen: the scene's own display image, glowing a little (kind = display)
    "SS_Display": dict(rgb=(5, 5, 6), rough=0.02, ior=1.52, kind="display", glow=1.2, chamfer_mm=1.0),
    # logos and stickers: the scene's own logo image as a mask between the print and the plate (kind = logo)
    "SS_Logo_Light": dict(rgb=(226, 220, 208), rough=0.35, kind="logo", print_rgb=(78, 68, 60), chamfer_mm=2.0),
    "SS_Logo_Champagne": dict(metal=1, rgb=(196, 176, 130), rough=0.3, kind="logo", print_rgb=(60, 52, 46),
                              chamfer_mm=2.0),
    # weight plates and dumbbell faces carry their print as a "dark" logo: clay, printed in ivory
    "SS_Logo_Dark": dict(rgb=(118, 101, 89), rough=0.36, kind="logo", print_rgb=(232, 226, 214), chamfer_mm=3.0),
}
MATERIAL_FIELDS = ["name", "kind", "metal", "rgb", "albedo", "rough", "rough_map", "bump_map", "bump", "tile_mm",
                   "ior", "coat", "coat_rough", "sheen", "sheen_rgb", "sheen_rough", "round_mm", "glow", "print_rgb",
                   "chamfer_mm"]

# the roles of parts.py -> the Sand Stone material
ROLE_TO_SANDSTONE = {
    "TG_SAND_FRAME": "SS_Warm_Titanium",
    "TG_SAND_PLASTIC": "SS_Speckled_Stone",
    "TG_SAND_PLASTIC_DARK": "SS_Clay_Soft_Touch",
    "TG_UPHOLSTERY": "SS_Clay_Upholstery",
    "TG_UPHOLSTERY_DARK": "SS_Clay_Upholstery",
    "TG_BELT": "SS_Running_Belt",
    "TG_LOGO_WHITE": "SS_Logo_Light",
    "TG_LOGO_GOLD": "SS_Logo_Champagne",
    "TG_LOGO_DARK": "SS_Logo_Dark",
    "TG_BLACK_PLASTIC": "SS_Espresso_Rubber",
    "TG_BLACK_GLOSS": "SS_Warm_Titanium",      # black metal frames (racks, rigs)
    "TG_CHROME": "SS_Polished_Steel",
    "TG_METAL_SATIN": "SS_Brushed_Steel",
    "TG_RUBBER": "SS_Espresso_Rubber",
    "TG_PLASTIC_DARK_GREY": "SS_Umber",
    "TG_PLASTIC_MID_GREY": "SS_Taupe",
    "TG_PLASTIC_LIGHT_GREY": "SS_Ivory",
    "TG_WHITE": "SS_Ivory",
    "TG_YELLOW": "SS_TG_Yellow",
    "TG_RED": "SS_Clay_Urethane",               # coloured weight plates and grips become clay
    "TG_GREEN": "SS_Clay_Urethane",
    "TG_BLUE": "SS_Clay_Urethane",
}

# (pattern on the material name, Sand Stone material): looked at before the rules, first match wins
OVERRIDES = [
    (r"red_button", "SS_Red_Button"),
    # Technogym's own Sand Stone reference set (the Artis machines merged into a scene)
    (r"^Material #2147464532$", "SS_Speckled_Stone"),
    (r"^Material #899$", "SS_Warm_Titanium"),
    (r"^Material #2$", "SS_Logo_Light"),
    (r"^Material #2147464504$", "SS_Warm_Titanium"),
    (r"^Material #(908)$", "SS_Clay_Soft_Touch"),
    (r"^Material #4$", "SS_Clay_Upholstery"),
    (r"^Material #(978|10909|10914)$", "SS_Running_Belt"),
    (r"^Material #901$", "SS_Screen_Glass"),
    (r"^Material #904$", "SS_Display"),
    (r"^Material #903$", "SS_TG_Yellow"),
    (r"^Material #977$", "SS_Red_Button"),
    (r"^Material #(976|10912|11095|11096)$", "SS_Ivory"),
    (r"^Material #(29|2147464533)$", "SS_Polished_Steel"),
    (r"^Material #(974|975)$", "SS_Umber"),
    (r"^Material #(902|905|906|10910|10911|10916|10917)$", "SS_Espresso_Rubber"),
    # parts of the Technogym models the rules cannot tell apart (checked on colour-coded renders)
    (r"^TG_artis_cardio_(sandstone|diamondblack|anthracitesilver)_plastic_2$", "SS_Warm_Titanium"),  # handles, tubes
    (r"^TG_artis_cardio_(sandstone|diamondblack|anthracitesilver)_plastic_3$", "SS_Clay_Soft_Touch"),  # trims
    (r"^TG_biostrength_(sandstone|diamondblack|anthracitesilver)_plastic_2$", "SS_Clay_Soft_Touch"),  # grips, base
    (r"^(Grey_Dumb|New_Disk_Grey|new_disk|Plastic_Grey_Har)", "SS_Clay_Urethane"),  # dumbbell heads, plates
    (r"^e4ab1202_1d96_4988_8a9c_7b34b0b5c04e$", "SS_Clay_Urethane"),                 # weight plates
    (r"^material__(2|6)_aee9efb6$", "SS_Warm_Titanium"),                              # bike frame and posts
    (r"^material__10_aee9efb6$", "SS_Clay_Soft_Touch"),
    (r"^fdcce71c_4f00_471f_8d7c_df0263cd6e9b$", "SS_Brushed_Steel"),                  # bike flywheel
    (r"^_auto_$", "SS_Ivory"),                                                       # SketchUp's default faces
    (r"^_auto_58$", "SS_Speckled_Stone"),       # the free-space zones' colour, where it is on a real part
    (r"^acad11b286c2$", "SS_Clay_Urethane"),                                        # wellness balls
    (r"^Plastic_Black_caec0045$", "SS_Clay_Urethane"),                              # medicine balls on racks
    (r"^Material__(28|33|34|35|36|37|41|44|46|47|62|65|381)_d9ef82fd$", "SS_Clay_Urethane"),  # kettlebells
    (r"^(d475d179_e5b1_45e9_ad8c_73abedca97c9|M_36bd3678_d019_43a9_89f7_f7bdb5645275)$", "SS_Clay_Urethane"),  # ditto
    (r"^M_731ccdf6_9c79_4b09_9f86_3a53356f245e$", "SS_Clay_Soft_Touch"),            # exercise mats
]

# the free-space zones some models draw on the floor (a flat rectangle at a treadmill, in a swatch colour or one of
# these): not a thing, removed when flat (1 mm), simple (8 faces) and at least 300 mm both ways
ZONE_MATERIALS = ["_auto_58"]

DARK_LUMINANCE = 60      # a material darker than this counts as black
DARK_SHARE = 0.6         # equipment whose faces are this much dark (and not named sandstone) is black


def known_colours(tool_dir):
    """The original (SketchUp) colours of the Technogym model's materials, from examples/technogym/part_map.csv:
    the scenes' own colours were already changed by an earlier conversion."""
    path = Path(tool_dir) / "examples" / "technogym" / "part_map.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["source"]: [int(v) for v in r["skp_rgb"].split(",")] for r in csv.DictReader(f)}


def colour_of(name, rgb, known):
    return known.get(name) or rgb or [128, 128, 128]


def material_target(name, rgb):
    """(Sand Stone material, why) for a scene material of this name and (original) colour."""
    for pattern, target in OVERRIDES:
        if re.search(pattern, name):
            return target, f"override /{pattern}/"
    sand = re.sub(r"diamondblack|anthracitesilver", "sandstone", name)
    role, why = parts.classify(sand, rgb)
    return ROLE_TO_SANDSTONE[role], f"{role} ({why})"


def is_swatch_material(name, rgb):
    """A pure accent colour that is not one of the maker's named materials: the colour cubes beside machines."""
    if name.startswith(("TG", "Material #")) or re.search(r"yellow|handle|logo|button|leva|movimento", name, re.I):
        return False
    h, s, v = parts.hsv(rgb)
    return s >= 0.6 and v >= 0.5


def is_zone_material(name, rgb):
    """A colour a free-space zone can be drawn in: one of ZONE_MATERIALS, or any accent colour (not the maker's)."""
    if name in ZONE_MATERIALS:
        return True
    if name.startswith(("TG", "Material #")):
        return False
    return parts.accent(rgb) is not None


def finish(eq, known):
    """black, sand or neutral: the equipment's finish, by its name, its TG materials, else its share of dark faces."""
    if re.search(r"diamondblack|anthracite", eq["eq"], re.I):
        return "black"
    if re.search(r"sandstone", eq["eq"], re.I):
        return "sand"
    tg = [m for m in eq["mats"] if m["m"].startswith("TG_")]
    black = sum(m["f"] for m in tg if re.search(r"diamondblack|anthracite", m["m"]))
    sand = sum(m["f"] for m in tg if "sandstone" in m["m"])
    if black > sand:
        return "black"
    if sand:
        return "sand"
    if re.match(r"Material #", " ".join(m["m"] for m in eq["mats"])):
        return "sand"   # Technogym's own Sand Stone reference set
    total = sum(m["f"] for m in eq["mats"]) or 1
    dark = sum(m["f"] for m in eq["mats"] if parts.lum(colour_of(m["m"], m["rgb"], known)) < DARK_LUMINANCE)
    return "black" if dark / total >= DARK_SHARE else "neutral"


def dims_cm(eq):
    return sorted((b - a) / 10 for a, b in zip(eq["min"], eq["max"]))


def decide(scenes, known):
    """{scene: [(equipment, action, why)]} for every scene's equipment ({scene: [survey rows]}); twins are looked
    for in every scene."""
    rows = [(scene, eq) for scene, eqs in scenes.items() for eq in eqs]
    fin = {id(eq): finish(eq, known) for _, eq in rows}
    creamy = [(scene, eq) for scene, eq in rows if fin[id(eq)] != "black"]
    out = {scene: [] for scene in scenes}
    for scene, eq in rows:
        if fin[id(eq)] != "black":
            out[scene].append((eq["eq"], "keep", fin[id(eq)]))
            continue
        d = dims_cm(eq)
        twin = next(((s, e) for s, e in creamy
                     if all(abs(a - b) <= TWIN_TOLERANCE_CM for a, b in zip(d, dims_cm(e)))), None)
        if twin:
            out[scene].append((eq["eq"], "remove", f"black; in Sand Stone as {twin[1]['eq']} ({twin[0]})"))
        elif eq.get("hidden"):
            out[scene].append((eq["eq"], "remove", "black, and hidden in the scene: not needed"))
        else:
            out[scene].append((eq["eq"], "recolour", "black; no Sand Stone version in the scenes"))
    return out


def material_rows(materials, known):
    """[(scene material, Sand Stone material, original colour, why)] for every material of the scenes."""
    out = []
    for name, rgb in sorted(materials.items()):
        c = colour_of(name, rgb, known)
        target, why = material_target(name, c)
        out.append((name, target, c, why))
    return out


def linear255(c):
    """An sRGB colour (0..255) as 3ds Max reads a colour value with colour management on: linear, 0..255."""
    out = []
    for x in c:
        x /= 255
        out.append(255 * (x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4))
    return out


def write(work, actions, mrows, swatches, zones=ZONE_MATERIALS):
    """The tsv files for the MAXScript (colours in linear 0..255, as 3ds Max reads them)."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)

    def cell(v):
        if v is None:
            return ""
        if isinstance(v, (tuple, list)):
            return ",".join(f"{x:.3f}" for x in linear255(v))
        return str(v)
    with open(work / "sandstone_materials.tsv", "w", encoding="utf-8") as f:
        for name, spec in MATERIALS.items():
            row = {"name": name, "kind": spec.get("kind", "plain"), "metal": spec.get("metal", 0),
                   "ior": spec.get("ior", 1.5), **{k: v for k, v in spec.items() if k not in ("kind", "metal", "ior")}}
            f.write("\t".join(cell(row.get(k)) for k in MATERIAL_FIELDS) + "\n")
    with open(work / "sandstone_map.tsv", "w", encoding="utf-8") as f:
        for name, target, _, _ in mrows:
            f.write(f"{name}\t{target}\n")
    with open(work / "sandstone_swatches.tsv", "w", encoding="utf-8") as f:
        for name in swatches:
            f.write(name + "\n")
    with open(work / "sandstone_zones.tsv", "w", encoding="utf-8") as f:
        for name in zones:
            f.write(name + "\n")
    for scene, acts in actions.items():
        with open(work / f"{scene}_actions.tsv", "w", encoding="utf-8") as f:
            for eq, action, why in acts:
                f.write(f"{eq}\t{action}\t{why}\n")
