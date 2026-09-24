"""DWG -> DXF through AutoCAD's own console (accoreconsole.exe, no window, no user interaction).

1. -EXPORTTOAUTOCAD: AutoCAD Architecture / Civil 3D objects become plain AutoCAD objects (without it they are
   'proxy' objects no other program can read); bound XREFs stay, missing ones are reported.
2. SAVEAS DXF 2018 at full precision.
Both run on a copy in a local temporary folder with a plain name, so network paths, open files (the DWG may be open
in someone's AutoCAD) and unusual characters never reach AutoCAD. Script files hold only the commands (no LISP:
AutoCAD's SECURELOAD would refuse a script file from the temporary folder, and it is not changed here).
"""
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..util import detail, duration, log, tool, warn

LICENCE_WORDS = ("licens", "sign in", "sign-in", "subscription")


def _decode(raw):
    if raw.count(b"\x00") > len(raw) // 4:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _run(exe, dwg, script_lines, tmp, name, timeout):
    """Run one console session on `dwg` with the given script; returns its transcript."""
    scr = tmp / f"{name}.scr"
    scr.write_bytes(("\r\n".join(script_lines) + "\r\n").encode("ascii"))  # an empty line would answer a prompt
    out = tmp / f"{name}.out"
    t0 = time.time()
    with open(out, "wb") as f:
        proc = subprocess.Popen([exe, "/i", str(dwg), "/s", str(scr), "/l", "en-US"], stdout=f, stderr=subprocess.STDOUT,
                                cwd=str(tmp))
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            text = _decode(out.read_bytes())
            raise RuntimeError(f"AutoCAD console did not finish '{name}' within {timeout} s (it may be waiting for an "
                               f"answer); last output:\n{text[-1500:]}")
    text = _decode(out.read_bytes()).replace("\x00", "")
    detail(f"read: AutoCAD console '{name}' finished in {duration(time.time() - t0)} (exit code {proc.returncode})")
    low = text.lower()
    if any(w in low for w in LICENCE_WORDS) and "command:" not in low:
        raise RuntimeError("AutoCAD console needs a licence / sign-in: start AutoCAD once, sign in, and run again")
    return text


def xrefs_of(transcript):
    """[(name, path, loaded)] of the XREFs AutoCAD reported while opening the drawing."""
    found = {}
    for m in re.finditer(r'Xref "([^"]+)":\s*(.+)', transcript):
        found[m.group(1)] = {"name": m.group(1), "path": m.group(2).strip(), "loaded": True}
    for m in re.finditer(r'"([^"]+)" is unloaded', transcript):
        if m.group(1) in found:
            found[m.group(1)]["loaded"] = False
    for m in re.finditer(r'Resolve Xref "([^"]+)".*?\n(.*?)\n', transcript):
        if m.group(1) in found and "can't find" in m.group(2).lower():
            found[m.group(1)]["loaded"] = False
    return list(found.values())


def dwg_to_dxf(cfg, dwg, target_dxf):
    """Convert `dwg` into `target_dxf`; returns info about the conversion (transcripts, xrefs, AEC export)."""
    exe = tool(cfg, "accoreconsole_exe")
    timeout = int(cfg["read"]["timeout_s"])
    base = ["FILEDIA", "0", "CMDDIA", "0", "PROXYNOTICE", "0"]
    info = {"accoreconsole": exe, "aec_export": False}
    with tempfile.TemporaryDirectory(prefix="acad_") as t:
        tmp = Path(t)
        if not str(tmp).isascii():
            warn(f"read: the temporary folder {tmp} has non-ASCII characters; AutoCAD may refuse it")
        src = tmp / "in.dwg"
        with open(dwg, "rb") as fi, open(src, "wb") as fo:  # plain reads work while someone has the DWG open
            shutil.copyfileobj(fi, fo, 1 << 20)
        current = src
        if cfg["read"]["export_aec"]:
            plain = tmp / "plain.dwg"
            text = _run(exe, src, base + ["-EXPORTTOAUTOCAD", "", str(plain), "_.QUIT", "_Y"], tmp, "export", timeout)
            info["xrefs"] = xrefs_of(text)
            info["custom_objects"] = "Custom object(s) encountered" in text
            if plain.exists():
                current, info["aec_export"] = plain, True
                log("read: AutoCAD Architecture / custom objects exported to plain AutoCAD objects")
            elif "Unknown command" in text:
                detail("read: this AutoCAD has no EXPORTTOAUTOCAD command; the drawing is saved as it is")
            else:
                warn("read: exporting to plain AutoCAD did not produce a file; the drawing is saved as it is")
        out = tmp / "out.dxf"
        text = _run(exe, current, base + ["_.SAVEAS", "DXF", "V", "2018", "16", str(out), "_.QUIT", "_Y"], tmp, "saveas",
                    timeout)
        if "xrefs" not in info:
            info["xrefs"] = xrefs_of(text)
        if not out.exists():
            raise RuntimeError(f"AutoCAD console did not write the DXF; its output:\n{text[-2000:]}")
        Path(target_dxf).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, target_dxf)
    for x in info["xrefs"]:
        if not x["loaded"]:
            warn(f"read: XREF '{x['name']}' is missing ({x['path']}) - its content is not in the result")
    return info
