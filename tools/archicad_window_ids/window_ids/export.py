"""The output files, made from the saved project - which itself is never changed:

  output\\<project>_window_ids.pln     the project with the Պ IDs in its windows, plus two layers of the tool:
                                      'Window IDs - Floor Plans' (an ID label on every window) and
                                      'Window Types - Measurements' (the worksheet with the types and their sizes)
  output\\<project>_window_ids.pdf     the plans of the stories with windows, every window tagged with its ID
  output\\<project>_window_types.pln   only the window types: the worksheet on 'Window Types - Measurements';
                                      every other element and layer removed
  output\\<project>_window_types.pdf   that sheet, printed at its scale

Nothing else is left in the folder: Archicad's .bpn backups are removed, the log is %TEMP%\\archicad_window_ids.log.

The work is done in a helper Archicad of the same version, on copies: one started for it, or the one an earlier run
left open with these output files (it is used again rather than refused). Windows on locked or hidden layers get
their IDs too: in the copy those layers are opened for the work and put back as they were.
"""
import shutil
import tempfile
import time
from pathlib import Path

from . import layers, pdf, plans, sheet
from .annotate import annotate
from .archicad import Archicad, ArchicadError, scan
from .ids import write_ids
from .session import DialogWatch, open_project, pid_of_port, start
from .types import assign
from .util import log, same_path, set_log_file, warn, warnings
from .windows import none_found, read_windows, stories

PARTS = ("Segment", "Riser", "Tread", "StairStructure", "CurtainWallFrame", "CurtainWallPanel",
         "CurtainWallJunction", "CurtainWallAccessory")


def outputs(project, out_dir=None):
    stem = Path(project).stem
    out = Path(out_dir).resolve() if out_dir else Path(project).resolve().parent / "output"
    return {"dir": out, "ids": out / f"{stem}_window_ids.pln", "ids_pdf": out / f"{stem}_window_ids.pdf",
            "types": out / f"{stem}_window_types.pln", "types_pdf": out / f"{stem}_window_types.pdf"}


def _helper(o, version, helper_port):
    """(client, watch) of the Archicad to work in, or (None, None) when one is to be started: the given one, else the
    one an earlier run left with an output file open. Any other Archicad with an output file open stops the tool."""
    chosen = None
    if helper_port:
        chosen = Archicad(helper_port)
        if chosen.version() != version:
            raise ArchicadError(f"the Archicad on port {helper_port} is version {chosen.version()}, the project needs "
                                f"{version}")
    for ac, info in scan():
        if not info["path"] or not any(same_path(info["path"], o[k]) for k in ("ids", "types")):
            continue
        if chosen is None and ac.version() == version:
            chosen = ac
            log(f"export: the Archicad on port {ac.port} has {Path(info['path']).name} open from an earlier run - it "
                "does the work again (what was unsaved there is dropped)")
        elif chosen is None or ac.port != chosen.port:
            raise ArchicadError(f"{Path(info['path']).name} is open in the Archicad on port {ac.port}: close it there "
                                "first (it is about to be made anew)")
    if chosen is None:
        return None, None
    return chosen, DialogWatch({pid_of_port(chosen.port)})


def _fresh_copy(src, dst):
    Path(str(dst) + ".lck").unlink(missing_ok=True)  # no Archicad has dst open (checked): a lock left by a crash
    shutil.copyfile(src, dst)


def _clear_model(ac):
    """Deletes every element of the floor plan (parts of stairs, railings and curtain walls go with their owner)."""
    db = plans.floor_plan_db(ac, show=True)
    els = ac.tapir("GetAllElements", {"databases": [{"databaseId": db}]}).get("elements", [])
    kinds = []
    for i in range(0, len(els), 500):
        kinds += ac.tapir("GetDetailsOfElements", {"elements": els[i:i + 500], "fields": ["type"]})["detailsOfElements"]
    drop = [e for e, k in zip(els, kinds) if not any(p in k.get("type", "") for p in PARTS)
            and not (k.get("type", "").startswith("Railing") and k.get("type") != "Railing")]
    try:
        ac.tapir("UnlockElements", {"elements": drop})  # a locked element cannot be deleted
    except ArchicadError:
        pass
    for i in range(0, len(drop), 500):
        part = drop[i:i + 500]
        try:
            ac.tapir("DeleteElements", {"elements": part})
        except ArchicadError:
            for e in part:
                try:
                    ac.tapir("DeleteElements", {"elements": [e]})
                except ArchicadError:
                    pass
    log(f"types file: {len(drop)} element(s) deleted from the floor plan")


def _model_left(ac, seconds=15):
    """How many model elements the open project still has - Archicad lists deleted ones for a few moments more."""
    left = 0
    for _ in range(seconds):
        left = len(ac.api("API.GetAllElements", {}).get("elements", []))  # whatever window is open
        if not left:
            break
        time.sleep(1)
    return left


def export(project, cfg, version, out_dir=None, helper_port=None, renumber=False):
    """Makes the output files of `project` (a saved .pln); returns their paths and the types."""
    project = Path(project).resolve()  # Archicad needs whole paths
    if not project.exists():
        raise ArchicadError(f"{project} not found - save the project first")
    o = outputs(project, out_dir)
    o["dir"].mkdir(parents=True, exist_ok=True)
    set_log_file(Path(tempfile.gettempdir()) / "archicad_window_ids.log")
    log(f"export: {project} -> {o['dir']}")
    ac, watch = _helper(o, version, helper_port)
    if ac and same_path(ac.project()["path"], o["ids"]):  # it lets go of the IDs file: it opens the other one
        _fresh_copy(project, o["types"])
        open_project(ac, watch, o["types"])
    _fresh_copy(project, o["ids"])

    # ---- 1. the copy with the IDs, the ID labels and the worksheet
    if ac:
        open_project(ac, watch, o["ids"])
    else:
        ac, watch = start(o["ids"], version)
    try:
        windows = read_windows(ac, cfg)
        if not windows:
            raise ArchicadError(none_found(ac))
        names = stories(ac)
        plans.floor_plan_db(ac, show=True)  # first: Archicad keeps the layers' visibility per open tab
        with layers.opened(ac, sorted({w.layer for w in windows})):
            for w in windows:
                w.editable = True  # their layers are open now
            types = assign(windows, cfg, renumber)
            for t in types:
                log(f"  {t.label:7s} {t.width * 1000:6.0f} x {t.height * 1000:<6.0f} {len(t.windows):3d} pcs  {t.part}")
            log(f"types: {len(windows)} windows -> {len(types)} types")
            old = {w.guid: w.id for w in windows}
            write_ids(ac, types)
        done = annotate(ac, types, names, cfg)
        ac.tapir("SaveProject", timeout=3600)
        log(f"export: {o['ids'].name} saved")
        pdf.write(o["ids_pdf"], plans.page_svgs(project.stem, names, done["geometry"], done["tags"], types,
                                                done["rotation"]), plans.PAPER)

        # ---- 2. the window types alone
        _fresh_copy(o["ids"], o["types"])
        open_project(ac, watch, o["types"])
        _clear_model(ac)
        _sheet, types_layer = sheet.place(ac, done["drawing"], cfg)
        removed = layers.delete_all_but(ac, {layers.all_layers(ac)[types_layer]["index"]})
        ac.tapir("SaveProject", timeout=3600)
        log(f"export: {o['types'].name} saved (layers removed: {', '.join(removed) or 'none'})")
        left = _model_left(ac)
        if left:
            warn(f"types file: {left} model element(s) could not be deleted from it (locked or in a group?)")
        pdf.write(o["types_pdf"], [sheet.to_svg(done["drawing"], cfg, paper=True)],
                  sheet.paper_size(done["drawing"], cfg))
    except ArchicadError as e:
        raise ArchicadError(f"{e}\n(the unfinished copy is left open in the Archicad on port {ac.port}: close it "
                            "there without saving, or just run again)") from e
    finally:
        watch.stop()
        for p in (o["ids"], o["types"]):
            p.with_suffix(".bpn").unlink(missing_ok=True)  # Archicad's backups of the files just saved
    o.update(changed=sum(1 for w in windows if old[w.guid] != w.id), warnings=warnings(), types_list=types,
             windows=len(windows), port=ac.port, id_layer=done["id_layer"], types_layer=done["types_layer"],
             sheet=done["sheet"])
    return o
