"""uid.bat - window types and their IDs (Պ-01, Պ-02 ...) in an Archicad project.

  uid.bat                      in the only open solo project: the IDs into its windows, an ID label on every
                               window on the layer 'Window IDs - Floor Plans', and the worksheet with the types and
                               their measurements on the layer 'Window Types - Measurements'
  uid.bat --port 19726         the same in the project open in that Archicad
  uid.bat --dry-run            show what would change, change nothing
  uid.bat --renumber           number every type afresh (Պ-01 ...), ignoring the IDs already given
  uid.bat --output --project X.pln     the output files of X.pln (its copy with the IDs and both layers, the window
                                       types file, both as PDF) in X's output folder; X itself is not changed
  uid.bat addon install        Tapir and the "Window IDs" button in Archicad's Tapir palette (addon remove: the
                               button away)
"""
import argparse
import sys
import time
from pathlib import Path

from . import layers, plans, report
from .annotate import annotate
from .archicad import ArchicadError, connect
from .ids import write_ids
from .types import assign
from .util import load_config, log, same_path, set_log_file, warn, warnings
from .windows import count, none_found, read_windows, stories


def run(port=None, project=None, dry_run=False, renumber=False, draw=True, config=None):
    """In the open project: the IDs into the windows, the ID labels on 'Window IDs - Floor Plans' and the worksheet on
    'Window Types - Measurements'. Nothing is saved. Returns {'types', 'windows', 'changed', 'report', 'sheet',
    'id_layer', 'types_layer', 'warnings'}."""
    cfg = load_config(config)
    ac = connect(port, project)
    info = ac.project()
    if info["untitled"]:
        raise ArchicadError("Save the project first (the report is written next to it)")
    if info["teamwork"]:
        raise ArchicadError("Teamwork projects are not supported yet: open a solo copy (.pln)")
    out_dir = Path(info["path"]).parent / "output"
    set_log_file(out_dir / f"{Path(info['path']).stem}_windows.log")
    log(f"project: {info['path']} (Archicad on port {ac.port}){' - DRY RUN' if dry_run else ''}")

    windows = read_windows(ac, cfg)
    if not windows:
        raise ArchicadError(none_found(ac))
    names = stories(ac)
    types = assign(windows, cfg, renumber)
    for t in types:
        log(f"  {t.label:7s} {t.width * 1000:6.0f} x {t.height * 1000:<6.0f} {len(t.windows):3d} pcs  {t.part}"
            + (f"  (hand {t.hand})" if t.hand else ""))
    log(f"types: {len(windows)} windows -> {len(types)} types")

    old = {w.guid: w.id for w in windows}
    # a hidden layer is shown for the IDs and hidden again; a locked one is the designer's "do not touch". The floor
    # plan comes to the front first: Archicad keeps the layers' visibility per open tab
    plans.floor_plan_db(ac, show=True)
    states = layers.all_layers(ac)
    hidden = sorted({w.layer for w in windows if not w.editable and states.get(w.layer, {}).get("isHidden")
                     and not states.get(w.layer, {}).get("isLocked")})
    with layers.opened(ac, [] if dry_run else hidden):
        for w in windows:
            if w.layer in hidden:
                w.editable = True
        changed = write_ids(ac, types, dry_run)
    changes = [(w, old[w.guid], t.label) for t in types for w in t.windows
               if old[w.guid] != t.label and (w.id == t.label or (dry_run and w.editable))]

    if dry_run:
        from .sheet import layout
        done = {"drawing": layout(types, names, cfg), "sheet": None, "id_layer": None, "types_layer": None}
    else:
        done = annotate(ac, types, names, cfg, draw)
    _check_schedule(ac, cfg)
    page = report.write(out_dir, info["path"], types, names, changes, done["drawing"], cfg,
                        report.previews(ac, types), warnings(), dry_run)
    return {"types": types, "windows": len(windows), "changed": changed, "report": page, "sheet": done["sheet"],
            "id_layer": done["id_layer"], "types_layer": done["types_layer"], "warnings": warnings()}


def run_export(port=None, project=None, out=None, version=None, helper_port=None, renumber=False, config=None):
    """The output files of the project open at `port` (its saved file), or of the file `project`."""
    from .archicad import Archicad, scan
    from .export import export
    cfg = load_config(config)
    if port:
        ac = Archicad(port)
        info = ac.project()
        if info["untitled"] or info["teamwork"]:
            raise ArchicadError("Save the project as a solo .pln first: the output is made from the saved file")
        if not count(ac):  # say so now, not after copying the file and starting a second Archicad
            raise ArchicadError(none_found(ac))
        project, version = info["path"], version or ac.version()
    elif not project:
        raise ArchicadError("Say which project: --project file.pln (or --port of the Archicad that has it open)")
    if not version:
        open_in = [ac for ac, info in scan() if info["path"] and same_path(info["path"], project)]
        version = open_in[0].version() if open_in else int(cfg.get("archicad_version", 28))
    return export(project, cfg, version, out, helper_port, renumber)


def _check_schedule(ac, cfg):
    """The Interactive Schedule cannot be made through the API: point to the one-time setup when it is missing."""
    name = cfg.get("schedule_name", "Պատուհանների մասնագիր")
    tree = ac.api("API.GetNavigatorItemTree", {"navigatorTreeId": {"type": "ProjectMap"}})
    stack = [tree["navigatorTree"]["rootItem"]]
    while stack:
        it = stack.pop()
        it = it.get("navigatorItem", it)
        if it.get("type") == "ScheduleItem" and it.get("name", "").strip() == name:
            log(f"schedule: '{name}' is in the project - it lists the new IDs by itself")
            return
        stack += it.get("children", [])
    warn(f"schedule: no Interactive Schedule named '{name}' in this project - set it up once as the README says "
         "(Document > Schedules > Scheme Settings); the worksheet has the same table meanwhile")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="uid.bat", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("addon", nargs="*", help=argparse.SUPPRESS)
    ap.add_argument("--port", type=int, help="the Archicad to work in (19723-19744)")
    ap.add_argument("--project", help="the .pln whose Archicad to work in (it must be open)")
    ap.add_argument("--dry-run", action="store_true", help="change nothing, write only the report")
    ap.add_argument("--renumber", action="store_true", help="number all types afresh")
    ap.add_argument("--no-sheet", action="store_true", help="do not draw the worksheet")
    ap.add_argument("--config", help="a JSON file with settings over config/default.json")
    ap.add_argument("--output", action="store_true", help="make the output files instead of changing the project")
    ap.add_argument("--out", help="folder of the output files (default: 'output' next to the project)")
    ap.add_argument("--archicad", type=int, help="Archicad version of the helper (default: that of the open project)")
    ap.add_argument("--helper-port", type=int, help="use this already running Archicad as the helper")
    a = ap.parse_args(argv)
    if a.addon:
        from .addon import install
        if a.addon[0] != "addon" or len(a.addon) > 2 or (a.addon[1:] or ["install"])[0] not in ("install", "remove"):
            ap.error("unknown command: " + " ".join(a.addon))
        try:
            install(remove=(a.addon[1:] or ["install"])[0] == "remove")
        except (ArchicadError, OSError) as e:  # no network, registry refused ...
            log(f"addon: not installed: {e}", "FAIL")
            return 1
        return 0
    t0 = time.time()
    if a.output:
        try:
            o = run_export(a.port, a.project, a.out, a.archicad, a.helper_port, a.renumber, a.config)
        except ArchicadError as e:
            log(str(e), "FAIL")
            return 1
        log(f"done in {time.time() - t0:.0f}s: {o['windows']} windows, {len(o['types_list'])} types -> {o['dir']}")
        return 0
    try:
        res = run(a.port, a.project, a.dry_run, a.renumber, not a.no_sheet, a.config)
    except ArchicadError as e:
        log(str(e), "FAIL")
        return 1
    log(f"done in {time.time() - t0:.0f}s: {res['windows']} windows, {len(res['types'])} types, "
        f"{res['changed']} ID(s) {'to change' if a.dry_run else 'changed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
