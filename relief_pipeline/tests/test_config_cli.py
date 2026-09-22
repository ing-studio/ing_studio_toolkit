"""Configuration layering, validation and the command line."""
import json
import tempfile
import unittest
from pathlib import Path

from relief import cli
from relief.config import ConfigError, cut_label, cut_sizes, deep_merge, load_config, parse_assignment, settings
from relief.pipeline import STAGE_NAMES, select


class ConfigTest(unittest.TestCase):
    def test_defaults_load_and_validate(self):
        cfg = load_config(use_project=False)
        self.assertEqual(cfg["contours"]["cut_sizes_m"], [1, 3, 5])
        self.assertTrue(cfg["_work"].is_absolute())

    def test_deep_merge_keeps_siblings_and_replaces_lists(self):
        out = deep_merge({"a": {"x": 1, "y": [1, 2]}, "b": 1}, {"a": {"y": [3]}})
        self.assertEqual(out, {"a": {"x": 1, "y": [3]}, "b": 1})

    def test_set_parses_json_values(self):
        self.assertEqual(parse_assignment("contours.cut_sizes_m=[1,2,5]"), (["contours", "cut_sizes_m"], [1, 2, 5]))
        self.assertEqual(parse_assignment("placement.mode=object"), (["placement", "mode"], "object"))
        cfg = load_config(assignments=["mesh.target_points=40000"], use_project=False)
        self.assertEqual(cfg["mesh"]["target_points"], 40000)

    def test_unknown_key_and_bad_values_are_rejected(self):
        with self.assertRaises(ConfigError):
            load_config(assignments=["mesh.target_pionts=1"], use_project=False)
        with self.assertRaises(ConfigError):
            load_config(assignments=["contours.cut_sizes_m=[1,-2]"], use_project=False)
        with self.assertRaises(ConfigError):
            load_config(assignments=["placement.mode=somewhere"], use_project=False)

    def test_extra_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "site.json"
            path.write_text(json.dumps({"contours": {"cut_sizes_m": [2, 10]}}), encoding="utf-8")
            cfg = load_config([path], use_project=False)
        self.assertEqual(list(cut_sizes(cfg)), ["2m", "10m"])

    def test_labels_and_settings(self):
        self.assertEqual(cut_label(1), "1m")
        self.assertEqual(cut_label(2.5), "2.5m")
        cfg = load_config(use_project=False)
        self.assertNotIn("_note", settings(cfg, "mesh")["mesh"])


class CliTest(unittest.TestCase):
    def test_flags_become_overrides(self):
        args = cli._parser().parse_args(["run", "--pln", "a.pln", "--cloud", "b.e57", "--cut", "1", "2", "5",
                                         "--mesh-points", "30000", "--simplify", "0.3", "--no-3d"])
        cfg = cli._config(args)
        self.assertEqual(cfg["contours"]["cut_sizes_m"], [1.0, 2.0, 5.0])
        self.assertEqual(cfg["mesh"]["target_points"], 30000)
        self.assertEqual(cfg["contours"]["smoothing"]["simplify_tolerance_m"], 0.3)
        self.assertFalse(cfg["archicad"]["contours_3d"])

    def test_stage_selection(self):
        self.assertEqual(select(), STAGE_NAMES)
        self.assertEqual(select(stage="qa"), ["qa"])
        self.assertEqual(select(start="contours", until="archicad"), ["contours", "archicad"])
        with self.assertRaises(SystemExit):
            select(start="qa", until="cloud")


if __name__ == "__main__":
    unittest.main()
