"""Archicad JSON API client with the Tapir add-on commands, and the safety stop.

Safety stop: while the pipeline uses an Archicad instance, its dialogs are watched. Archicad's "invalid elements were
fixed" note is confirmed; any other message dialog (for example "older version of an add-on than this project")
stops the pipeline at once. Nothing is saved after that; the dialog is left for the user to read.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from ..util import error, log

SUPPORTED_VERSIONS = (28, 29)
_version = [28]  # until use_version: the version every tool of the toolkit was written for
PORTS = range(19723, 19745)


def installed_versions():
    """The supported Archicad versions installed on this machine."""
    import glob
    return [v for v in SUPPORTED_VERSIONS if glob.glob(rf"C:\Program Files\GRAPHISOFT\Archicad {v}*\Archicad.exe")]


def use_version(setting):
    """The Archicad version the pipeline works with: archicad.version (28 | 29), or auto = the newest installed;
    28 when the tool's settings name none. Only that version's instances are used, and the PLN is saved in it."""
    if setting in (None, "auto"):
        found = installed_versions()
        v = found[-1] if found else SUPPORTED_VERSIONS[-1]
    else:
        v = int(setting)
        if v not in SUPPORTED_VERSIONS:
            raise ArchicadError(f"archicad.version {setting!r}: supported are {', '.join(map(str, SUPPORTED_VERSIONS))}")
    _version[0] = v
    return v


def version():
    return _version[0]


TAPIR_COMMANDS = ("GetProjectInfo", "SaveProject", "GetAddOnVersion", "GetStories", "CreateLayers",
                  "GetAttributesByType", "GetElementsByType", "GetDetailsOfElements", "SetDetailsOfElements",
                  "DeleteElements", "ChangeWindow", "CreateMeshes", "CreateSplines", "CreatePolylines", "CreateMorphs")


class ArchicadError(RuntimeError):
    pass


class SafetyStop(RuntimeError):
    """Archicad showed an unexpected dialog; the pipeline must not continue or save."""


# --------------------------------------------------------------------------- dialog watch (safety stop)
class DialogWatch:
    ALERT_BUTTONS = {"OK", "Yes", "No", "Cancel", "Save", "Don't Save", "Don’t Save", "Close", "Continue",
                     "Retry", "Ignore", "Discard"}
    INVALID_ELEMENTS = "invalid elements were found"
    # windows Archicad draws itself: not '#32770', so they have no readable message and no buttons to answer, but
    # they do block startup completely. 'Project Recovery' appears after Archicad was killed instead of quitting.
    BLOCKING_TITLES = ("project recovery",)
    # Archicad's own note that a file (a hotlinked module) carries data of add-ons not loaded here: its OK keeps that
    # data, which is what the pipeline wants; it asks nothing else
    KEEP_DATA_TITLES = ("missing add-ons",)

    def __init__(self, pid, report_dir=None):
        self.pid, self.report_dir = pid, report_dir
        self.message = None
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def tripped(self):
        return self.message is not None

    def check(self):
        if self.tripped:
            raise SafetyStop(self.message)

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

        while not self._stop.wait(1.0) and not self.tripped:
            tops = []
            user32.EnumWindows(proto(lambda h, _: tops.append(h) or True), 0)
            for h in tops:
                if owner(h) != self.pid or not user32.IsWindowVisible(h):
                    continue
                if cls(h) != "#32770":
                    title = text(h)
                    if title.lower() in self.KEEP_DATA_TITLES:
                        kids = []
                        user32.EnumChildWindows(h, proto(lambda c, _: kids.append((c, cls(c), text(c))) or True), 0)
                        ok_button = [c for c, k, t in kids if k == "Button" and t.replace("&", "") == "OK"]
                        if ok_button:
                            user32.SendMessageW(ok_button[0], 0x00F5, 0, 0)  # BM_CLICK: the data is kept
                            log(f"archicad: '{title}' (a linked file's add-on data): confirmed, the data is kept")
                        continue
                    if not any(k in title.lower() for k in self.BLOCKING_TITLES):
                        continue
                    self.message = (f"Archicad (pid {self.pid}) is waiting in its '{title}' window -> pipeline "
                                    "stopped, nothing was saved. Answer it in Archicad. It appears when an Archicad "
                                    "was killed instead of quitting; deleting the leftover session folders of "
                                    "instances that are NOT running (%LOCALAPPDATA%\\Graphisoft\\Archicad__*) "
                                    "stops it coming back.")
                    error(f"archicad: SAFETY STOP - {self.message}")
                    break
                kids = []
                user32.EnumChildWindows(h, proto(lambda c, _: kids.append((c, cls(c), text(c))) or True), 0)
                buttons = {t.replace("&", ""): c for c, k, t in kids if k == "Button" and t}
                body = " ".join(t for _, k, t in kids if k == "Static" and t).strip()
                if not body or not (set(buttons) & self.ALERT_BUTTONS):
                    continue  # progress windows and the like
                if self.INVALID_ELEMENTS in body.lower() and "OK" in buttons:
                    user32.SendMessageW(buttons["OK"], 0x00F5, 0, 0)  # BM_CLICK
                    self._keep_invalid_elements_report()
                    log("archicad: Archicad repaired invalid elements on open; note confirmed")
                    continue
                self.message = (f"Archicad (pid {self.pid}) shows a dialog '{text(h)}': {body}  -> pipeline stopped, "
                                "nothing was saved. Read the dialog in Archicad and close that project WITHOUT saving.")
                error(f"archicad: SAFETY STOP - {self.message}")
                break

    def _keep_invalid_elements_report(self):
        report = Path(os.environ.get("TEMP", "")) / "NewElementCheckResultDetailedInfo.xml"
        time.sleep(1)
        if self.report_dir and report.exists():
            shutil.copyfile(report, Path(self.report_dir) / "archicad_invalid_elements.xml")


# --------------------------------------------------------------------------- client
class Archicad:
    def __init__(self, host, port, watch=None):
        self.url = f"{host}:{port}"
        self.port = port
        self.watch = watch

    def api(self, command, params=None, timeout=900):
        if self.watch:
            self.watch.check()
        body = {"command": command}
        if params is not None:
            body["parameters"] = params
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        box = {}

        def call():
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    box["resp"] = json.loads(r.read().decode("utf-8"))
            except Exception as e:  # handed to the caller below
                box["error"] = e

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        while worker.is_alive():
            worker.join(0.5)
            if self.watch:
                self.watch.check()  # a modal dialog blocks the API: stop instead of waiting for the timeout
        if "error" in box:
            raise box["error"]
        resp = box["resp"]
        if not resp.get("succeeded"):
            raise ArchicadError(f"{command}: {resp.get('error')}")
        return resp.get("result", {})

    def tapir(self, name, params=None, timeout=900):
        p = {"addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name}}
        if params is not None:
            p["addOnCommandParameters"] = params
        res = self.api("API.ExecuteAddOnCommand", p, timeout).get("addOnCommandResponse", {})
        if isinstance(res, dict) and (res.get("success") is False or ("error" in res and len(res) == 1)):
            raise ArchicadError(f"{name}: {res.get('error')}")
        return res

    def project_location(self):
        info = self.tapir("GetProjectInfo", timeout=30)
        return info.get("projectLocation") or info.get("projectPath") or "", bool(info.get("isTeamwork"))

    def missing_tapir_commands(self, commands=TAPIR_COMMANDS):
        return [c for c in commands if not self.api("API.IsAddOnCommandAvailable", {
            "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": c}}, timeout=30).get("available")]


def eid(guid):
    return {"elementId": {"guid": guid}}


def archicad_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Archicad.exe", "/NH"], capture_output=True, text=True).stdout
    return "archicad.exe" in out.lower()
