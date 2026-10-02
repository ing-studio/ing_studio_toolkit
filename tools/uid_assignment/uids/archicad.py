"""Archicad JSON API client (built-in commands and the Tapir add-on's), and finding the Archicad to work in.

Several Archicad instances can run on one machine, each on its own port 19723-19744. The tool works in exactly one:
the one given by --port (the palette button passes its own), the one that has --project open, or the only solo
project that is open.
"""
import json
import math
import urllib.request

from .util import same_path

PORTS = range(19723, 19745)
HOST = "http://127.0.0.1"


class ArchicadError(RuntimeError):
    pass


class Archicad:
    def __init__(self, port, host=HOST):
        self.port = port
        self.url = f"{host}:{port}"

    def api(self, command, params=None, timeout=600):
        body = {"command": command}
        if params is not None:
            body["parameters"] = params
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError) as e:  # closed, busy past the timeout, or a broken answer
            raise ArchicadError(f"{command}: the Archicad on port {self.port} does not answer ({e})") from e
        if not resp.get("succeeded"):
            raise ArchicadError(f"{command}: {resp.get('error', {}).get('message', resp.get('error'))}")
        return resp.get("result", {})

    def tapir(self, name, params=None, timeout=600):
        p = {"addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name}}
        if params is not None:
            p["addOnCommandParameters"] = params
        res = self.api("API.ExecuteAddOnCommand", p, timeout).get("addOnCommandResponse", {})
        if isinstance(res, dict) and (res.get("success") is False or ("error" in res and len(res) == 1)):
            err = res.get("error")
            raise ArchicadError(f"{name}: {err.get('message', err) if isinstance(err, dict) else err}")
        return res

    def project(self):
        """{'path', 'name', 'teamwork', 'untitled'} of the open project."""
        info = self.tapir("GetProjectInfo", timeout=30)
        return {"path": info.get("projectLocation") or info.get("projectPath") or "",
                "name": info.get("projectName") or "", "teamwork": bool(info.get("isTeamwork")),
                "untitled": bool(info.get("isUntitled"))}

    def version(self):
        return int(self.api("API.GetProductInfo", timeout=10).get("version"))

    def view_rotation(self):
        """The rotation (radians) of the view in front: a plan turned with Set Orientation is shown rotated by it."""
        try:
            t = self.tapir("GetView2DTransformations", {}).get("transformations") or [{}]
            return float(t[0].get("rotation") or 0.0)
        except (ArchicadError, TypeError, ValueError):
            return 0.0

    def level_angle(self):
        """The text angle (radians) that reads level in the view in front. On a turned plan a text at 0 would be
        drawn askew; the tools' own default angles follow the orientation of whatever view was in front, so a text
        must always get its angle explicitly."""
        return round((-self.view_rotation()) % (2 * math.pi), 9) % (2 * math.pi)


def eid(guid):
    return {"elementId": {"guid": guid}}


def scan():
    """Running Archicad instances that answer with Tapir: [(client, project info)]."""
    found = []
    for port in PORTS:
        ac = Archicad(port)
        try:
            ac.api("API.GetProductInfo", timeout=3)
            found.append((ac, ac.project()))
        except Exception:
            continue  # nothing on that port, still starting, or no Tapir
    return found


def connect(port=None, project=None):
    """The Archicad to work in (see the module docstring)."""
    if port:
        ac = Archicad(port)
        try:
            ac.project()
        except Exception as e:
            raise ArchicadError(f"No Archicad with Tapir answers on port {port}: {e}")
        return ac
    instances = scan()
    if project:
        for ac, info in instances:
            if info["path"] and same_path(info["path"], project):
                return ac
        raise ArchicadError(f"{project} is not open in any Archicad: open it first (the tool works in the open "
                            "project)")
    solo = [(ac, info) for ac, info in instances if not info["teamwork"] and not info["untitled"]]
    if len(solo) == 1:
        return solo[0][0]
    listing = "\n".join(f"  --port {ac.port}   {info['name']}{' (Teamwork)' if info['teamwork'] else ''}"
                        for ac, info in instances) or "  (none)"
    raise ArchicadError("Say which Archicad to work in with --port or --project. Open projects:\n" + listing)
