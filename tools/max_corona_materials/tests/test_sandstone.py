"""Tests of the Sand Stone finish (corona_materials.sandstone, corona_materials.maps), without 3ds Max.

  the rules     real size, black twins / black-only equipment, swatches and zones, the material of every Technogym
                material, the name of the scenes put together
  the maps      seamless, the same every time, the catalogue's colours
  3ds Max       (only with ING_TEST_3DSMAX=1) the clean-up of the meshes: the same surface twice, a screen lying in its
                panel's plane, duplicate faces, dense meshes smoothed over their hard edges, weighted normals; the
                equipment arranged in rows
Run:  test.bat max_corona_materials   (in the toolkit's folder)
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(TOOL_DIR), str(TOOL_DIR.parent.parent / "core")]  # the tool, the toolkit's library

from corona_materials import maps, maxbatch, sandstone as S, sandstone_run as R  # noqa: E402

KNOWN = S.known_colours(TOOL_DIR)


def eq(name, dims_mm, mats, at=(0, 0, 0)):
    """A surveyed piece of equipment: name, size in mm, [(material, faces)]."""
    return {"eq": name, "min": list(at), "max": [a + d for a, d in zip(at, dims_mm)], "faces": sum(f for _, f in mats),
            "mats": [{"m": m, "f": f, "rgb": KNOWN.get(m)} for m, f in mats]}


class Equipment(unittest.TestCase):
    def test_black_twin_is_removed_black_only_is_recoloured(self):
        scenes = {
            "part1": [eq("TG_freeweights_diamondblack_1169_4023_1", (930, 1200, 1320),
                         [("TG_free_weights_diamondblack_frame_performance", 500)]),
                      eq("G_14a33673_bike", (230, 480, 480), [("material__2_aee9efb6", 900), ("_auto_", 50)])],
            "part2": [eq("TG_freeweights_sandstone_424_4023_1", (1200, 930, 1325),
                         [("TG_free_weights_sandstone_frame_performance", 500)])],
        }
        acts = {s: {e: (a, why) for e, a, why in rows} for s, rows in S.decide(scenes, KNOWN).items()}
        self.assertEqual(acts["part1"]["TG_freeweights_diamondblack_1169_4023_1"][0], "remove")
        self.assertIn("TG_freeweights_sandstone_424_4023_1 (part2)",
                      acts["part1"]["TG_freeweights_diamondblack_1169_4023_1"][1])
        self.assertEqual(acts["part1"]["G_14a33673_bike"][0], "recolour")     # mostly dark, no Sand Stone version
        self.assertEqual(acts["part2"]["TG_freeweights_sandstone_424_4023_1"][0], "keep")

    def test_twins_are_found_at_real_size(self):
        # the import's equipment is 2.54 times too small (SketchUp's inches read as mm); a model merged in from
        # elsewhere is real: the black import is the Sand Stone model's twin only at their real sizes
        black = eq("TG_artis_run_diamondblack_1", (350.4, 810.4, 621.3), [("TG_artis_cardio_diamondblack_frame", 900)])
        black.update({"import": True, "scale": 10.0})        # (its meshes in inches, read at 10 mm)
        sand = eq("Group001_Artis_Run", (890, 2058, 1578), [("Material #2147464532", 900)])
        scenes = {"part1": [black], "part2": [sand]}
        self.assertEqual(S.decide(scenes, KNOWN)["part1"][0][1], "recolour")
        S.to_real_size([black, sand], 25.4)
        self.assertEqual([round(d) for d in S.dims_cm(black)], [89, 158, 206])
        self.assertEqual(S.dims_cm(sand), [89.0, 157.8, 205.8])                  # (not an import: as it was)
        self.assertEqual(S.decide(scenes, KNOWN)["part1"][0][1], "remove")
        # a piece scaled by hand in its scene (meshes at 29.25) comes to the same real size
        rig = eq("TG_freeweights_diamondblack_432_3943_1", (2280.4, 2183.4, 1520.3), [])
        rig.update({"import": True, "scale": 29.253})
        S.to_real_size([rig], 25.4)
        self.assertEqual([round(d) for d in S.dims_cm(rig)], [132, 190, 198])

    def test_hidden_equipment_is_removed(self):
        bike = eq("G_14a33673_bike", (230, 480, 480), [("material__2_aee9efb6", 900)])
        bike["hidden"] = True
        rack = eq("TG_freeweights_sandstone_424_4023_1", (1200, 930, 1325),
                  [("TG_free_weights_sandstone_frame_performance", 500)])
        rack["hidden"] = True
        black = eq("TG_freeweights_diamondblack_1169_4023_1", (930, 1200, 1320),
                   [("TG_free_weights_diamondblack_frame_performance", 500)])
        rows = S.decide({"part1": [bike, rack, black]}, KNOWN)["part1"]
        self.assertEqual([r[1] for r in rows], ["remove", "remove", "recolour"])   # (a hidden twin is no twin)
        self.assertIn("hidden", rows[0][2])
        self.assertIn("hidden", rows[1][2])

    def test_finish(self):
        self.assertEqual(S.finish(eq("TG_skill_anthracitesilver_801_340_1", (1, 1, 1), []), KNOWN), "black")
        self.assertEqual(S.finish(eq("c49bfe63", (1, 1, 1), [("TG_skill_sandstone_plastic_1", 10)]), KNOWN), "sand")
        self.assertEqual(S.finish(eq("artis", (1, 1, 1), [("Material #2147464532", 10)]), KNOWN), "sand")
        self.assertEqual(S.finish(eq("ball", (1, 1, 1), [("acad11b286c2", 90), ("_auto_", 10)]), KNOWN), "black")
        self.assertEqual(S.finish(eq("mat", (1, 1, 1), [("_auto_", 90)]), KNOWN), "neutral")


class Materials(unittest.TestCase):
    def target(self, name):
        return S.material_target(name, S.colour_of(name, None, KNOWN))[0]

    def test_the_catalogue_finishes(self):
        self.assertEqual(self.target("TG_pureplate_sandstone_frame"), "SS_Warm_Titanium")
        self.assertEqual(self.target("TG_free_weights_diamondblack_frame_performance"), "SS_Warm_Titanium")
        self.assertEqual(self.target("TG_cablestations_sandstone_plastic_1"), "SS_Speckled_Stone")
        self.assertEqual(self.target("TG_biostrength_sandstone_upholstery"), "SS_Clay_Upholstery")
        self.assertEqual(self.target("TG_skill_sandstone_belt"), "SS_Running_Belt")
        self.assertEqual(self.target("TG_fixed_yellow_handles"), "SS_TG_Yellow")
        self.assertEqual(self.target("TG_red_button"), "SS_Red_Button")

    def test_nothing_black_is_left_black(self):
        for name in ("Grey_Dumb_ede6faa3", "e4ab1202_1d96_4988_8a9c_7b34b0b5c04e", "acad11b286c2",
                     "Material__33_d9ef82fd", "Plastic_Black_caec0045"):
            self.assertEqual(self.target(name), "SS_Clay_Urethane", name)
        self.assertEqual(self.target("Black_Metal__d81abc68"), "SS_Warm_Titanium")
        self.assertEqual(self.target("material__2_aee9efb6"), "SS_Warm_Titanium")
        self.assertEqual(S.MATERIALS["SS_Logo_Dark"]["rgb"], (118, 101, 89))   # plates: clay, printed in ivory

    def test_every_technogym_material_has_a_sand_stone_material(self):
        self.assertEqual(len(KNOWN), 332)
        rows = S.material_rows({n: None for n in KNOWN}, KNOWN)
        self.assertEqual({r[1] for r in rows} - set(S.MATERIALS), set())
        self.assertEqual(len({r[1] for r in rows}), 17)      # (the screen and display are the reference set's)

    def test_swatches_and_zones(self):
        self.assertTrue(S.is_swatch_material("e3736644_9b6f_41b5_bf05_d66abb5f4b07", [255, 0, 0]))
        self.assertFalse(S.is_swatch_material("TG_red_button", [206, 0, 0]))
        self.assertFalse(S.is_swatch_material("reformer_leva_gi_9ea055fa", [224, 223, 75]))
        self.assertFalse(S.is_swatch_material("Material #977", [255, 0, 0]))
        self.assertTrue(S.is_zone_material("e03b7f63_655b_4b5a_8015_602137e28e52", [253, 241, 102]))
        self.assertTrue(S.is_zone_material("_auto_58", [127, 111, 63]))
        self.assertFalse(S.is_zone_material("TG_skill_sandstone_plastic_2", [46, 46, 46]))

    def test_files_for_3ds_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            S.write(tmp, {"p": [("A", "keep", "sand")]}, [("x", "SS_Ivory", [1, 1, 1], "")], ["s"], ["z"])
            rows = [ln.split("\t") for ln in (Path(tmp) / "sandstone_materials.tsv").read_text().splitlines()]
            self.assertEqual(len(rows), len(S.MATERIALS))
            self.assertTrue(all(len(r) == len(S.MATERIAL_FIELDS) for r in rows))
            stone = next(r for r in rows if r[0] == "SS_Speckled_Stone")
            # colours go to 3ds Max linear: sRGB 200 -> 147.3
            self.assertEqual(stone[S.MATERIAL_FIELDS.index("rgb")].split(",")[0], "147.283")
            for f in ("sandstone_map.tsv", "sandstone_swatches.tsv", "sandstone_zones.tsv", "p_actions.tsv"):
                self.assertTrue((Path(tmp) / f).exists(), f)

    def test_the_maxscript_reads_the_same_fields(self):
        # sandstone_materials.ms reads the tsv's columns by position (SS_FIELDS)
        ms = (TOOL_DIR / "scripts" / "sandstone_materials.ms").read_text(encoding="utf-8")
        line = next(ln for ln in ms.splitlines() if ln.startswith("global SS_FIELDS"))
        self.assertEqual(line.split("#(", 1)[1].rstrip(")").replace('"', "").split(", "), S.MATERIAL_FIELDS)

    def test_edges(self):
        # every material that rounds its edges in renders (Corona Round Edges) has a chamfer for the geometry too, and
        # a real chamfer is never smaller than the render's rounding
        for name, m in S.MATERIALS.items():
            if m.get("round_mm"):
                self.assertGreaterEqual(m.get("chamfer_mm", 0), m["round_mm"], name)


class Results(unittest.TestCase):
    def test_the_name_of_the_scenes_together(self):
        stems = [f"Technogym Equipment Part {i}" for i in range(1, 5)]
        self.assertEqual(R.common_name(stems), "Technogym Equipment")
        self.assertEqual(R.common_name(["gym a", "gym b"]), "gym")
        self.assertEqual(R.common_name(["one"]), "one")
        self.assertEqual(R.common_name(["north", "south"]), "Scenes")

    def test_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sizes.tsv"
            path.write_text("rack_1\t2515\t660\t897\nbroken line\n", encoding="utf-8")
            self.assertEqual(R.read_sizes(path), {"rack_1": (2515, 660, 897)})
            self.assertEqual(R.read_sizes(Path(tmp) / "missing.tsv"), {})


class Maps(unittest.TestCase):
    def test_seamless_and_seeded(self):
        a = maps.speckled_stone(256, np.random.default_rng(1))
        b = maps.speckled_stone(256, np.random.default_rng(1))
        self.assertTrue(np.array_equal(a["albedo"], b["albedo"]))
        bump = a["bump"]
        inside = np.abs(np.diff(bump, axis=1)).mean()
        across = np.abs(bump[:, 0] - bump[:, -1]).mean()      # the right edge meets the left edge
        self.assertLess(across, inside * 1.6)

    def test_catalogue_colours(self):
        a = maps.speckled_stone(512, np.random.default_rng(2))["albedo"].reshape(-1, 3).mean(0)
        self.assertTrue(np.allclose(a, maps.SPECKLED_STONE, atol=1.0), a)
        c = maps.clay_leather(256, np.random.default_rng(3))["albedo"].reshape(-1, 3).mean(0)
        self.assertTrue(np.allclose(c, maps.CLAY, atol=1.0), c)

    def test_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = maps.make_all(tmp, size=128, only=["stipple"])
            self.assertEqual(set(out), {"stipple_bump.png", "stipple_rough.png"})
            from osgeo import gdal
            ds = gdal.Open(str(out["stipple_bump.png"]))
            bits = ds.GetRasterBand(1).DataType
            ds = None                                                       # (closes the file)
            self.assertEqual(bits, gdal.GDT_UInt16)                         # heights in 16 bit


# a small scene for the clean-up, checked in 3ds Max; writes name=value lines to ING_WORK\clean.log
CLEAN = r"""
fileIn (ING_SCRIPTS + "smooth_rounds.ms")
fileIn (ING_SCRIPTS + "clean_scene.ms")
fileIn (ING_SCRIPTS + "arrange_equipment.ms")
fn mtl nm = (local m = StandardMaterial(); m.name = nm; m)
fn cleanTest = (
    local f = createFile (ING_WORK + "clean.log")
    try (
        resetMaxFile #noPrompt
        -- the same box three times (one a hair apart, one in a generic material) and a smaller box at the same corner
        local a = convertToMesh (Box length:100 width:100 height:20 pos:[0, 0, 0]); a.name = "a"; a.material = mtl "_auto_"
        local b = convertToMesh (Box length:100 width:100 height:20 pos:[0, 0, 0.05]); b.name = "b"; b.material = mtl "TG_frame"
        local c = convertToMesh (Box length:100 width:100 height:20 pos:[0, 0, 0]); c.name = "c"; c.material = mtl "TG_frame"
        local d = convertToMesh (Box length:100 width:100 height:10 pos:[0, 0, 0]); d.name = "d"; d.material = mtl "TG_frame"
        local r = removeCoincident (for o in geometry collect o)
        format "coincident_removed=%\n" r[1] to:f
        format "coincident_other_material=%\n" r[2] to:f
        format "kept=%\n" ((for o in geometry where isValidNode o collect o.name) as string) to:f
        -- a screen lying on a panel, in its plane: lifted off it; both touch face to face
        local panel = convertToMesh (Box length:200 width:200 height:10 pos:[2000, 0, 0]); panel.name = "panel"
        local screen = convertToMesh (Plane length:50 width:50 lengthsegs:1 widthsegs:1 pos:[2000, 0, 10])
        screen.name = "screen"
        format "lifted=%\n" (liftOverlaps #(panel, screen)) to:f
        format "screen_z=%\n" screen.min.z to:f
        format "contacts=%\n" LO_CONTACT.count to:f
        -- the same inside one mesh: a label (material 2) over a face of material 1
        local m2 = convertToMesh (Plane length:100 width:100 lengthsegs:1 widthsegs:1 pos:[3000, 0, 0])
        m2.name = "panel2"
        local l2 = convertToMesh (Plane length:20 width:20 lengthsegs:1 widthsegs:1 pos:[3000, 0, 0])
        for i = 1 to l2.mesh.numfaces do setFaceMatID l2.mesh i 2
        update l2
        meshop.attach m2 l2
        smoothRounds #(m2) 30.0 0 1
        format "label_lifted=%\n" SR_LIFTED to:f
        format "label_max_z=%\n" m2.max.z to:f
        -- a face twice
        local e = convertToMesh (Box length:50 width:50 height:50 pos:[500, 0, 0]); e.name = "e"
        local tm = e.mesh
        setNumFaces tm 13 true
        setFace tm 13 (getFace tm 1)
        update e
        -- a dense box with every face in one smoothing group: its edges are smoothed over
        local g = convertToMesh (Box length:100 width:100 height:100 lengthsegs:60 widthsegs:60 heightsegs:60 pos:[1000, 0, 0])
        g.name = "g"
        for i = 1 to g.mesh.numfaces do setFaceSmoothGroup g.mesh i 1
        update g
        smoothRounds #(e, g) 30.0 0 1
        format "dup_faces=%\n" SR_DUP_FACES to:f
        format "e_faces=%\n" e.mesh.numfaces to:f
        local sg = Dictionary #integer
        local sm = snapshotAsMesh g
        for i = 1 to sm.numfaces do sg[getFaceSmoothGroup sm i] = true
        format "dense_groups=%\n" sg.count to:f
        format "e_mods=%\n" ((for m in e.modifiers collect (classof m) as string) as string) to:f
        -- equipment far away, apart and above the floor: arranged in rows from the origin, on the floor, apart
        delete objects
        local eqs = #(Box length:500 width:2000 height:900 pos:[90000, 400000, 70], \
            Box length:900 width:1200 height:1500 pos:[95000, 380000, 70], Box length:300 width:300 height:300 pos:[0, 0, -20])
        local arr = arrangeEquipment eqs 100.0
        format "arranged=%\n" arr[1] to:f
        format "floor=%\n" ((for o in eqs collect (formattedPrint o.min.z format:".1f")) as string) to:f
        format "deepest_first=%\n" ((formattedPrint eqs[2].max.y format:".1f") + "," + (formattedPrint eqs[2].min.x format:".1f")) to:f
        local apart = true
        for i = 1 to 3 do for j = i + 1 to 3 do (
            local a = eqs[i]; local b = eqs[j]
            if a.min.x < b.max.x + 99 and b.min.x < a.max.x + 99 and a.min.y < b.max.y + 99 and b.min.y < a.max.y + 99 do apart = false
        )
        format "apart=%\n" apart to:f
        format "DONE\n" to:f
    ) catch (format "ERROR: %\n" (getCurrentException()) to:f)
    close f
)
cleanTest()
"""


@unittest.skipUnless(os.environ.get("ING_TEST_3DSMAX") == "1", "set ING_TEST_3DSMAX=1 to run the 3ds Max steps")
class CleanUpIn3dsMax(unittest.TestCase):
    def test_clean_up(self):
        exe = maxbatch.find_batch()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = tmp / "clean.ms"
            script.write_text(CLEAN, encoding="utf-8")
            runner = tmp / "run_clean.ms"
            runner.write_text(maxbatch.settings_script(script, {"ING_WORK": str(tmp) + "\\",
                                                                "ING_SCRIPTS": str(maxbatch.SCRIPTS) + "\\"}),
                              encoding="utf-8")
            subprocess.run([exe, str(runner), "-listenerLog", str(tmp / "clean_listener.log")], capture_output=True)
            lines = (tmp / "clean.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[-1], "DONE", lines)
            got = dict(ln.split("=", 1) for ln in lines if "=" in ln)
        self.assertEqual(got["coincident_removed"], "2")     # a and one of b / c; the thinner d stays
        self.assertEqual(got["coincident_other_material"], "1")
        self.assertNotIn('"a"', got["kept"])                 # the generic material gives way to the maker's
        self.assertIn('"d"', got["kept"])
        self.assertEqual(got["lifted"], "2")                 # the screen's two faces ...
        self.assertAlmostEqual(float(got["screen_z"]), 11.0, places=3)    # ... SR_LIFT_MM off the panel
        self.assertEqual(got["contacts"], "2")               # neither gets a TurboSmooth
        self.assertEqual(got["label_lifted"], "2")           # a label inside one mesh is lifted off its face too
        self.assertAlmostEqual(float(got["label_max_z"]), 1.0, places=3)
        self.assertEqual(got["dup_faces"], "1")
        self.assertEqual(got["e_faces"], "12")
        self.assertGreaterEqual(int(got["dense_groups"]), 2)  # the dense box's sides are no longer smoothed together
        self.assertIn("Weighted_Normals", got["e_mods"])     # a flat object keeps its flat faces flat
        self.assertEqual(got["arranged"], "3")
        self.assertEqual(got["floor"], '#("0.0", "0.0", "0.0")')
        self.assertEqual(got["deepest_first"], "0.0,0.0")     # the deepest at the back row's start
        self.assertEqual(got["apart"], "true")


if __name__ == "__main__":
    unittest.main()
