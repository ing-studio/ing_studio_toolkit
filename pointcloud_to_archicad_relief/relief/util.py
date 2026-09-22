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
_stage = ""

# level -> (label, ANSI colour of the label)
LEVELS = {
    "info": ("INFO", ""),
    "detail": (" .. ", "90"),   # grey: commands and small progress steps
    "skip": ("SKIP", "36"),     # cyan: cached result reused
    "ok": (" OK ", "32"),       # green
    "warn": ("WARN", "33"),     # yellow
    "error": ("FAIL", "31"),    # red
}
_TAG = re.compile(r"^([a-z]+): ")


# --------------------------------------------------------------------------- logging
def _enable_colour():
    """Colours on a real console only (not when the output goes to a file); NO_COLOR turns them off."""
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    try:  # Windows: switch the console to ANSI mode
        import ctypes
        k = ctypes.windll.kernel32
        h, mode = k.GetStdHandle(-11), ctypes.c_uint32()
        return bool(k.GetConsoleMode(h, ctypes.byref(mode)) and k.SetConsoleMode(h, mode.value | 4))
    except Exception:
        return False


_COLOUR = _enable_colour()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _COLOUR and code else text


def set_log_file(path):
    global _log_file
    _log_file = Path(path) if path else None


def log_file():
    return _log_file


def set_stage(name):
    """The tag of messages that do not name one ('ground: ...' names its own)."""
    global _stage
    _stage = name or ""


def _print(text):
    try:
        print(text, flush=True)
    except UnicodeEncodeError:  # a console code page without the characters of a path
        print(text.encode("ascii", "replace").decode(), flush=True)


def _to_file(text):
    if _log_file is not None:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def log(msg, level="info", console=True):
    """One message: time, level, tag (the stage), text. Coloured on the console, plain in the log file."""
    msg = str(msg)
    m = _TAG.match(msg)
    tag, text = (m.group(1), msg[m.end():]) if m else (_stage, msg)
    label, colour = LEVELS[level]
    lines = text.splitlines() or [""]
    pad = " " * 26
    _to_file(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {label}  {tag:10s} {lines[0]}"
             + "".join(f"\n{pad}{ln}" for ln in lines[1:]))
    if console:
        body = _c("90", text) if level == "detail" else _c(colour, text) if level in ("warn", "error") else text
        blines = body.splitlines() or [""]
        _print(f"{_c('90', time.strftime('%H:%M:%S'))}  {_c(colour + ';1' if colour else '1', label)}  "
               f"{_c('36', f'{tag:10s}')} {blines[0]}" + "".join(f"\n{' ' * 27}{ln}" for ln in blines[1:]))


def detail(msg):
    log(msg, "detail")


def skip(msg):
    log(msg, "skip")


def ok(msg):
    log(msg, "ok")


def warn(msg):
    log(msg, "warn")


def error(msg, console=True):
    log(msg, "error", console)


def section(title):
    """A heading between the parts of a run."""
    line = f"=== {title} " + "=" * max(3, 100 - len(title))
    _to_file("\n" + line)
    _print("\n" + _c("1;34", line))


def duration(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


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
    detail("run " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
    t0 = time.time()
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=app_env())
    log(f"{Path(str(cmd[0])).name} finished in {duration(time.time() - t0)} (exit code {p.returncode})",
        "detail" if p.returncode == 0 else "error")
    if check and p.returncode != 0:
        error("output of the command:\n" + (p.stdout[-4000:] + "\n" + p.stderr[-4000:]).strip(), console=False)
        raise RuntimeError(f"Command failed ({p.returncode}): {cmd[0]}")
    return p.returncode, p.stdout, p.stderr
