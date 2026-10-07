# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tapir palette button: build the Archicad site model of an AutoCAD site plan with the autocad_to_archicad tool.

The drawing (DWG / DXF), the survey point cloud and, optionally, the project PDFs are picked here; the tool writes
output/<drawing>_FromDWG.pln and its report next to the drawing - a new file, the open project is not touched.
All the logic lives in the tool; this button only starts it (site_model.bat DRAWING POINT_CLOUD [--doc PDF ...]).

Installed into Documents/Tapir/custom-scripts by install.bat (which fills in TOOL_DIR).
"""
import os
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

TOOL_DIR = r"__TOOL_DIR__"
TITLE = "Site model from AutoCAD"
DRAWING_TYPES = [("AutoCAD drawings", "*.dwg *.dxf"), ("All files", "*.*")]
CLOUD_TYPES = [("Point clouds", "*.e57 *.las *.laz *.ply *.pcd *.pts *.ptx *.xyz *.txt *.csv"), ("All files", "*.*")]


def main():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    site_model_bat = Path(TOOL_DIR) / "site_model.bat"
    if not site_model_bat.exists():
        messagebox.showerror(TITLE, f"The autocad_to_archicad tool is not found:\n{site_model_bat}\n\nThe toolkit has "
                                    "moved: run install.bat again in the tool's folder.", parent=root)
        return
    drawing = filedialog.askopenfilename(title="The site plan (DWG or DXF)", filetypes=DRAWING_TYPES, parent=root)
    if not drawing:
        return
    cloud = filedialog.askopenfilename(title="The survey point cloud of the site", filetypes=CLOUD_TYPES,
                                       initialdir=str(Path(drawing).parent), parent=root)
    if not cloud:
        return
    cmd = [str(site_model_bat), drawing, cloud]
    if messagebox.askyesno(TITLE, "Add the project's PDFs?\n\nThey are optional: they add the underground levels "
                                  "and check the floor area.", parent=root):
        pdfs = filedialog.askopenfilenames(title="Project PDFs", filetypes=[("PDF", "*.pdf")],
                                           initialdir=str(Path(drawing).parent), parent=root)
        for pdf in pdfs:
            cmd += ["--doc", pdf]

    # own console window (a small launcher .cmd avoids cmd's quoting rules), so the progress is visible and
    # Archicad stays free; run in the drawing's folder: the results go to its "output" folder
    folder = str(Path(drawing).parent)
    launcher = Path(tempfile.gettempdir()) / "site_model_launch.cmd"
    line = " ".join(f'"{c}"' for c in cmd)
    launcher.write_text(f'@echo off\r\nchcp 65001 >nul\r\ntitle {TITLE}\r\ncd /d "{folder}"\r\n'
                        f"call {line}\r\necho.\r\npause\r\n", encoding="utf-8")
    os.startfile(str(launcher))
    stem = Path(drawing).stem
    messagebox.showinfo(TITLE, "The tool is running in its own window.\n\n"
                               f"Result: output\\{stem}_FromDWG.pln and output\\{stem}_FromDWG_report.html next to "
                               "the drawing.", parent=root)


if __name__ == "__main__":
    main()
