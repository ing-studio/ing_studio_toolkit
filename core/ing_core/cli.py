"""The toolkit's own commands (the root install.bat, uninstall.bat and test.bat use them).

  python -m ing_core tapir install|remove|status    Tapir in every Archicad 28 / 29 of this machine
  python -m ing_core test [TOOL ...]                the test suites: core and every tool (or the ones named)
"""
import argparse
import json
import os
import subprocess
import sys

from . import __version__
from .util import TOOLKIT_DIR


def suites():
    """{name: folder} of every test suite: core's, then each tool's (tests\\ under its folder)."""
    out = {"core": TOOLKIT_DIR / "core"}
    for tool in sorted((TOOLKIT_DIR / "tools").iterdir()):
        if (tool / "tests").is_dir():
            out[tool.name] = tool
    return out


def run_tests(names):
    """Each suite in its own Python, from its own folder (the tools' packages and tests never meet)."""
    found = suites()
    unknown = [n for n in names if n not in found]
    if unknown:
        print(f"no test suite {', '.join(unknown)}; there are: {', '.join(found)}", file=sys.stderr)
        return 2
    failed = []
    for name in names or found:
        print(f"\n=== {name}", flush=True)
        env = dict(os.environ, PYTHONPATH=str(TOOLKIT_DIR / "core"), PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "tests"],
                           cwd=found[name], env=env)
        if p.returncode:
            failed.append(name)
    print("\n" + (f"FAILED: {', '.join(failed)}" if failed else f"all {len(names or found)} test suites passed"))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ing_core", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"ing_core {__version__}")
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")
    tapir = sub.add_parser("tapir", help="the Tapir add-on in Archicad 28 / 29")
    tapir.add_argument("action", choices=["install", "remove", "status"])
    test = sub.add_parser("test", help="run the test suites")
    test.add_argument("names", nargs="*", metavar="SUITE", help="core or a tool's folder name (default: all)")
    args = ap.parse_args(argv)

    if args.command == "test":
        return run_tests(args.names)
    from .archicad import addon
    from .archicad.client import ArchicadError
    try:
        if args.action == "status":
            print(json.dumps(addon.status(), indent=2))
        elif args.action == "remove":
            addon.remove_tapir()
        else:
            addon.register_tapir()
    except ArchicadError as e:
        print(f"addon: {e}", file=sys.stderr)
        return 1
    return 0
