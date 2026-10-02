"""Running a step's MAXScript in 3ds Max without its window (3dsmaxbatch.exe).

The step's settings reach the script as MAXScript globals: a small run_<step>.ms in the work folder defines them
(global ING_WORK = @"..."), then fileIn's the script. Every script writes its own log in the work folder and ends it
with DONE, or with ERROR: and the reason.
"""
import glob
import re
import subprocess
import time
from pathlib import Path

from ing_core.util import detail, duration, log

TOOL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = TOOL_DIR / "scripts"
BATCH_PATTERN = r"C:\Program Files\Autodesk\3ds Max {year}\3dsmaxbatch.exe"


class MaxError(RuntimeError):
    pass


def find_batch(version="auto"):
    """3dsmaxbatch.exe of the 3ds Max year asked for, or of the newest one installed."""
    year = "20*" if version in (None, "auto") else str(version)
    hits = sorted(glob.glob(BATCH_PATTERN.format(year=year)))
    if not hits:
        raise MaxError(f"3ds Max {'' if year == '20*' else year + ' '}not found ({BATCH_PATTERN.format(year=year)}); "
                       "install it (with Corona) or set max.version")
    return hits[-1]


def mxs_value(v):
    """A Python value as MAXScript source: paths as verbatim strings, numbers as they are."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    text = str(v)
    if '"' in text:
        raise MaxError(f"a setting for 3ds Max may not contain a double quote: {text}")
    return f'@"{text}"'


def settings_script(script, values):
    """The source of run_<step>.ms: the globals, then the step's script."""
    lines = [f"global {k} = {mxs_value(v)}" for k, v in values.items()]
    return "\n".join(lines + [f"fileIn {mxs_value(script)}", ""])


def last_line(path):
    try:
        lines = [ln for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except FileNotFoundError:
        return ""
    return lines[-1] if lines else ""


def run_step(batch_exe, step, script, values, step_log):
    """Run scripts/<script> with these ING_* globals; step_log is the log the script writes (its last line decides)."""
    work = Path(values["ING_WORK"])
    work.mkdir(parents=True, exist_ok=True)
    runner = work / f"run_{step}.ms"
    runner.write_text(settings_script(SCRIPTS / script, values), encoding="utf-8")
    Path(step_log).unlink(missing_ok=True)
    listener = work / f"{step}_listener.log"
    log(f"{step}: 3ds Max works on it without a window (log: {step_log}) ...")
    detail(f"run {batch_exe} {runner}")
    t0 = time.time()
    p = subprocess.run([batch_exe, str(runner), "-listenerLog", str(listener)], capture_output=True)
    end = last_line(step_log)
    detail(f"3dsmaxbatch finished in {duration(time.time() - t0)} (exit code {p.returncode}): {end}")
    if not re.search(r"\bDONE$", end):
        reason = end.split("ERROR:", 1)[-1].strip() if "ERROR:" in end else \
            f"3ds Max stopped before the end (exit code {p.returncode}); see {listener}"
        raise MaxError(f"{step}: {reason}")
