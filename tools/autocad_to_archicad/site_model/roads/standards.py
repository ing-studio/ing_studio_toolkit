"""The street rules for a class of street on a given terrain (roads.standards, roads.design_speeds).

ՀՀՇՆ 30-01-2023 (Armenia, in force since 30 May 2023; it replaced ՀՀՇՆ 30-01-2014 and the Soviet SNiP 2.07.01-89),
Table 29, gives each class of city street its design speed on normal, rugged ('կտրտված') and mountainous
('լեռնային') terrain, its lane width and number of lanes, and the smallest sidewalk. The smallest radius, the largest
grade and the vertical curves follow from the design speed (ՀՀՇՆ 32-01-2022). The terrain category is a setting, or
'auto': the tool's rule of thumb from the ground slope under the new streets (not a definition of the norm).
"""
import numpy as np

TERRAINS = ("normal", "rugged", "mountainous")


def terrain_category(cfg, slope_permille):
    t = cfg["roads"]["terrain"]
    if t != "auto":
        return t, "roads.terrain"
    lim = cfg["roads"]["terrain_auto_permille"]
    cat = "mountainous" if slope_permille >= lim["mountainous"] else "rugged" if slope_permille >= lim["rugged"] else "normal"
    return cat, f"ground slope under the new streets {slope_permille:.0f} per mille (the tool's rule: rugged from " \
                f"{lim['rugged']}, mountainous from {lim['mountainous']} per mille)"


def resolve(cfg, cls, terrain):
    """Everything the profile design and the checks need for one street class on one terrain."""
    std = dict(cfg["roads"]["standards"][cls])
    speeds = std["design_speed_kmh"]
    v = speeds[TERRAINS.index(terrain)] if isinstance(speeds, list) else speeds
    table = cfg["roads"]["design_speeds"]
    keys = sorted(int(k) for k in table if not k.startswith("_"))
    k = min((s for s in keys if s >= v), default=keys[-1])
    row = table[str(k)]
    out = {"class": cls, "terrain": terrain, "design_speed_kmh": v, "lane_m": std["lane_m"], "lanes": std["lanes"],
           "sidewalk_m": std["sidewalk_m"], "min_radius_m": row["min_radius_m"],
           "max_grade_permille": row["max_grade_permille"],
           "exceptional_grade_permille": row.get("exceptional_grade_permille"),
           "exceptional_max_length_m": row.get("exceptional_max_length_m"),
           "crest_radius_m": row["crest_radius_m"], "sag_radius_m": row["sag_radius_m"],
           "sight_m": row.get("sight_m"), "source": row.get("source", "")}
    return out


def ground_slope(z, gt, mask):
    """Median slope (per mille) of the terrain grid over a mask."""
    gy, gx = np.gradient(z, abs(gt[5]), gt[1])
    s = np.hypot(gx, gy)[mask & np.isfinite(z)]
    return float(np.median(s)) * 1000.0 if len(s) else 0.0
