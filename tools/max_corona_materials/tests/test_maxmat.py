"""Tests of max_corona_materials.

  the part map    on the Technogym set: the 332 materials of examples/technogym give the same parts, rules and files
  3ds Max         (only with ING_TEST_3DSMAX=1: it takes a few minutes) a small reference scene and model are made in
                  3ds Max, then every step runs on them
Run:  test.bat max_corona_materials   (in the toolkit's folder)
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(TOOL_DIR), str(TOOL_DIR.parent.parent / "core")]  # the tool, the toolkit's library

from ing_core.config import load  # noqa: E402
from maxmat import cli, maxbatch, parts  # noqa: E402

EXAMPLE = TOOL_DIR / "examples" / "technogym"


def example_rows():
    with open(EXAMPLE / "part_map.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def example_materials():
    """The model's materials as the import step lists them, from the example map."""
    return [{"name": r["source"], "meshes": int(r["meshes"]), "rgb": [int(v) for v in r["skp_rgb"].split(",")]}
            for r in example_rows()]


def settings(**over):
    return load(TOOL_DIR, cli.validate, assignments=list(over.items()), use_project=False)


class PartMap(unittest.TestCase):
    def test_technogym_set_maps_as_before(self):
        rows = parts.part_map(example_materials())
        expected = example_rows()
        self.assertEqual(len(rows), 332)
        self.assertEqual([(r["source"], r["part"], r["rule"]) for r in rows],
                         [(r["source"], r["part"], r["rule"]) for r in expected])

    def test_files_match_the_example(self):
        cfg = settings()
        rows = parts.part_map(example_materials())
        parts.check_parts(cfg["parts"], rows, cfg["fallback_part"])
        with tempfile.TemporaryDirectory() as tmp:
            work, out = Path(tmp) / "work", Path(tmp) / "out"
            used = parts.write(cfg["parts"], rows, work, out, "technogym")
            for mine, theirs in (("technogym_part_map.csv", "part_map.csv"),
                                 ("technogym_part_materials.csv", "part_materials.csv")):
                self.assertEqual((out / mine).read_text(encoding="utf-8").splitlines(),
                                 (EXAMPLE / theirs).read_text(encoding="utf-8").splitlines(), mine)
            tsv = (work / "part_materials.tsv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(tsv), len(used))
            self.assertIn("TG_SAND_FRAME\tMaterial #899\t140,127,113\t0.68\t1.8", tsv)
            self.assertIn("TG_SAND_PLASTIC\tMaterial #2147464532\t\t\t", tsv)
            self.assertEqual(len((work / "part_map.tsv").read_text(encoding="utf-8").splitlines()), 332)

    def test_rules(self):
        self.assertEqual(parts.classify("TG_skill_sandstone_belt", [46, 46, 46]), ("TG_BELT", "TG belt"))
        self.assertEqual(parts.classify("chrome_handle", [200, 200, 200])[0], "TG_CHROME")
        self.assertEqual(parts.classify("Material__55", [230, 30, 30]), ("TG_RED", "colour: accent"))
        self.assertEqual(parts.classify("Material__56", [90, 90, 90])[0], "TG_PLASTIC_MID_GREY")
        self.assertEqual(parts.classify("Material__57", [150, 130, 110]), ("TG_SAND_PLASTIC", "colour: sandstone-like"))

    def test_undefined_part_is_refused(self):
        cfg = settings()
        smaller = {k: v for k, v in cfg["parts"].items() if k != "TG_BELT"}
        with self.assertRaises(ValueError):
            parts.check_parts(smaller, parts.part_map([{"name": "TG_x_belt", "meshes": 1, "rgb": [1, 1, 1]}]),
                              cfg["fallback_part"])


class Settings(unittest.TestCase):
    def test_default_settings_are_valid(self):
        cfg = settings()
        self.assertIn(cfg["fallback_part"], cfg["parts"])

    def test_fallback_must_be_a_part(self):
        from ing_core.config import ConfigError
        with self.assertRaises(ConfigError):
            settings(fallback_part="NO_SUCH_PART")

    def test_settings_script(self):
        src = maxbatch.settings_script(Path(r"C:\t\scripts\x.ms"), {"ING_WORK": "C:\\w\\", "TEST_GROUPS": 3})
        self.assertEqual(src.splitlines(), ['global ING_WORK = @"C:\\w\\"', "global TEST_GROUPS = 3",
                                            'fileIn @"C:\\t\\scripts\\x.ms"'])
        with self.assertRaises(maxbatch.MaxError):
            maxbatch.mxs_value('a "quoted" name')


FIXTURES = r"""
-- a reference scene with Corona templates, and a small model: Model > two equipment groups, a duplicate mesh
fn makeFixtures = (
    fn mk nm = (local m = CoronaLegacyMtl(); m.name = nm; m)
    resetMaxFile #noPrompt
    local i = 0
    for t in #("Material #975", "Material #978", "Material #29", "Material #2") do (
        i += 1
        local b = box pos:[i * 100, 0, 0]
        b.material = mk t
    )
    saveMaxFile (ING_WORK + "reference.max") quiet:true
    resetMaxFile #noPrompt
    local belt = StandardMaterial name:"TG_skill_sandstone_belt" diffuse:(color 46 46 46)
    local chrome = StandardMaterial name:"chrome_parts" diffuse:(color 200 200 200)
    local grey = StandardMaterial name:"Material__55" diffuse:(color 90 90 90)
    local root = Dummy name:"Model"
    local a1 = box length:50 width:50 height:50 pos:[0, 0, 0] material:belt
    local a2 = sphere radius:20 pos:[0, 0, 80] material:chrome
    local g1 = group #(a1, a2) name:"Treadmill"
    local b1 = box length:40 width:40 height:40 pos:[300, 0, 0] material:grey
    local b2 = box length:40 width:40 height:40 pos:[300, 0, 0] material:belt
    local g2 = group #(b1, b2) name:"Bike"
    g1.parent = root
    g2.parent = root
    exportFile (ING_WORK + "model.fbx") #noPrompt using:FBXEXP
    local f = createFile (ING_WORK + "fixtures.log")
    format "DONE\n" to:f
    close f
)
makeFixtures()
"""


@unittest.skipUnless(os.environ.get("ING_TEST_3DSMAX") == "1", "set ING_TEST_3DSMAX=1 to run the 3ds Max steps")
class With3dsMax(unittest.TestCase):
    def test_every_step(self):
        exe = maxbatch.find_batch()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fixtures = tmp / "fixtures.ms"
            fixtures.write_text(FIXTURES, encoding="utf-8")
            runner = tmp / "run_fixtures.ms"  # (run_step runs the tool's scripts\; the fixtures run directly)
            runner.write_text(maxbatch.settings_script(fixtures, {"ING_WORK": str(tmp) + "\\"}), encoding="utf-8")
            subprocess.run([exe, str(runner), "-listenerLog", str(tmp / "fixtures_listener.log")], capture_output=True)
            self.assertTrue((tmp / "model.fbx").exists(), "3ds Max did not make the test model")

            out = tmp / "out"
            code = cli.main(["--reference", str(tmp / "reference.max"), "--model", str(tmp / "model.fbx"),
                             "--out", str(out), "--no-project-config", "--set", f"paths.work_dir={tmp / 'work'}"])
            self.assertEqual(code, 0)
            self.assertTrue((out / "model_corona.max").exists())
            names = {m["name"] for m in json.loads((tmp / "work" / "model" / "model_materials.json").read_text())}
            self.assertTrue({"TG_skill_sandstone_belt", "chrome_parts", "Material__55"} <= names, names)
            with open(out / "model_part_map.csv", encoding="utf-8", newline="") as f:
                mapped = {r["source"]: r["part"] for r in csv.DictReader(f)}
            self.assertEqual(mapped["TG_skill_sandstone_belt"], "TG_BELT")
            self.assertEqual(mapped["chrome_parts"], "TG_CHROME")
            log = (tmp / "work" / "model" / "restructure.log").read_text(encoding="utf-8")
            self.assertIn("groups built 2", log)
            self.assertIn("different material 1", log)  # the two boxes on one spot: one is kept


if __name__ == "__main__":
    unittest.main()
