"""Shared helpers: logging, JSON files, file identity, external tools."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent

TOOL_SEARCH = {
    "pdal_exe": [r"C:\Program Files\QGIS*\bin\pdal.exe"],
    "cloudcompare_exe": [r"C:\Program Files\CloudCompare*\CloudCompare.exe"],
    "archicad_exe": [r"C:\Program Files\GRAPHISOFT\Archicad 28*\Archicad.exe"],
    "archicad_template": [r"C:\Program Files\GRAPHISOFT\Archicad 28*\Defaults\Archicad\*.tpl"],
}

_log_file = None


# --------------------------------------------------------------------------- logging
def set_log_file(path):
    global _log_file
    _log_file = Path(path) if path else None


def log_file():
    return _log_file


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:  # a console code page without the characters of a path
        print(line.encode("ascii", "replace").decode(), flush=True)
    if _log_file is not None:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------- files
def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def file_signature(path):
    """Name, size and date of a file: identifies an input without reading it."""
    st = os.stat(path)
    return {"name": os.path.basename(path).lower(), "size": st.st_size, "mtime": int(st.st_mtime)}


def same_path(a, b):
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "job"


def all_exist(paths):
    return all(Path(p).exists() for p in paths)


# --------------------------------------------------------------------------- external tools
def tool(cfg, key):
    """Executable from the config, else the newest standard install, else PATH."""
    configured = cfg["tools"].get(key)
    if configured and os.path.exists(configured):
        return configured
    for pattern in TOOL_SEARCH.get(key, []):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    found = shutil.which(Path(configured).name if configured else key)
    if found:
        return found
    raise RuntimeError(f"{key} not found (config tools.{key} = {configured!r}); install it or set tools.{key}")


def app_env():
    """Environment for other applications: without the Qt settings of QGIS, whose Python runs this tool - with
    them, Qt programs such as CloudCompare cannot start (they wait on a 'no Qt platform plugin' message)."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("QT_")}


def run(cmd, check=True):
    """Run an external command; returns (code, stdout, stderr)."""
    log("RUN " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
    t0 = time.time()
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=app_env())
    log(f"    exit={p.returncode} in {time.time() - t0:.1f}s")
    if check and p.returncode != 0:
        sys.stderr.write(p.stdout[-4000:] + "\n" + p.stderr[-4000:] + "\n")
        raise RuntimeError(f"Command failed ({p.returncode}): {cmd[0]}")
    return p.returncode, p.stdout, p.stderr
