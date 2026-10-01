# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Tapir palette button: window types and their IDs (Պ-01, Պ-02, ...) of the open project.

  In this project  the IDs go into the open project's windows; two layers of the tool are added (or redone):
                   'Window IDs - Floor Plans' with an ID label on every window, and 'Window Types - Measurements'
                   with the worksheet of the types, their dimensions and the table. Nothing is saved.
  Output files     the same on a copy of the saved project, in its "output" folder, plus a file with only the window
                   types and both as PDF - the open project is not changed; a helper Archicad does the work

All the logic lives in the tool; this button only runs it for the Archicad it was clicked in (Tapir passes --port).
Installed into Documents/Tapir/custom-scripts by addon\\install.bat or addon\\install.ps1 (which fill in TOOL_DIR).
"""
import argparse
import os
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox

TOOL_DIR = r"__TOOL_DIR__"
TITLE = "Window IDs  (Պ)"
INTRO = (
    "Window types and IDs (Պ-01, Պ-02 ...) of the open project.\n\n"
    "In this project: the IDs go into the windows, and two layers are added\n"
    "   (or redone on the next run):\n"
    "     •  Window IDs - Floor Plans: an ID label on every window\n"
    "     •  Window Types - Measurements: the worksheet of the types,\n"
    "        their dimensions and the table\n"
    "   Nothing is saved: check, then save.\n\n"
    "Output files: the same on a copy of the saved project, plus a file with only\n"
    "   the window types and both as PDF, in the project's 'output' folder.\n"
    "   The open project is not changed - save it first. A helper Archicad\n"
    "   opens for the work and stays open with the result.")


def ask(root):
    """'here', 'output' or None."""
    box = tk.Toplevel(root)
    box.title(TITLE)
    box.attributes("-topmost", True)
    box.resizable(False, False)
    choice = {"v": None}
    tk.Label(box, justify="left", padx=16, pady=12, text=INTRO).pack()
    row = tk.Frame(box, pady=10)
    row.pack()
    for text, value in (("In this project", "here"), ("Output files", "output"), ("Cancel", None)):
        tk.Button(row, text=text, width=14, command=lambda v=value: (choice.update(v=v), box.destroy())).pack(
            side="left", padx=6)
    box.protocol("WM_DELETE_WINDOW", box.destroy)
    root.wait_window(box)
    return choice["v"]


def working(root, job):
    """Runs job() while a small window shows the tool's latest message; returns its result or raises its error."""
    from uids import util
    box = tk.Toplevel(root)
    box.title(TITLE)
    box.attributes("-topmost", True)
    label = tk.Label(box, width=90, anchor="w", justify="left", padx=14, pady=14, text="Starting ...")
    label.pack()
    out = {}
    worker = threading.Thread(target=lambda: out.update(r=_catch(job)), daemon=True)
    worker.start()

    def tick():
        if worker.is_alive():
            if util._lines:
                label.config(text="Working ...\n\n" + util._lines[-1][1][:160])
            box.after(500, tick)
        else:
            box.destroy()
    box.after(200, tick)  # from inside the wait: a job that ends at once must not close the box before it
    root.wait_window(box)
    worker.join()
    result, error = out["r"]
    if error:
        raise error
    return result


def _catch(job):
    try:
        return job(), None
    except Exception as e:
        return None, e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19723)
    args, _ = ap.parse_known_args()
    root = tk.Tk()
    root.withdraw()

    if not (Path(TOOL_DIR) / "uids" / "cli.py").exists():
        messagebox.showerror(TITLE, f"The tool is not found:\n{TOOL_DIR}\n\nRun addon\\install.bat (or install.ps1) "
                                    "again from the tool's folder.", parent=root)
        return
    sys.path.insert(0, TOOL_DIR)
    from uids.archicad import ArchicadError
    from uids.cli import run, run_export

    choice = ask(root)
    if choice is None:
        return
    try:
        job = run_export if choice == "output" else run
        res = working(root, lambda: job(port=args.port))
    except ArchicadError as e:
        messagebox.showerror(TITLE, str(e), parent=root)
        return
    except Exception as e:  # anything unexpected: say it rather than vanish
        messagebox.showerror(TITLE, f"The tool stopped: {type(e).__name__}: {e}", parent=root)
        return

    types = res["types_list"] if choice == "output" else res["types"]
    lines = [f"{res['windows']} windows  ->  {len(types)} types", f"{res['changed']} ID(s) changed", "",
             f"Layer '{res['id_layer']}': the ID labels on the plans"]
    if res.get("types_layer"):
        lines.append(f"Layer '{res['types_layer']}': worksheet {res['sheet']}")
    if choice == "output":
        lines += ["", f"In {res['dir']}:"] + [f"  {Path(res[k]).name}"
                                              for k in ("ids", "ids_pdf", "types", "types_pdf")]
    if res["warnings"]:
        lines += ["", "Note:"] + [f"- {w.split(': ', 1)[-1]}" for w in res["warnings"]]
    if choice == "output":
        if messagebox.askyesno(TITLE, "\n".join(lines + ["", "Open the folder?"]), parent=root):
            os.startfile(str(res["dir"]))
    elif messagebox.askyesno(TITLE, "\n".join(lines + ["", "Open the report?"]), parent=root) and res["report"]:
        webbrowser.open(Path(res["report"]).as_uri())


if __name__ == "__main__":
    main()
