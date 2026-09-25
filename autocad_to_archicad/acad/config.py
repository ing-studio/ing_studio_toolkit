"""Configuration: config/default.json <- config/project.json <- --config files <- --set / command line flags.

Later layers override earlier ones key by key (nested sections are merged, lists are replaced).
"""
import copy
import json
import os
from pathlib import Path

from .util import PIPELINE_DIR

CONFIG_DIR = PIPELINE_DIR / "config"
DEFAULT_WORK_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ing_studio_toolkit" / PIPELINE_DIR.name
DEFAULT_FILE = CONFIG_DIR / "default.json"
PROJECT_FILE = CONFIG_DIR / "project.json"
UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}


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
    """'roads.proposed.class=district' -> (['roads', 'proposed', 'class'], 'district'); values are JSON, else strings."""
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
    cfg["_output"] = Path(os.path.abspath(cfg["paths"]["output_dir"] or "output"))
    cfg["_work"] = Path(os.path.abspath(cfg["paths"]["work_dir"] or DEFAULT_WORK_DIR))
    return cfg


def validate(cfg):
    units = cfg["drawing"]["units"]
    if units != "auto" and units not in UNITS:
        raise ConfigError(f"drawing.units must be auto or one of {', '.join(UNITS)}, got {units!r}")
    region = cfg["drawing"]["region"]
    if region != "auto" and not (isinstance(region, list) and len(region) == 4):
        raise ConfigError("drawing.region must be auto or [x1, y1, x2, y2]")
    ll = cfg["site"]["lonlat"]
    if ll not in (None, "auto") and not (isinstance(ll, list) and len(ll) == 2 and -180 <= ll[0] <= 180
                                          and -90 <= ll[1] <= 90):
        raise ConfigError(f"site.lonlat must be auto or [longitude, latitude], got {ll!r}")
    for role, v in cfg["layers"].items():
        if role.startswith("_") or role == "hints":
            continue
        if v != "auto" and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ConfigError(f"layers.{role} must be auto or a list of layer name patterns, got {v!r}")
    for sec in ("georef", "cloud"):
        if cfg[sec]["mode"] not in ("auto", "manual"):
            raise ConfigError(f"{sec}.mode must be auto or manual")
    if cfg["georef"]["mode"] == "manual" and not cfg["georef"]["manual_origin_utm"]:
        raise ConfigError("georef.mode=manual needs georef.manual_origin_utm = [easting, northing]")
    if cfg["cloud"]["mode"] == "manual" and not cfg["cloud"]["manual_origin_dwg_m"]:
        raise ConfigError("cloud.mode=manual needs cloud.manual_origin_dwg_m = [x, y]")
    z = cfg["cloud"]["z_to_altitude"]
    if z != "auto" and not isinstance(z, (int, float)):
        raise ConfigError("cloud.z_to_altitude must be auto or a number")
    if cfg["roads"]["proposed"]["class"] not in cfg["roads"]["standards"]:
        raise ConfigError(f"roads.proposed.class must be one of {', '.join(cfg['roads']['standards'])}")
    for key in ("layer_terrain", "layer_roads_existing", "layer_roads_proposed", "layer_sidewalks", "layer_road_lines",
                "layer_walls", "layer_buildings_existing", "layer_buildings_proposed", "layer_underground", "layer_trees",
                "layer_walls_existing", "layer_context_terrain", "layer_context_buildings", "layer_contours",
                "layer_hotlinks"):
        if not cfg["archicad"][key].startswith(cfg["archicad"]["layer_prefix_site"]):
            raise ConfigError(f"archicad.{key} must start with archicad.layer_prefix_site")
    v = cfg["archicad"]["version"]
    if v != "auto" and v not in (28, 29):
        raise ConfigError(f"archicad.version must be auto, 28 or 29, got {v!r}")
    for h in cfg["archicad"]["hotlinks"]:
        missing = [k for k in ("name", "file", "x", "y", "altitude", "rotation_deg") if k not in h]
        if missing:
            raise ConfigError(f"archicad.hotlinks item {h.get('name', '?')!r} lacks {', '.join(missing)}")
    cols = cfg["archicad"]["contours"]["colours"]
    if not (isinstance(cols, list) and cols and all(isinstance(c, list) and len(c) == 3 for c in cols)):
        raise ConfigError("archicad.contours.colours must be a list of [red, green, blue] (0-255)")
    for key, sf in cfg["archicad"]["surfaces"].items():
        if key.startswith("_"):
            continue
        if not (isinstance(sf, dict) and sf.get("name") and len(sf.get("rgb", [])) == 3
                and all(0 <= c <= 1 for c in sf["rgb"])):
            raise ConfigError(f"archicad.surfaces.{key} must be {{\"name\": ..., \"rgb\": [r, g, b] (0-1)}}")


def settings(cfg, *sections):
    """The config sections a stage result depends on (without notes): stored with the result, compared for skip."""
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if not k.startswith("_")}
        return v
    out = {}
    for s in sections:
        node = cfg
        for part in s.split("."):
            node = node[part]
        out[s] = clean(node)
    return out
