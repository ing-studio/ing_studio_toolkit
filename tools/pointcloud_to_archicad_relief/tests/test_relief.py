"""Tests of the relief tool on synthetic data (no QGIS, CloudCompare or Archicad needed).

Run:  test.bat pointcloud_to_archicad_relief   (in the toolkit's folder)
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(TOOL_DIR), str(TOOL_DIR.parent.parent / "core")]  # the tool, the toolkit's library

from relief import cli, pipeline  # noqa: E402
from relief.config import ConfigError, cut_label, cut_sizes, load_config  # noqa: E402
from relief.geometry.smoothing import smooth_contour  # noqa: E402
from relief.io.cloud_formats import text_reader  # noqa: E402
from relief.job import RESULT_SUFFIX, Job, sort_inputs  # noqa: E402


class Settings(unittest.TestCase):
    def test_defaults_are_valid(self):
        cfg = load_config(use_project=False)
        self.assertEqual(list(cut_sizes(cfg)), ["1m", "3m", "5m"])
        self.assertEqual(cfg["_work"].name, "pointcloud_to_archicad_relief")

    def test_bad_values_are_refused(self):
        for bad in (["contours.cut_sizes_m=[]"], ["contours.cut_sizes_m=[1, 1.0]"], ["mesh.target_points=5"],
                    ["placement.mode=somewhere"], ["placement.new_pln_origin=[1]"], ["archicad.layer_contours=x"]):
            with self.assertRaises(ConfigError, msg=bad):
                load_config(assignments=bad, use_project=False)

    def test_cut_labels(self):
        self.assertEqual([cut_label(s) for s in (1, 2.5, 0.25)], ["1m", "2.5m", "0.25m"])

    def test_flags_become_settings(self):
        args = cli._parser().parse_args(["run", "a.e57", "--contours", "0.5", "2", "--no-3d", "--origin", "10,20"])
        cfg = load_config(assignments=cli._overrides(args), use_project=False)
        self.assertEqual(cfg["contours"]["cut_sizes_m"], [0.5, 2.0])
        self.assertFalse(cfg["archicad"]["contours_3d"])
        self.assertEqual(cfg["placement"]["new_pln_origin"], [10.0, 20.0])


class Inputs(unittest.TestCase):
    def test_files_are_sorted_by_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("survey.e57", "site.pln", "notes.doc", f"site{RESULT_SUFFIX}.pln"):
                (Path(tmp) / n).write_text("x")
            cfg = load_config(use_project=False)
            clouds, plns = sort_inputs(cfg, [str(Path(tmp) / "survey.e57"), str(Path(tmp) / "site.pln")])
            self.assertEqual([Path(c).name for c in clouds], ["survey.e57"])
            self.assertEqual([Path(p).name for p in plns], ["site.pln"])
            for bad in (["notes.doc"], [f"site{RESULT_SUFFIX}.pln"], [], ["missing.e57"]):
                with self.assertRaises(SystemExit, msg=bad):
                    sort_inputs(cfg, [str(Path(tmp) / n) for n in bad])

    def test_job_paths(self):
        cfg = load_config(use_project=False)
        job = Job(cfg, ["C:/data/Ground points - Cloud.e57", "C:/data/b.las"], "C:/p/My site.pln")
        self.assertEqual(job.cloud_dir.name, "Ground_points_Cloud_and_1_more")
        self.assertEqual(job.pln_dir.name, "My_site")
        self.assertEqual(Path(job.output_pln).name, f"My site{RESULT_SUFFIX}.pln")
        self.assertEqual(Job(cfg, ["C:/x/s.e57"]).pln_dir.name, "new_pln")

    def test_without_files_the_input_folder_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = Path(tmp)
            (tool / "input").mkdir()
            (tool / "input" / "survey.e57").write_text("x")
            (tool / "input" / "README.md").write_text("x")
            with mock.patch.object(cli, "TOOL_DIR", tool), \
                    mock.patch.object(pipeline, "run", return_value=(0, "log")) as run:
                self.assertEqual(cli.main(["--no-project-config"]), 0)
            cfg, clouds, plns = run.call_args.args[:3]
            self.assertEqual([Path(c).name for c in clouds], ["survey.e57"])
            self.assertEqual(plns, [])
            self.assertEqual(cfg["_output"], tool / "output")

    def test_text_cloud_columns_are_sniffed(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "pts.txt"
            f.write_text("X;Y;Z;Intensity\n" + "".join(f"{i};{i * 2};{i * 0.1:.2f};7\n" for i in range(20)))
            reader = text_reader(str(f))
            self.assertEqual(reader["separator"], ";")
            self.assertEqual(reader["header"], "X;Y;Z;Intensity")
            self.assertEqual(reader["skip"], 1)


class Contours(unittest.TestCase):
    SMOOTHING = {"reduce_tolerance_m": 0.0, "min_length_m": 10.0, "nurbs_degree": 3, "simplify_tolerance_m": 0.5,
                 "max_control_spacing_m": 20.0}

    def test_a_circle_is_smoothed_within_the_tolerance(self):
        t = np.linspace(0, 2 * np.pi, 400)
        ring = np.c_[50 * np.cos(t), 50 * np.sin(t)]
        ring[-1] = ring[0]
        out = smooth_contour(ring, True, self.SMOOTHING)
        self.assertLess(len(out["ctrl"]), 100)  # far fewer points than the cut line
        r = np.hypot(*out["curve"].T)
        self.assertLess(np.abs(r - 50).max(), 2.0)

    def test_short_lines_are_left_out(self):
        self.assertIsNone(smooth_contour(np.array([[0.0, 0.0], [3.0, 0.0], [6.0, 1.0]]), False, self.SMOOTHING))


class CommandLine(unittest.TestCase):
    def test_stages_and_config(self):
        self.assertEqual(pipeline.STAGE_NAMES, ["cloud", "ground", "dem", "reference", "contours", "archicad"])
        with mock.patch("sys.stdout") as out:
            self.assertEqual(cli.main(["config", "--no-project-config", "--contours", "2"]), 0)
        printed = "".join(c.args[0] for c in out.write.call_args_list)
        self.assertEqual(json.loads(printed)["contours"]["cut_sizes_m"], [2.0])


if __name__ == "__main__":
    unittest.main()
