"""Command line of the AutoCAD -> Archicad site tool (dwg2ac.bat).

  dwg2ac.bat DRAWING POINT_CLOUD [options]     build the site model (same as: dwg2ac.bat run ...)
  dwg2ac.bat clean DRAWING [--out DIR]         delete that drawing's results and cached steps (a fresh start)
  dwg2ac.bat stages                            list the stages
  dwg2ac.bat config [options]                  print the effective settings
  dwg2ac.bat addon install|remove|status       the Archicad add-on (Tapir), shared with the relief tool
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import UNITS, ConfigError, load_config

COMMANDS = ("run", "clean", "stages", "config", "addon")

RUN_HELP = """DRAWING: the site plan, .dwg or .dxf (a DWG is read through AutoCAD's console; AutoCAD must be installed).
POINT_CLOUD: the survey point cloud of the site (E57, LAS, ...); its terrain becomes the Archicad mesh.
  (It may instead be set once in paths.point_cloud of config/project.json.)
Everything else is worked out: where the site is (the input names looked up on the map, checked by matching the
drawing's buildings to OpenStreetMap), what each layer holds, the heights, the storeys of the new buildings. Project
PDFs (--doc) are optional: they add the underground levels and check the floor area.

Result, in an "output" folder where the command is run (or in --out DIR):
  <drawing>_FromDWG.pln            terrain mesh, existing and new streets, walls, buildings, trees, underground
                                   levels (with --doc), the drawing in 2D
  <drawing>_FromDWG_report.html    placement, layers found, rules applied, street profiles, cut and fill, buildings,
                                   what the project PDFs say, the norms to keep in mind

Examples:
  dwg2ac.bat plan.dwg survey.e57
  dwg2ac.bat plan.dwg survey.e57 --doc areas.pdf
  dwg2ac.bat plan.dwg survey.e57 --lonlat 44.515,40.192
  dwg2ac.bat plan.dwg survey.e57 --only roads --force
  dwg2ac.bat clean plan.dwg                    (then the next run redoes everything)
  dwg2ac.bat plan.dwg survey.e57 --street-class district --set roads.earthworks.max_daylight_m=40
"""


def _lonlat(text):
    try:
        lon, lat = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("LON,LAT")
    return [lon, lat]


def _settings_args(p):
    g = p.add_argument_group("site and drawing")
    g.add_argument("--lonlat", type=_lonlat, metavar="LON,LAT", help="a point near the site, when the input names "
                                                                      "do not lead to it (site.lonlat; default: auto)")
    g.add_argument("--units", choices=["auto"] + list(UNITS), help="what one drawing unit is (default: auto)")
    g.add_argument("--street-class", metavar="CLASS", help="class of the new streets: district, local, driveway "
                                                            "(default: local)")
    g.add_argument("--doc", action="append", metavar="PDF", help="optional: a project PDF read as data (programme "
                                                                 "tables, level plans); repeatable (documents.files)")
    g.add_argument("--no-2d", action="store_true", help="do not copy the drawing's 2D elements into the PLN")
    g.add_argument("--out", metavar="DIR", help="folder for the results (default: output, in the current folder)")
    g = p.add_argument_group("settings files")
    g.add_argument("--config", action="append", default=[], metavar="FILE",
                   help="extra JSON settings merged over config/default.json and config/project.json (repeatable)")
    g.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="any setting of config/default.json, e.g. --set roads.profile.crest_radius_m=2000")
    g.add_argument("--no-project-config", action="store_true", help="ignore config/project.json")


def _parser():
    from .pipeline import STAGE_NAMES
    ap = argparse.ArgumentParser(prog="dwg2ac.bat", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"autocad_to_archicad {__version__}")
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")
    run = sub.add_parser("run", help="build the site model (the default command)",
                         usage="dwg2ac.bat DRAWING POINT_CLOUD [options]",
                         description="AutoCAD site plan + point cloud -> Archicad site model.",
                         epilog=RUN_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    run.add_argument("drawing", metavar="DRAWING", help=".dwg or .dxf")
    run.add_argument("cloud", nargs="?", metavar="POINT_CLOUD", help="survey point cloud of the site (needed; or "
                                                                      "paths.point_cloud)")
    _settings_args(run)
    g = run.add_argument_group("run control (results are cached; unchanged steps are skipped)")
    g.add_argument("--only", choices=STAGE_NAMES, metavar="STAGE", help="run one stage (see: dwg2ac.bat stages)")
    g.add_argument("--from", dest="start", choices=STAGE_NAMES, metavar="STAGE", help="start at this stage")
    g.add_argument("--until", choices=STAGE_NAMES, metavar="STAGE", help="stop after this stage")
    g.add_argument("--force", action="store_true", help="redo the stages even if their results are cached")
    g.add_argument("--cache", metavar="DIR", help="folder for intermediate files")
    clean = sub.add_parser("clean", help="delete a drawing's results and cached steps (the next run starts afresh)",
                           usage="dwg2ac.bat clean DRAWING [--out DIR] [--cache DIR]")
    clean.add_argument("drawing", metavar="DRAWING", help=".dwg or .dxf whose results go")
    clean.add_argument("--out", metavar="DIR", help="its results folder (default: output, in the current folder)")
    clean.add_argument("--cache", metavar="DIR", help="its cache folder, if not the default")
    sub.add_parser("stages", help="list the stages")
    cfg = sub.add_parser("config", help="print the effective settings")
    _settings_args(cfg)
    addon = sub.add_parser("addon", help="the Archicad add-on Tapir (the same one the relief tool uses)")
    addon.add_argument("action", choices=["install", "remove", "status"])
    return ap


def _overrides(args):
    out = list(getattr(args, "set", None) or [])
    for attr, key in (("lonlat", "site.lonlat"), ("units", "drawing.units"), ("street_class", "roads.proposed.class"),
                      ("out", "paths.output_dir"), ("cache", "paths.work_dir")):
        value = getattr(args, attr, None)
        if value is not None:
            out.append((key.split("."), value))
    if getattr(args, "no_2d", False):
        out.append((["archicad", "two_d"], False))
    if getattr(args, "doc", None):
        out.append((["documents", "files"], list(args.doc)))
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version"):
        argv.insert(0, "run")
    args = _parser().parse_args(argv)
    try:
        if args.command == "stages":
            from .pipeline import STAGES
            for s in STAGES:
                print(f"{s.name:11s} {s.help}")
            return 0
        if args.command == "addon":
            from .archicad import addon
            from .archicad.client import use_version
            use_version(load_config()["archicad"]["version"])
            if args.action == "status":
                print(json.dumps(addon.status(), indent=2))
            else:
                addon.register_tapir(remove=args.action == "remove")
            return 0
        cfg = load_config(getattr(args, "config", None) or [], _overrides(args),
                          use_project=not getattr(args, "no_project_config", False))
        if args.command == "clean":
            return clean(cfg, args.drawing)
        if args.command == "config":
            print(json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")}, indent=2, ensure_ascii=False))
            return 0
    except ConfigError as e:
        print(f"settings error: {e}", file=sys.stderr)
        return 2

    from . import pipeline
    from .job import Job, check_input
    drawing, cloud = check_input(cfg, args.drawing, args.cloud)
    code, _ = pipeline.run(Job(cfg, drawing, cloud), pipeline.select(args.only, args.start, args.until), args.force)
    return code


def clean(cfg, drawing):
    """Delete the results (PLN, its backup, report) and the cache folder of a drawing. Refuses while an Archicad has
    the PLN open. The relief tool's terrain cache of the point cloud is that tool's and stays."""
    from .archicad.session import project_is_open
    from .job import Job
    job = Job(cfg, os.path.abspath(drawing), "")
    pln = Path(job.output_pln)
    if pln.exists() and project_is_open(cfg["archicad"]["host"], pln, tries=1):
        print(f"{pln.name} is open in Archicad: close it there first", file=sys.stderr)
        return 1
    gone = []
    for f in (pln, pln.with_suffix(".bpn"), Path(str(pln) + ".lck"), Path(job.output_report)):
        if f.exists():
            f.unlink()
            gone.append(str(f))
    if job.work_dir.exists():
        shutil.rmtree(job.work_dir)
        gone.append(str(job.work_dir))
    print("deleted:\n  " + "\n  ".join(gone) if gone else f"nothing to delete for {Path(drawing).name}")
    return 0
