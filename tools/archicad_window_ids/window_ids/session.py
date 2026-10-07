"""A helper Archicad of its own for the output files: started on a copy, never the designer's open project.

Archicad asks things while it opens a file. Its "Missing Add-Ons" note is answered with OK (that keeps the data of
add-ons not loaded here, which is what a copy should do); any other message box stops the tool instead of guessing
an answer - the dialog is left for the designer to read.
"""
import csv
import glob
import io
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .archicad import PORTS, Archicad, ArchicadError
from .util import log, same_path

KEEP_DATA_TITLES = ("missing add-ons",)
RECOVERY_TITLES = ("archicad project recovery",)


def archicad_exe(version):
    hits = sorted(glob.glob(rf"C:\Program Files\GRAPHISOFT\Archicad {version}*\Archicad.exe"))
    if not hits:
        raise ArchicadError(f"Archicad {version} is not installed on this computer")
    return hits[-1]


def archicad_pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Archicad.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return {int(row[1]) for row in csv.reader(io.StringIO(out)) if len(row) > 1 and row[1].isdigit()}


class DialogWatch:
    """Answers Archicad's "Missing Add-Ons" note in the given processes; notes any other message box."""

    def __init__(self, pids):
        self.pids = set(pids)
        self.message = None
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def check(self):
        if self.message:
            raise ArchicadError(self.message)

    def stop(self):
        self._stop.set()

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def text(h):
            buf = ctypes.create_unicode_buffer(2048)
            user32.GetWindowTextW(h, buf, 2048)
            return buf.value

        def cls(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, buf, 256)
            return buf.value

        def owner(h):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            return pid.value

        def children(h):
            kids = []
            user32.EnumChildWindows(h, proto(lambda c, _: kids.append((c, cls(c), text(c))) or True), 0)
            return kids

        while not self._stop.wait(1.0) and not self.message:
            tops = []
            user32.EnumWindows(proto(lambda h, _: tops.append(h) or True), 0)
            for h in tops:
                if owner(h) not in self.pids or not user32.IsWindowVisible(h):
                    continue
                title = text(h)
                if title.lower() in RECOVERY_TITLES:  # the designer's unsaved work of a crash: theirs to decide
                    self.message = ("The helper Archicad shows 'Archicad Project Recovery': it kept the unsaved work "
                                    "of an Archicad that crashed earlier. Choose there what to do with it (open it "
                                    "and save it, or continue), then run the tool again - it did not touch it.")
                    break
                if title.lower() in KEEP_DATA_TITLES:
                    ok = [c for c, k, t in children(h) if k == "Button" and t.replace("&", "") == "OK"]
                    if ok:
                        user32.SendMessageW(ok[0], 0x00F5, 0, 0)  # BM_CLICK
                        log("archicad: 'Missing Add-Ons' confirmed (the add-ons' data is kept)")
                    continue
                if cls(h) != "#32770":
                    continue  # Archicad's own windows and palettes
                kids = children(h)
                body = " ".join(t for _, k, t in kids if k == "Static" and t).strip()
                if body and any(k == "Button" for _, k, _t in kids):
                    self.message = (f"The helper Archicad shows a dialog '{title}': {body} - the tool stopped. "
                                    "Read it in that Archicad and close it there.")
                    break


def pid_of_port(port):
    """The process listening on an Archicad JSON port."""
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            return int(parts[4])
    return None


def _answering(port):
    ac = Archicad(port)
    try:
        return ac, ac.project()
    except Exception:
        return None, None


def start(pln, version, minutes=30):
    """A new Archicad `version` with `pln` open: (client, watch)."""
    before = archicad_pids()
    busy = {port for port in PORTS if _answering(port)[1]}  # the Archicads already running
    exe = archicad_exe(version)
    log(f"archicad: starting Archicad {version} on {Path(pln).name} (a separate window; opening takes a while) ...")
    proc = subprocess.Popen([exe, str(pln)], close_fds=True, cwd=tempfile.gettempdir())
    watch = DialogWatch({proc.pid})
    t_end = time.time() + minutes * 60
    while time.time() < t_end:
        time.sleep(5)
        watch.pids |= archicad_pids() - before  # Archicad may hand the project over to a second process
        watch.check()
        for port in PORTS:
            ac, info = _answering(port)
            if info and info["path"] and same_path(info["path"], pln):
                log(f"archicad: {Path(pln).name} open (port {port})")
                return ac, watch
            if info and info["path"] and port not in busy and pid_of_port(port) in watch.pids:  # ours, but not pln
                raise ArchicadError(f"the helper Archicad (port {port}) opened {info['name'] or info['path']} "
                                    f"instead of {Path(pln).name} - Archicad recovered it after a crash. Save it "
                                    "there if it is needed, close that Archicad, and run the tool again.")
    raise ArchicadError(f"Archicad did not open {pln} within {minutes} min")


def open_project(ac, watch, pln):
    """Opens `pln` in the helper Archicad (its current project must be saved: unsaved changes are dropped)."""
    box = {}

    def call():
        try:
            box["r"] = ac.tapir("OpenProject", {"projectFilePath": str(pln)}, timeout=3600)
        except Exception as e:
            box["e"] = e
    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(1.0)
        watch.check()
    if "e" in box:
        raise box["e"]
    if not same_path(ac.project()["path"], pln):
        raise ArchicadError(f"the helper Archicad did not open {pln}")
    log(f"archicad: {Path(pln).name} open")
