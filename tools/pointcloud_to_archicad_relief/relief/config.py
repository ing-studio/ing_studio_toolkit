"""Configuration: config/default.json <- config/project.json <- --config files <- --set / command line flags.

The layering is the toolkit's (ing_core.config); the checks of this tool's settings are here.
"""
from pathlib import Path

from ing_core.config import ConfigError, load, settings  # noqa: F401  (settings: used by the stages through here)

TOOL_DIR = Path(__file__).resolve().parent.parent


def load_config(extra_files=(), assignments=(), use_project=True):
    return load(TOOL_DIR, validate, extra_files, assignments, use_project)


def validate(cfg):
    sizes = cfg["contours"]["cut_sizes_m"]
    if not sizes or not all(isinstance(s, (int, float)) and s > 0 for s in sizes):
        raise ConfigError(f"contours.cut_sizes_m must be positive numbers, got {sizes!r}")
    if len({cut_label(s) for s in sizes}) != len(sizes):
        raise ConfigError(f"contours.cut_sizes_m has duplicates: {sizes!r}")
    if int(cfg["mesh"]["target_points"]) < 100:
        raise ConfigError("mesh.target_points must be at least 100")
    if cfg["ground"]["method"] not in ("csf", "smrf"):
        raise ConfigError("ground.method must be csf or smrf")
    if cfg["placement"]["mode"] not in ("auto", "object", "coordinates"):
        raise ConfigError("placement.mode must be auto, object or coordinates")
    origin = cfg["placement"]["new_pln_origin"]
    if origin not in ("auto", "keep") and not (isinstance(origin, list) and len(origin) == 2
                                               and all(isinstance(v, (int, float)) for v in origin)):
        raise ConfigError(f"placement.new_pln_origin must be auto, keep or [x, y], got {origin!r}")
    if "{size}" not in cfg["archicad"]["layer_contours"]:
        raise ConfigError("archicad.layer_contours must contain {size}")
    for key in ("layer_mesh", "layer_contours"):
        if not cfg["archicad"][key].startswith(cfg["archicad"]["layer_prefix"]):
            raise ConfigError(f"archicad.{key} must start with archicad.layer_prefix")


def cut_label(size):
    """1 -> '1m', 2.5 -> '2.5m': the name of a cut size in layers, files and logs."""
    return f"{float(size):g}m"


def cut_sizes(cfg):
    """{label: size} of the contour layers, finest first."""
    return {cut_label(s): float(s) for s in sorted(cfg["contours"]["cut_sizes_m"])}
