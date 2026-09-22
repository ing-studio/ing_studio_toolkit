# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tapir palette button: build the relief of the open project with the relief pipeline.

One terrain Mesh from the point cloud(s) and the contour layers cut from it are written into
output/<project>_ReliefOnly.pln next to the project - a separate file; the open project is only read, never changed.
All the logic lives in the tool; this button only starts it (relief.bat <this project> [point clouds]).

Installed into Documents/Tapir/custom-scripts by  relief.bat addon install  (which fills in PIPELINE_DIR).
"""
import argparse
import json
import os
import tempfile
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox

PIPELINE_DIR = r"__PIPELINE_DIR__"
CLOUD_TYPES = [("Point clouds", "*.e57 *.las *.laz *.ply *.pcd *.pts *.ptx *.xyz *.txt *.csv"), ("All files", "*.*")]


def project_path(port):
    body = {"command": "API.ExecuteAddOnCommand", "parameters": {
        "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": "GetProjectInfo"}}}
    req = urllib.request.Request(f"http://127.0.0.1:{port}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        info = json.loads(r.read().decode())["result"]["addOnCommandResponse"]
    if info.get("isUntitled"):
        return None, "untitled"
    if info.get("isTeamwork"):
        return None, "teamwork"
    return info.get("projectLocation") or info.get("projectPath"), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19723)
    args, _ = ap.parse_known_args()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    title = "Relief from point cloud"

    relief_bat = Path(PIPELINE_DIR) / "relief.bat"
    if not relief_bat.exists():
        messagebox.showerror(title, f"Relief pipeline not found:\n{relief_bat}\n\nRun  relief.bat addon install  "
                                    "again from the pipeline folder.", parent=root)
        return
    try:
        pln, problem = project_path(args.port)
    except Exception as e:
        messagebox.showerror(title, f"Could not ask Archicad for the project: {e}", parent=root)
        return
    if problem == "untitled" or not pln:
        messagebox.showwarning(title, "Save the project first: the pipeline reads the saved .pln file.", parent=root)
        return
    if problem == "teamwork":
        messagebox.showwarning(title, "Teamwork projects are not supported: save a solo copy (.pln) and open that.",
                               parent=root)
        return
    if pln.lower().endswith("_reliefonly.pln"):
        messagebox.showwarning(title, "This is a relief-only result file. Open the source project and run the "
                                      "button there.", parent=root)
        return

    choice = messagebox.askyesnocancel(
        title,
        f"Project:\n{pln}\n\nThe saved file is used (save now if you changed something).\n\n"
        "Choose point cloud file(s)?\n"
        "  Yes  = pick E57 / LAS / LAZ / PLY / XYZ ... files\n"
        "  No   = use the survey cloud set in the tool's config\\project.json",
        parent=root)
    if choice is None:
        return
    folder = str(Path(pln).parent)
    cmd = [str(relief_bat), pln]
    if choice:
        clouds = filedialog.askopenfilenames(title="Point cloud file(s)", filetypes=CLOUD_TYPES, parent=root)
        if not clouds:
            return
        cmd += list(clouds)
    cmd += ["--notify"]  # run in the project's folder: the results go to its "output" folder

    # own console window (a small launcher .cmd avoids cmd's quoting rules), so the progress is visible and
    # Archicad stays free; the pipeline shows a message when it is done
    launcher = Path(tempfile.gettempdir()) / "relief_pipeline_launch.cmd"
    line = " ".join(f'"{c}"' for c in cmd)
    launcher.write_text(f'@echo off\r\nchcp 65001 >nul\r\ntitle Relief pipeline\r\ncd /d "{folder}"\r\n'
                        f"call {line}\r\necho.\r\npause\r\n", encoding="utf-8")
    os.startfile(str(launcher))
    messagebox.showinfo(title, "The relief pipeline is running in its own window.\n\n"
                               f"Result: output\\{Path(pln).stem}_ReliefOnly.pln next to the project\n"
                               "A message appears when it is finished.", parent=root)


if __name__ == "__main__":
    main()
