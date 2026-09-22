"""Command line of the relief tool (relief.bat).

  relief.bat FILES [options]      build the relief (same as: relief.bat run FILES ...)
  relief.bat stages               list the stages
  relief.bat config [options]     print the effective settings
  relief.bat addon install|remove|status   the Archicad add-on (Tapir + palette button)
"""
import argparse
import json
import sys

from . import __version__
from .config import ConfigError, load_config

COMMANDS = ("run", "stages", "config", "addon")

RUN_HELP = """\
FILES: point cloud file(s) and/or Archicad project(s), in any order.
  survey.e57                   a new PLN is made from the point cloud
  project.pln survey.e57       the relief is placed like the point cloud in that project (never changed)
  project.pln                  uses the point cloud set in config/project.json (paths.source_cloud)
Several point clouds are merged into one relief.
Point clouds: E57 LAS LAZ PLY PCD PTS PTX XYZ TXT CSV ASC NEU.

Result, in the current folder (or --out):
  <name>_ReliefOnly.pln            one terrain mesh + one contour layer per --contours size
  <name>_ReliefOnly_contours.dxf   the same contours as 3D lines

Examples:
  relief.bat survey.e57
  relief.bat project.pln survey.e57 --out D:\\results
  relief.bat survey.e57 --contours 0.5 1 5 --mesh-points 80000
  relief.bat survey.e57 --only contours --force
"""

# (flag, config key, type, metavar, help, nargs) - the settings worth a flag; any other one via --set
RELIEF_PARAMS = (
    ("--contours", "contours.cut_sizes_m", float, "M", "contour intervals in metres, one layer each (default 1 3 5)", "+"),
    ("--mesh-points", "mesh.target_points", int, "N", "max. number of mesh points: lighter or finer mesh (default 50000)", None),
)
SMOOTHING_PARAMS = (
    ("--reduce", "contours.smoothing.reduce_tolerance_m", float, "M", "Reduce tolerance before the curve (default 0)", None),
    ("--min-length", "contours.smoothing.min_length_m", float, "M", "drop lines up to this length (default 10)", None),
    ("--degree", "contours.smoothing.nurbs_degree", int, "N", "curve degree (default 3)", None),
    ("--simplify", "contours.smoothing.simplify_tolerance_m", float, "M", "Simplify tolerance (default 0.5)", None),
)
PLACEMENT_PARAMS = (
    ("--placement", "placement.mode", str, "MODE",
     "with a .pln: auto (default) = like the point cloud object in it, else by coordinates | object | coordinates",
     None),
    ("--floor", "placement.floor_index", int, "N", "story index for coordinates placement (default 0)", None),
)
PARAMS = RELIEF_PARAMS + SMOOTHING_PARAMS + PLACEMENT_PARAMS


def _add_params(group, params):
    for flag, _, typ, meta, text, nargs in params:
        group.add_argument(flag, type=typ, metavar=meta, nargs=nargs, help=text)


def _origin(text):
    if text in ("auto", "keep"):
        return text
    try:
        x, y = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("auto, keep or X,Y")
    return [x, y]


def _settings_args(p):
    """The flags that change settings: shared by run and config (which shows their effect)."""
    g = p.add_argument_group("output")
    g.add_argument("--out", metavar="DIR", help="folder for the results (default: the current folder)")
    g.add_argument("--no-3d", action="store_true", help="contours in plan only, no 3D ribbons")
    _add_params(p.add_argument_group("relief"), RELIEF_PARAMS)
    _add_params(p.add_argument_group("contour smoothing (Reduce -> drop short -> curve -> Simplify)"),
                SMOOTHING_PARAMS)
    g = p.add_argument_group("placement")
    _add_params(g, PLACEMENT_PARAMS)
    g.add_argument("--origin", type=_origin, metavar="auto|keep|X,Y",
                   help="new PLN only: auto (default) = origin moved near a far-away cloud | keep = the cloud's own "
                        "coordinates | X,Y = this point becomes the origin")
    g = p.add_argument_group("settings files")
    g.add_argument("--config", action="append", default=[], metavar="FILE",
                   help="extra JSON settings merged over config/default.json and config/project.json (repeatable)")
    g.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="any setting of config/default.json, e.g. --set dem.resolution=0.25 (repeatable)")
    g.add_argument("--no-project-config", action="store_true", help="ignore config/project.json")


def _parser():
    from .pipeline import STAGE_NAMES
    ap = argparse.ArgumentParser(prog="relief.bat", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"relief {__version__}")
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")

    run = sub.add_parser("run", help="build the relief (the default command)", usage="relief.bat FILES [options]",
                         description="Point cloud -> Archicad terrain mesh + contour layers.",
                         epilog=RUN_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    run.add_argument("files", nargs="+", metavar="FILES", help="point cloud(s) and/or .pln project(s)")
    _settings_args(run)
    g = run.add_argument_group("run control (results are cached; unchanged steps are skipped)")
    g.add_argument("--only", choices=STAGE_NAMES, metavar="STAGE", help="run one stage (see: relief.bat stages)")
    g.add_argument("--from", dest="start", choices=STAGE_NAMES, metavar="STAGE", help="start at this stage")
    g.add_argument("--until", choices=STAGE_NAMES, metavar="STAGE", help="stop after this stage")
    g.add_argument("--force", action="store_true", help="redo the selected stages even if cached")
    g.add_argument("--work", metavar="DIR", help="cache folder (default: %%LOCALAPPDATA%%\\ing_studio_toolkit\\...)")
    g.add_argument("--notify", action="store_true", help="show a message when finished (used by the palette button)")

    sub.add_parser("stages", help="list the stages")
    cfg = sub.add_parser("config", help="print the effective settings")
    _settings_args(cfg)

    addon = sub.add_parser("addon", help="the Archicad add-on: Tapir + palette button")
    addon.add_argument("action", choices=["install", "remove", "status"])
    addon.add_argument("--palette-only", action="store_true",
                       help="only the palette button (Tapir already installed, or Archicad is running)")
    return ap


def _overrides(args):
    out = list(args.set)
    for flag, key, *_ in PARAMS:
        value = getattr(args, flag.lstrip("-").replace("-", "_"), None)
        if value is not None:
            out.append((key.split("."), value))
    for attr, key, value in (("no_3d", "archicad.contours_3d", False), ("origin", "placement.new_pln_origin", None),
                             ("out", "paths.output_dir", None), ("work", "paths.work_dir", None)):
        given = getattr(args, attr, None)
        if given:
            out.append((key.split("."), given if value is None else value))
    return out


def _notify(code, log_path, results):
    import ctypes
    if code == 0:
        text, icon = "Relief finished.\n\n" + "\n".join(results), 0x40
    else:
        text, icon = f"Relief FAILED - nothing unsafe was saved.\n\nSee the log:\n{log_path}", 0x10
    ctypes.windll.user32.MessageBoxW(None, text, "Relief", icon | 0x40000)  # topmost


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version"):
        argv.insert(0, "run")  # relief.bat FILES ... = relief.bat run FILES ...
    args = _parser().parse_args(argv)
    try:
        if args.command == "stages":
            from .pipeline import STAGES
            for s in STAGES:
                print(f"{s.name:10s} per {s.scope:5s}  {s.help}")
            return 0
        if args.command == "addon":
            from .archicad import addon
            if args.action == "status":
                print(json.dumps(addon.status(), indent=2))
            else:
                addon.install(remove=args.action == "remove", palette_only=args.palette_only)
            return 0
        cfg = load_config(args.config, _overrides(args), use_project=not args.no_project_config)
        if args.command == "config":
            print(json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")}, indent=2, ensure_ascii=False))
            return 0
    except ConfigError as e:
        print(f"settings error: {e}", file=sys.stderr)
        return 2

    from . import pipeline
    from .job import Job, sort_inputs
    clouds, plns = sort_inputs(cfg, args.files)
    code, log_path = pipeline.run(cfg, clouds, plns, pipeline.select(args.only, args.start, args.until), args.force)
    if args.notify:
        _notify(code, log_path, [Job(cfg, clouds, p).output_pln for p in plns or [None]])
    return code
