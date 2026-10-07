"""Command line of max_corona_materials (corona_materials.bat): a model's materials -> clean Corona part materials.

  corona_materials.bat [STEP ...] [options]   run the steps (default: all four, in order)
  corona_materials.bat sandstone SCENE.max ...  re-finish scenes in Technogym's Sand Stone materials (HD maps,
                                              black equipment removed or recoloured, previews)
  corona_materials.bat stages                 list the steps
  corona_materials.bat config [options]       print the effective settings
  corona_materials.bat check                  is 3ds Max (with Corona) there (install.bat runs it)
"""
import argparse
import json
import sys
import time
from pathlib import Path

from ing_core.config import ConfigError, default_work_dir, load
from ing_core.util import error, input_files, load_json, log, ok, section, set_log_file, skip, slug

from . import __version__, parts
from .maxbatch import MaxError, find_batch, run_step

TOOL_DIR = Path(__file__).resolve().parent.parent
COMMANDS = ("run", "sandstone", "stages", "config", "check")
STAGES = (
    ("reference", "the reference scene's Corona materials -> a material library (3ds Max)"),
    ("import", "the model (FBX) -> a raw .max, and the list of its materials (3ds Max)"),
    ("map", "every material of the model -> a part material (the rules in corona_materials/parts.py)"),
    ("rebuild", "the raw import -> one group per equipment, one mesh and Corona material per part (3ds Max)"),
)
STAGE_NAMES = [s for s, _ in STAGES]

RUN_HELP = """Inputs (default: the tool's input folder; then the results go to its output folder):
  the reference scene     a .max whose Corona materials are the templates (--reference)
  the model               the FBX to convert (--model)
  model_materials.json    optional: the model's materials with mesh counts and colours; else read from the import

Result: <model>_corona.max, <model>_part_map.csv and <model>_part_materials.csv.
3ds Max (with Corona) does the work without opening its window; a step whose result is there is reused (--force
redoes it). The map and the rebuild always run.

Examples:
  corona_materials.bat
  corona_materials.bat --model D:\\gym\\equipment.fbx --reference D:\\gym\\reference_set.max --out D:\\gym\\result
  corona_materials.bat map                         (only the part map: check it in the .csv before a long rebuild)
  corona_materials.bat rebuild --test-groups 5     (the first 5 equipment groups, into the work folder)
"""


SANDSTONE_HELP = r"""Scenes of Technogym equipment re-finished in the Sand Stone Collection's materials (Warm Titanium
frames, Speckled Stone casings, Clay upholstery ...), with texture maps made at 4096 px and mapped at their real size:
  - equipment in a black finish (diamondblack, anthracitesilver, or mostly dark) that the scenes also have in
    Sand Stone is removed; black equipment with no Sand Stone version is recoloured, on its own layer;
  - the colour swatches some models carry (small red / green / blue / yellow cubes) are removed;
  - every material becomes one of the Sand Stone materials (corona_materials/sandstone.py says which and why).
The scenes are only read. Results: <scene> - Sand Stone.max, maps\, previews\ (a material board and Corona renders),
sandstone_equipment.csv and sandstone_materials.csv (what was decided, and why).

Examples:
  corona_materials.bat sandstone
  corona_materials.bat sandstone "D:\gym\Part 1.max" "D:\gym\Part 2.max" --out D:\gym\sandstone
"""


def validate(cfg):
    if not isinstance(cfg.get("parts"), dict) or not any(not k.startswith("_") for k in cfg["parts"]):
        raise ConfigError("parts must name at least one part material")
    for name, spec in cfg["parts"].items():
        if name.startswith("_"):
            continue
        if not (isinstance(spec, list) and len(spec) == 4 and isinstance(spec[0], str)):
            raise ConfigError(f"parts.{name} must be [template, diffuse or null, glossiness or null, IOR or null]")
    if cfg["fallback_part"] not in cfg["parts"]:
        raise ConfigError(f"fallback_part {cfg['fallback_part']!r} is not one of the parts")


def _parser():
    ap = argparse.ArgumentParser(prog="corona_materials.bat", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"max_corona_materials {__version__}")
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")
    run = sub.add_parser("run", help="run the steps (the default command)",
                         usage="corona_materials.bat [STEP ...] [options]",
                         description="A model's materials -> clean Corona part materials.", epilog=RUN_HELP,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    run.add_argument("steps", nargs="*", metavar="STEP", help=f"{', '.join(STAGE_NAMES)} (default: all)")
    _settings_args(run)
    run.add_argument("--test-groups", type=int, default=0, metavar="N",
                     help="rebuild only the first N equipment groups, into the work folder (a quick check)")
    run.add_argument("--force", action="store_true", help="redo the reference and import steps even if they are done")
    sand = sub.add_parser("sandstone", help="re-finish scenes in the Sand Stone materials",
                          usage="corona_materials.bat sandstone SCENE.max [SCENE.max ...] [options]",
                          description=SANDSTONE_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    sand.add_argument("scenes", nargs="*", metavar="SCENE",
                      help="3ds Max scenes (default: the .max files in input\\sandstone)")
    sand.add_argument("--out", metavar="DIR", help="folder for the results (default: output\\sandstone)")
    sand.add_argument("--no-preview", action="store_true", help="no material board and preview renders")
    sand.add_argument("--force", action="store_true", help="survey the scenes again even if done before")
    sand.add_argument("--config", action="append", default=[], metavar="FILE", help="extra JSON settings")
    sand.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                      help="a setting, e.g. --set sandstone.map_size=2048")
    sand.add_argument("--no-project-config", action="store_true", help="ignore config/project.json")
    sub.add_parser("stages", help="list the steps")
    sub.add_parser("check", help="is 3ds Max (with Corona) there")
    _settings_args(sub.add_parser("config", help="print the effective settings"))
    return ap


def _settings_args(p):
    g = p.add_argument_group("inputs and results")
    g.add_argument("--reference", metavar="MAX", help="the reference scene (default: the .max in the input folder)")
    g.add_argument("--model", metavar="FBX", help="the model (default: the .fbx in the input folder)")
    g.add_argument("--model-materials", metavar="JSON", help="the model's materials, if not read from the import")
    g.add_argument("--out", metavar="DIR", help="folder for the results")
    g = p.add_argument_group("settings files")
    g.add_argument("--config", action="append", default=[], metavar="FILE",
                   help="extra JSON settings merged over config/default.json and config/project.json (repeatable)")
    g.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="any setting of config/default.json, e.g. --set max.version=2025 (repeatable)")
    g.add_argument("--no-project-config", action="store_true", help="ignore config/project.json")


def _overrides(args):
    out = list(args.set)
    for attr, key in (("reference", "paths.reference"), ("model", "paths.model"),
                      ("model_materials", "paths.model_materials"), ("out", "paths.output_dir")):
        value = getattr(args, attr, None)
        if value:
            out.append((key.split("."), str(Path(value).resolve())))
    return out


def _one(cfg_value, extensions, what):
    """A file from the settings, else the only one of its kind in the input folder."""
    if cfg_value:
        if not Path(cfg_value).is_file():
            raise SystemExit(f"{what} not found: {cfg_value}")
        return Path(cfg_value)
    found = input_files(TOOL_DIR, extensions)
    if len(found) != 1:
        raise SystemExit(f"{what}: put exactly one {' or '.join(sorted(extensions))} file in {TOOL_DIR / 'input'} "
                         f"(it has {len(found) or 'none'}), or give it on the command line")
    return Path(found[0])


def _newer(result, *sources):
    return Path(result).exists() and all(Path(result).stat().st_mtime >= Path(s).stat().st_mtime for s in sources)


def run(cfg, steps, force=False, test_groups=0):
    reference = _one(cfg["paths"]["reference"], {".max"}, "The reference scene")
    model = _one(cfg["paths"]["model"], {".fbx"}, "The model")
    work = cfg["_work"] / slug(model.stem)
    work.mkdir(parents=True, exist_ok=True)
    out_dir = cfg["_output"]
    set_log_file(work / "corona_materials.log")
    section(f"max_corona_materials {__version__}  -  {time.strftime('%Y-%m-%d %H:%M')}")
    log(f"model {model}\nreference {reference}\nwork folder {work}\nresults {out_dir}")
    common = {"ING_WORK": str(work) + "\\"}
    raw = work / f"{slug(model.stem)}_raw_import.max"
    result = out_dir / f"{model.stem}_corona.max"
    batch = None

    def max_exe():
        nonlocal batch
        batch = batch or find_batch(cfg["max"]["version"])
        return batch

    if "reference" in steps:
        if not force and _newer(work / "reference.mat", reference):
            skip("reference: the material library is there (--force redoes it)")
        else:
            run_step(max_exe(), "reference", "dump_reference.ms", {**common, "ING_REFERENCE": str(reference)},
                     work / "reference.log")
            ok(f"reference: {work / 'reference.mat'}")
    if "import" in steps:
        if not force and _newer(raw, model) and (work / "model_materials.json").exists():
            skip("import: the raw import is there (--force redoes it)")
        else:
            run_step(max_exe(), "import", "import_model.ms", {**common, "ING_MODEL": str(model), "ING_RAW": str(raw)},
                     work / "import.log")
            ok(f"import: {raw}")
    if "map" in steps:
        given = cfg["paths"]["model_materials"] or (TOOL_DIR / "input" / "model_materials.json")
        source = Path(given) if Path(given).is_file() else work / "model_materials.json"
        materials = load_json(source)
        if materials is None:
            raise SystemExit(f"map: no list of the model's materials ({source}): run the import step first")
        rows = parts.part_map(materials)
        parts.check_parts(cfg["parts"], rows, cfg["fallback_part"])
        used = parts.write(cfg["parts"], rows, work, out_dir, model.stem)
        for p, (n, meshes) in used.items():
            log(f"map: {p:24s} {n:4d} materials {meshes:7d} meshes")
        ok(f"map: {len(rows)} materials -> {len(used)} part materials ({source.name}); "
           f"{out_dir / (model.stem + '_part_map.csv')}")
    if "rebuild" in steps:
        for f in ("reference.mat", "part_materials.tsv", "part_map.tsv", raw.name):
            if not (work / f).exists():
                raise SystemExit(f"rebuild: {work / f} is missing - run the steps before it")
        out_dir.mkdir(parents=True, exist_ok=True)
        values = {**common, "ING_RAW": str(raw), "ING_OUT": str(result), "ING_MODEL_ROOT": cfg["max"]["model_root"],
                  "ING_FALLBACK": cfg["fallback_part"], "TEST_GROUPS": int(test_groups)}
        run_step(max_exe(), "rebuild", "rebuild_parts.ms", values,
                 work / ("restructure_test.log" if test_groups else "restructure.log"))
        for line in (work / ("restructure_test.log" if test_groups else "restructure.log")).read_text(
                encoding="utf-8", errors="replace").splitlines():
            if "groups built" in line or "duplicates removed" in line or "outside part groups" in line:
                log("rebuild: " + line.split(" ", 2)[-1])
        ok(f"rebuild: {work / 'restructure_test.max' if test_groups else result}")
    return 0


def check():
    """3ds Max for the 3D steps, and Corona in it."""
    try:
        exe = Path(find_batch())
    except MaxError as e:
        print(e, file=sys.stderr)
        return 1
    year = exe.parent.name.rsplit(" ", 1)[-1]
    corona = list((exe.parent / "plugins").glob("Corona*.dlr"))
    print(f"3ds Max {year}: {exe}")
    if not corona:
        print(f"Corona for 3ds Max {year} was not found in {exe.parent / 'plugins'}: the rebuild needs it",
              file=sys.stderr)
        return 1
    print(f"Corona: {corona[0].name}")
    return 0


def sandstone_command(args):
    from . import sandstone_run
    try:
        cfg = load(TOOL_DIR, validate, args.config, list(args.set), use_project=not args.no_project_config)
    except ConfigError as e:
        print(f"settings error: {e}", file=sys.stderr)
        return 2
    scenes = [Path(p).resolve() for p in args.scenes] or \
        [Path(p) for p in sorted((TOOL_DIR / "input" / "sandstone").glob("*.max"))]
    missing = [str(p) for p in scenes if not p.is_file()]
    if not scenes or missing:
        print(f"sandstone: {'not found: ' + ', '.join(missing) if missing else 'no scenes'} - give the .max files, "
              f"or put them in {TOOL_DIR / 'input' / 'sandstone'}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).resolve() if args.out else TOOL_DIR / "output" / "sandstone"
    work = cfg["_work"] / "sandstone"
    work.mkdir(parents=True, exist_ok=True)
    set_log_file(work / "sandstone.log")
    section(f"max_corona_materials {__version__}: Sand Stone  -  {time.strftime('%Y-%m-%d %H:%M')}")
    log("scenes:\n" + "\n".join(str(p) for p in scenes) + f"\nresults {out_dir}\nwork folder {work}")
    t0 = time.time()
    try:
        results = sandstone_run.run(cfg, scenes, out_dir, find_batch(cfg["max"]["version"]), TOOL_DIR,
                                    preview=not args.no_preview, force=args.force)
    except (MaxError, ValueError, OSError) as e:
        error(f"stopped: {e}")
        return 1
    ok(f"done in {int(time.time() - t0) // 60} min: " + ", ".join(p.name for p in results))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version"):
        argv.insert(0, "run")
    args = _parser().parse_args(argv)
    if args.command == "stages":
        for name, text in STAGES:
            print(f"{name:10s} {text}")
        return 0
    if args.command == "check":
        return check()
    if args.command == "sandstone":
        return sandstone_command(args)
    from_input = not (args.reference or args.model)
    if from_input and not args.out:
        args.out = str(TOOL_DIR / "output")
    try:
        cfg = load(TOOL_DIR, validate, args.config, _overrides(args), use_project=not args.no_project_config)
    except ConfigError as e:
        print(f"settings error: {e}", file=sys.stderr)
        return 2
    if args.command == "config":
        print(json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")}, indent=2, ensure_ascii=False))
        print(f"work folder: {default_work_dir(TOOL_DIR)} (default)", file=sys.stderr)
        return 0
    unknown = [s for s in args.steps if s not in STAGE_NAMES]
    if unknown:
        print(f"unknown step {', '.join(unknown)}; the steps are: {', '.join(STAGE_NAMES)}", file=sys.stderr)
        return 2
    steps = [s for s in STAGE_NAMES if s in (args.steps or STAGE_NAMES)]
    try:
        return run(cfg, steps, args.force, args.test_groups)
    except (MaxError, ValueError) as e:
        error(f"stopped: {e}")
        return 1
