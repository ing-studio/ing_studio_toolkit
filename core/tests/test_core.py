"""Tests of ing_core, the toolkit's library (no Archicad, network or registry changes needed).

Run:  test.bat core   (in the toolkit's folder)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CORE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE_DIR))

from ing_core import cli, config, util  # noqa: E402
from ing_core.archicad import addon  # noqa: E402

TOOLKIT_DIR = CORE_DIR.parent


def make_tool(root, default, project=None):
    tool = Path(root) / "some_tool"
    (tool / "config").mkdir(parents=True)
    (tool / "config" / "default.json").write_text(json.dumps(default), encoding="utf-8")
    if project is not None:
        (tool / "config" / "project.json").write_text(json.dumps(project), encoding="utf-8")
    return tool


DEFAULT = {"paths": {"output_dir": None, "work_dir": None}, "a": {"b": 1, "c": [1, 2], "_note": "x"}, "d": "keep"}


class Config(unittest.TestCase):
    def test_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = make_tool(tmp, DEFAULT, {"a": {"b": 2}})
            extra = Path(tmp) / "extra.json"
            extra.write_text(json.dumps({"a": {"c": [9]}}), encoding="utf-8")
            cfg = config.load(tool, lambda c: None, [extra], ["d=changed"])
            self.assertEqual(cfg["a"], {"b": 2, "c": [9], "_note": "x"})  # nested merged, lists replaced
            self.assertEqual(cfg["d"], "changed")
            self.assertEqual(cfg["_work"], util.LOCAL_DIR / "some_tool")
            self.assertEqual(len(cfg["_files"]), 3)
            self.assertEqual(config.load(tool, lambda c: None, use_project=False)["a"]["b"], 1)

    def test_set_parses_json_and_refuses_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = make_tool(tmp, DEFAULT)
            self.assertEqual(config.load(tool, lambda c: None, assignments=["a.c=[3, 4]"])["a"]["c"], [3, 4])
            for bad in ("a.nope=1", "nope.b=1", "no_equals_sign"):
                with self.assertRaises(config.ConfigError):
                    config.load(tool, lambda c: None, assignments=[bad])

    def test_validate_and_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = make_tool(tmp, DEFAULT)

            def refuse(cfg):
                raise config.ConfigError("no")
            with self.assertRaises(config.ConfigError):
                config.load(tool, refuse)
            (tool / "config" / "project.json").write_text("{broken", encoding="utf-8")
            with self.assertRaises(config.ConfigError):
                config.load(tool, lambda c: None)

    def test_settings_leave_out_notes(self):
        cfg = {"a": {"b": 1, "_note": "x", "c": {"d": 2, "_e": 3}}}
        self.assertEqual(config.settings(cfg, "a", "a.c"), {"a": {"b": 1, "c": {"d": 2}}, "a.c": {"d": 2}})


class Util(unittest.TestCase):
    def test_folders(self):
        self.assertEqual(util.TOOLKIT_DIR, TOOLKIT_DIR)
        self.assertTrue((util.TOOLKIT_DIR / "tools").is_dir())

    def test_slug(self):
        self.assertEqual(util.slug("Ground points Cascad - Cloud"), "Ground_points_Cascad_Cloud")
        self.assertEqual(util.slug("Պատուհան"), "job")

    def test_input_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(util.input_files(tmp, {".e57"}), [])  # no input folder
            (Path(tmp) / "input").mkdir()
            for name in ("b.E57", "a.e57", "notes.txt", "README.md"):
                (Path(tmp) / "input" / name).write_text("x")
            self.assertEqual([Path(p).name for p in util.input_files(tmp, {".e57"})], ["a.e57", "b.E57"])


class Addon(unittest.TestCase):
    def test_entries(self):
        live = "lan.flat:///" + Path(__file__).as_posix()
        self.assertEqual(addon.entry_file("lan.flat:///C:/Tapir/TapirAddOn_AC28_Win.apx"),
                         Path("C:/Tapir/TapirAddOn_AC28_Win.apx"))
        self.assertIsNone(addon.entry_file("some other form"))
        self.assertTrue(addon.is_tapir("lan.flat:///C:/x/TapirAddOn_AC29_Win.apx"))
        self.assertFalse(addon.is_live_tapir("lan.flat:///C:/gone/TapirAddOn_AC28_Win.apx"))  # its file is gone
        self.assertFalse(addon.is_live_tapir(live))  # not a Tapir
        self.assertEqual(addon.tapir_file(29), "TapirAddOn_AC29_Win.apx")
        self.assertIn(addon.TAPIR_VERSION, addon.tapir_url(28))

    def test_palette_buttons_are_told_where_their_tool_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool, target = Path(tmp) / "a_tool", Path(tmp) / "custom-scripts"
            (tool / "addon").mkdir(parents=True)
            (tool / "addon" / "My button.py").write_text('TOOL_DIR = r"__TOOL_DIR__"\n', encoding="utf-8")
            with mock.patch.object(addon, "PALETTE_TARGET", target), mock.patch.object(addon.shutil, "which",
                                                                                         return_value="uv"):
                addon.install_palette(tool)
                self.assertEqual((target / "My button.py").read_text(encoding="utf-8"),
                                 f'TOOL_DIR = r"{tool.resolve()}"\n')
                addon.install_palette(tool, remove=True)
                self.assertFalse((target / "My button.py").exists())

    def test_every_button_has_the_placeholder(self):
        buttons = list((TOOLKIT_DIR / "tools").glob("*/addon/*.py"))
        self.assertTrue(buttons)
        for b in buttons:
            self.assertIn('TOOL_DIR = r"__TOOL_DIR__"', b.read_text(encoding="utf-8"), b)


class Launchers(unittest.TestCase):
    """Every tool's .bat, through core\\run.cmd, with this Python (ING_TOOLKIT_PYTHON)."""

    def test_help_of_every_tool(self):
        env = dict(os.environ, ING_TOOLKIT_PYTHON=sys.executable)
        commands = [b for t in sorted((TOOLKIT_DIR / "tools").iterdir()) for b in sorted(t.glob("*.bat"))
                    if b.name not in ("install.bat", "uninstall.bat")]
        for bat in commands:
            p = subprocess.run(f'cmd /s /c ""{bat}" --help"', capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, cwd=tempfile.gettempdir())
            self.assertEqual(p.returncode, 0, f"{bat.name}: {p.stdout[-500:]} {p.stderr[-500:]}")
            self.assertIn("usage:", p.stdout, bat.name)

    def test_exit_code_comes_through(self):
        env = dict(os.environ, ING_TOOLKIT_PYTHON=sys.executable)
        bat = TOOLKIT_DIR / "tools" / "pointcloud_to_archicad_relief" / "relief.bat"
        p = subprocess.run(f'cmd /s /c ""{bat}" config --set no.such=1"', capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace")
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("unknown config", p.stderr)


class Suites(unittest.TestCase):
    def test_every_tool_has_a_suite(self):
        found = cli.suites()
        self.assertEqual(list(found)[0], "core")
        self.assertEqual(sorted(n for n in found if n != "core"),
                         sorted(p.name for p in (TOOLKIT_DIR / "tools").iterdir() if p.is_dir()))


if __name__ == "__main__":
    unittest.main()
