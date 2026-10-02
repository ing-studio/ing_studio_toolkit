"""Configuration of a tool: config/default.json <- config/project.json <- --config files <- --set / command line flags.

Later layers override earlier ones key by key (nested sections are merged, lists are replaced). Each tool keeps its
own checks (a validate function) and calls load() with its folder.
"""
import copy
import json
import os
from pathlib import Path

from .util import LOCAL_DIR


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


def read_json(path):
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


def default_work_dir(tool_dir):
    """The cache of a tool's intermediate results: %LOCALAPPDATA%\\ing_studio_toolkit\\<tool>."""
    return LOCAL_DIR / Path(tool_dir).name


def load(tool_dir, validate, extra_files=(), assignments=(), use_project=True):
    """The settings of the tool in tool_dir: its config/default.json, overlaid by config/project.json (unless
    use_project is false), the extra files and the assignments ('key=value' or (keys, value)), then validated."""
    config_dir = Path(tool_dir) / "config"
    default_file, project_file = config_dir / "default.json", config_dir / "project.json"
    cfg = read_json(default_file)
    layers = ([project_file] if use_project and project_file.exists() else []) + [Path(p) for p in extra_files]
    for path in layers:
        cfg = deep_merge(cfg, read_json(path))
    for a in assignments:
        keys, value = a if isinstance(a, tuple) else parse_assignment(a)
        set_value(cfg, keys, value)
    validate(cfg)
    cfg["_files"] = [str(default_file)] + [str(p) for p in layers]
    # relative folders are relative to the folder the command is run from
    cfg["_output"] = Path(os.path.abspath(cfg["paths"]["output_dir"] or "output"))
    cfg["_work"] = Path(os.path.abspath(cfg["paths"]["work_dir"] or default_work_dir(tool_dir)))
    return cfg


def settings(cfg, *sections):
    """The config sections a stage result depends on (without notes): stored with the result, compared for skip.
    A section may be a dotted path ('roads.profile')."""
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
