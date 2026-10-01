"""Shared helpers: logging, config, paths."""
import json
import os
import time
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent

_log_file = None
_lines = []  # everything logged in this run, for the palette button's summary


def set_log_file(path):
    global _log_file
    _log_file = Path(path) if path else None
    if _log_file:
        _log_file.parent.mkdir(parents=True, exist_ok=True)


def log(msg, level="INFO"):
    text = f"{time.strftime('%H:%M:%S')}  {level:4s}  {msg}"
    _lines.append((level, str(msg)))
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, AttributeError):  # a console without the Armenian letters, or no console at all
        try:
            print(text.encode("ascii", "replace").decode(), flush=True)
        except Exception:
            pass
    if _log_file:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d')} {text}\n")


def warn(msg):
    log(msg, "WARN")


def warnings():
    return [m for level, m in _lines if level == "WARN"]


def same_path(a, b):
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def load_config(extra=None):
    """config/default.json, overlaid by config/project.json (if there) and by the file given with --config."""
    cfg = {}
    for path in [TOOL_DIR / "config" / "default.json", TOOL_DIR / "config" / "project.json", extra]:
        if path and Path(path).exists():
            with open(path, encoding="utf-8") as f:
                _merge(cfg, json.load(f))
    return cfg


def _merge(into, new):
    for k, v in new.items():
        if k.startswith("_"):
            continue  # comments
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _merge(into[k], v)
        else:
            into[k] = v


def mm(metres):
    return int(round(metres * 1000))
