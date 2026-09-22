"""Command line: relief.bat <command> [options]   (or: python -m relief ...)

  run      build the relief-only PLN for a project and point cloud(s)
  stages   list the stages
  config   print the effective configuration (after project.json, --config and overrides)
  addon    install / remove / show the Archicad add-on (Tapir + palette button)
"""
import argparse
import json
import sys

from . import __version__
from .config import ConfigError, load_config

# command line flag -> config key (dotted); the most used settings, everything else via --set
PARAMS = (
    ("--mesh-points", "mesh.target_points", int, "N", "max. number of mesh points (lighter / denser mesh)"),
    ("--cut", "contours.cut_sizes_m", float, "M", "contour cut sizes in metres, one layer each, e.g. --cut 1 2 5"),
    ("--reduce", "contours.smoothing.reduce_tolerance_m", float, "M", "Reduce tolerance before the NURBS"),
    ("--min-length", "contours.smoothing.min_length_m", float, "M", "lines not longer than this are left out"),
    ("--degree", "contours.smoothing.nurbs_degree", int, "N", "NURBS degree"),
    ("--simplify", "contours.smoothing.simplify_tolerance_m", float, "M", "Simplify tolerance of the splines"),
    ("--placement", "placement.mode", str, "MODE", "auto | object | coordinates"),
    ("--floor", "placement.floor_index", int, "N", "story index for coordinates placement"),
)


def _parser():
    ap = argparse.ArgumentParser(prog="relief", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"relief pipeline {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    def config_args(p):
        g = p.add_argument_group("configuration")
        g.add_argument("--config", action="append", default=[], metavar="FILE",
                       help="extra JSON config merged over config/default.json and config/project.json (repeatable)")
        g.add_argument("--no-project-config", action="store_true", help="ignore config/project.json")
        g.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                       help="set any config value, e.g. --set mesh.target_points=40000 (value is JSON; repeatable)")
        for flag, key, typ, meta, text in PARAMS:
            g.add_argument(flag, type=typ, metavar=meta, nargs="+" if flag == "--cut" else None,
                           help=f"{text} [{key}]")
        g.add_argument("--no-3d", action="store_true", help="plan contours only, no 3D ribbons [archicad.contours_3d]")
        g.add_argument("--out", metavar="DIR", help="output folder [paths.output_dir]")
        g.add_argument("--work", metavar="DIR", help="work (cache) folder [paths.work_dir]")

    from .pipeline import STAGE_NAMES
    run = sub.add_parser("run", help="build the relief-only PLN", formatter_class=argparse.RawDescriptionHelpFormatter,
                         description="Point cloud(s) + source PLN -> output/<source>_ReliefOnly.pln (+ contours DXF).\n"
                                     "Without --pln / --cloud the input folder is used (and paths.source_cloud).")
    run.add_argument("--pln", nargs="+", metavar="FILE", help="source Archicad project(s) (read only, never saved)")
    run.add_argument("--cloud", nargs="+", metavar="FILE",
                     help="point cloud file(s): E57 LAS LAZ PLY PCD PTS PTX XYZ TXT CSV; several are merged")
    g = run.add_argument_group("stages")
    g.add_argument("--stage", choices=STAGE_NAMES, help="run only this stage")
    g.add_argument("--from", dest="start", choices=STAGE_NAMES, help="start at this stage")
    g.add_argument("--until", choices=STAGE_NAMES, help="stop after this stage")
    g.add_argument("--force", action="store_true", help="re-run the selected stages even if their results exist")
    run.add_argument("--notify", action="store_true", help="show a message box when finished (palette button)")
    config_args(run)

    sub.add_parser("stages", help="list the stages")
    cfg = sub.add_parser("config", help="print the effective configuration")
    config_args(cfg)

    addon = sub.add_parser("addon", help="Archicad add-on: Tapir + palette button")
    addon.add_argument("action", choices=["install", "remove", "status"])
    addon.add_argument("--palette-only", action="store_true",
                       help="only the palette button (Tapir already installed, or Archicad is running)")
    return ap


def _overrides(args):
    out = list(args.set)
    for flag, key, _, _, _ in PARAMS:
        value = getattr(args, flag.lstrip("-").replace("-", "_"))
        if value is not None:
            out.append((key.split("."), value))
    if args.no_3d:
        out.append((["archicad", "contours_3d"], False))
    if args.out:
        out.append((["paths", "output_dir"], args.out))
    if args.work:
        out.append((["paths", "work_dir"], args.work))
    return out


def _config(args):
    return load_config(args.config, _overrides(args), use_project=not args.no_project_config)


def _notify(code, log_path):
    import ctypes
    if code == 0:
        text, icon = "Relief pipeline finished.\n\nResult: the output folder (<project>_ReliefOnly.pln)", 0x40
    else:
        text, icon = f"Relief pipeline FAILED - nothing unsafe was saved.\n\nSee the log:\n{log_path}", 0x10
    ctypes.windll.user32.MessageBoxW(None, text, "Relief pipeline", icon | 0x40000)  # topmost


def main(argv=None):
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
        cfg = _config(args)
        if args.command == "config":
            print(json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")}, indent=2, ensure_ascii=False))
            return 0
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    from . import pipeline
    from .job import discover_inputs
    clouds, plns = discover_inputs(cfg, args.cloud, args.pln)
    code, log_path = pipeline.run(cfg, clouds, plns, pipeline.select(args.stage, args.start, args.until), args.force)
    if args.notify:
        _notify(code, log_path)
    return code
