"""Configuration: config/default.json <- config/project.json <- --config files <- --set / command line flags.

Later layers override earlier ones key by key (nested sections are merged, lists are replaced).
"""
import copy
import json
import os
from pathlib import Path

from .util import PIPELINE_DIR

CONFIG_DIR = PIPELINE_DIR / "config"
DEFAULT_FILE = CONFIG_DIR / "default.json"
PROJECT_FILE = CONFIG_DIR / "project.json"


class ConfigError(ValueError):
    pass


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: invalid JSON ({e})")


def parse_assignment(text):
    """'contours.cut_sizes_m=[1,2,5]' -> (['contours', 'cut_sizes_m'], [1, 2, 5]); values are JSON, else strings."""
    if "=" not in text:
        raise ConfigError(f"--set expects section.key=value, got {text!r}")
    key, raw = text.split("=", 1)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return [p for p in key.strip().split(".") if p], value


def set_value(cfg, keys, value):
    node = cfg
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            raise ConfigError(f"unknown config section {'.'.join(keys[:-1])!r}")
        node = node[k]
    if keys[-1] not in node:
        raise ConfigError(f"unknown config key {'.'.join(keys)!r} (see config/default.json)")
    node[keys[-1]] = value


def load_config(extra_files=(), assignments=(), use_project=True):
    cfg = _read(DEFAULT_FILE)
    layers = ([PROJECT_FILE] if use_project and PROJECT_FILE.exists() else []) + [Path(p) for p in extra_files]
    for path in layers:
        cfg = deep_merge(cfg, _read(path))
    for a in assignments:
        keys, value = a if isinstance(a, tuple) else parse_assignment(a)
        set_value(cfg, keys, value)
    validate(cfg)
    cfg["_files"] = [str(DEFAULT_FILE)] + [str(p) for p in layers]
    for key in ("input_dir", "output_dir", "work_dir"):
        p = Path(cfg["paths"][key])
        cfg["_" + key[:-4]] = Path(os.path.normpath(p if p.is_absolute() else PIPELINE_DIR / p))
    return cfg


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


def settings(cfg, *sections):
    """The config sections a stage result depends on (without notes): stored with the result, compared for skip."""
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if not k.startswith("_")}
        return v
    return {s: clean(cfg[s]) for s in sections}
