"""Tests of the AutoCAD -> Archicad site tool on synthetic data (no AutoCAD, Archicad or network needed).

Run:  "%LOCALAPPDATA%\\ing_studio_toolkit\\autocad_to_archicad\\env\\.venv\\Scripts\\python.exe" -m unittest discover -s tests
"""
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acad.io import armscii  # noqa: E402


class Armscii(unittest.TestCase):
    def test_decodes_armenian_layer_names(self):
        self.assertEqual(armscii.maybe_decode("Þ»Ýù_²í³ñïí³Í ê³ÑÙ³Ý")[0], "Շենք_Ավարտված Սահման")

    def test_leaves_french_and_plain_text(self):
        for s in ("Réalisé en béton", "PHASE 3 SITE BOUNDARY", "ALT.+1080.70 m", "Straße"):
            self.assertEqual(armscii.maybe_decode(s), (s, False))


class DrawingModel(unittest.TestCase):
    """Blocks: nested, mirrored, on layer 0, ByBlock colour; units; text."""

    def make(self, path):
        import ezdxf
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4  # mm
        doc.layers.add("WALLS", color=1)
        doc.layers.add("TREES", color=3)
        inner = doc.blocks.new("INNER")
        inner.add_arc((1000, 0), 500, 0, 90, dxfattribs={"layer": "0", "color": 0})  # layer 0, ByBlock
        outer = doc.blocks.new("OUTER")
        outer.add_blockref("INNER", (0, 0), dxfattribs={"layer": "0", "color": 0})  # ByBlock all the way down
        outer.add_line((0, 0), (2000, 0), dxfattribs={"layer": "WALLS"})
        msp = doc.modelspace()
        msp.add_blockref("OUTER", (10000, 5000), dxfattribs={"layer": "TREES", "color": 5})
        msp.add_blockref("OUTER", (20000, 5000), dxfattribs={"layer": "TREES", "xscale": -1})  # mirrored
        msp.add_text("Þ»Ýù", dxfattribs={"height": 1500, "layer": "WALLS"}).set_placement((0, 0))
        doc.saveas(path)

    def test_flatten(self):
        from acad.io.dxf_model import header_units, read_model
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "b.dxf"
            self.make(p)
            doc, prims, layers, stats = read_model(p, tol=5.0)
            self.assertEqual(header_units(doc), 0.001)
            arcs = [q for q in prims if q["kind"] in ("arc", "poly") and q["layer"] == "TREES"]
            self.assertEqual(len(arcs), 2, "the arcs on layer 0 take the block reference's layer")
            normal = next(q for q in arcs if q["kind"] == "arc")
            self.assertEqual(normal["color"], 5, "ByBlock colour comes from the reference")
            self.assertTrue(np.allclose(normal["c"], [11000, 5000]))
            mirrored = next(q for q in arcs if q is not normal)
            xy = mirrored["xy"]  # a mirrored arc becomes a polyline in world coordinates
            self.assertTrue(np.all(xy[:, 0] <= 20000 - 500 + 1) and np.all(xy[:, 0] >= 20000 - 1500 - 1))
            walls = [q for q in prims if q["layer"] == "WALLS" and q["kind"] == "poly"]
            self.assertEqual(len(walls), 2)
            text = next(q for q in prims if q["kind"] == "text")
            self.assertEqual(text["text"], "Շենք")


class Registration(unittest.TestCase):
    def test_rotation_and_shift_are_recovered(self):
        from acad.geometry.crs import Rigid2D
        from acad.geometry.register import icp, rotation_search, to_rigid
        rng = np.random.default_rng(1)
        boxes = []
        for _ in range(60):  # a small 'town' of rectangles
            x, y = rng.uniform(0, 400, 2)
            w, h = rng.uniform(8, 25, 2)
            for t in np.linspace(0, 1, 30):
                boxes += [(x + w * t, y), (x + w, y + h * t), (x + w * (1 - t), y + h), (x, y + h * (1 - t))]
        P = np.array(boxes)
        truth = Rigid2D(math.radians(17.0), 5000.0, -3000.0)
        Q = truth.apply(P) + rng.normal(0, 0.2, P.shape)
        res = rotation_search(P, Q, 2.0, np.arange(-180, 180, 2.0))
        self.assertGreater(res["peak_ratio"], 2.0)
        fit, stats = icp(P, Q, to_rigid(res))
        self.assertAlmostEqual(math.degrees(fit.angle), 17.0, delta=0.1)
        self.assertLess(np.abs(fit.apply(P) - truth.apply(P)).max(), 0.5)


class Profile(unittest.TestCase):
    """The network profile keeps every rule and joins at the tie-in."""

    def test_rules(self):
        from acad.roads.proposed import design_profile
        cfg = {"roads": {"profile": {"serpentine_max_grade_permille": 40, "serpentine_radius_m": 30,
                                     "tie_in_tolerance_m": 0.02, "tie_in_weight": 500, "exceptional_grade_cost": None}}}
        std = {"max_grade_permille": 80, "crest_radius_m": 1000, "sag_radius_m": 600}
        s = np.arange(0, 301, 5.0)
        ground = 100 + 0.15 * s  # 150 per mille: too steep for the rules
        e1 = {"xy": np.column_stack([s, 0 * s]), "s": s, "ground": ground, "radius": np.full(len(s), np.inf),
              "nodes": (0, 1)}
        s2 = np.arange(0, 101, 5.0)
        e2 = {"xy": np.column_stack([300 + 0 * s2, s2]), "s": s2, "ground": np.full(len(s2), 145.0),
              "radius": np.r_[np.full(10, np.inf), np.full(len(s2) - 10, 20.0)], "nodes": (1, 2)}
        summary = design_profile([e1, e2], {0: 100.0}, cfg, std)
        self.assertAlmostEqual(e1["z"][0], 100.0, delta=0.03)
        self.assertAlmostEqual(e1["z"][-1], e2["z"][0], places=6)  # one height at the junction
        for e in (e1, e2):
            g = np.abs(np.diff(e["z"]) / np.diff(e["s"]))
            lim = np.minimum(e["limit"][:-1], e["limit"][1:])
            self.assertTrue(np.all(g <= lim + 1e-6))
            dg = np.diff(np.diff(e["z"]) / 5.0)
            self.assertTrue(np.all(dg <= 5.0 / 600 + 1e-6) and np.all(dg >= -5.0 / 1000 - 1e-6))
        self.assertEqual(summary["grade_limit_raised_by_permille"], 0.0)


    def test_exceptional_grade_only_where_it_pays(self):
        from acad.roads.proposed import design_profile
        cfg = {"roads": {"profile": {"serpentine_max_grade_permille": 40, "serpentine_radius_m": 30,
                                     "tie_in_tolerance_m": 0.02, "tie_in_weight": 500, "exceptional_grade_cost": 0.03}}}
        std = {"max_grade_permille": 90, "exceptional_grade_permille": 120, "crest_radius_m": 570, "sag_radius_m": 180}
        s = np.arange(0, 401, 5.0)
        ground = 100 + np.where(s < 100, 0.12 * s, 12 + 0.02 * (s - 100))  # a 100 m ramp of 120 per mille
        e = {"xy": np.column_stack([s, 0 * s]), "s": s, "ground": ground, "radius": np.full(len(s), np.inf),
             "nodes": (0, 1), "name": "a"}
        summary = design_profile([e], {}, cfg, std)
        g = np.abs(np.diff(e["z"]) / np.diff(s))
        self.assertLessEqual(g.max(), 0.120 + 1e-6)
        self.assertGreater(g.max(), 0.095, "the steep ground is followed with the exceptional grade")
        used = sum(x["length_m"] for x in summary["exceptional_stretches"])
        self.assertLessEqual(used, 150)


    def test_streets_side_by_side_share_the_paving(self):
        from shapely.geometry import LineString
        from shapely.ops import unary_union
        from acad.roads.proposed import design_profile
        cfg = {"roads": {"profile": {"serpentine_max_grade_permille": 40, "serpentine_radius_m": 30,
                                     "tie_in_tolerance_m": 0.02, "tie_in_weight": 500, "exceptional_grade_cost": None}}}
        std = {"max_grade_permille": 90, "crest_radius_m": 570, "sag_radius_m": 180}
        s = np.arange(0, 81, 5.0)
        a = math.radians(3.0)

        def street(sign, slope):  # a fork: two streets leave one node 6 deg apart, on rising / falling ground
            return {"xy": np.column_stack([s * math.cos(a), sign * s * math.sin(a)]), "s": s, "ground": 100 + slope * s,
                    "radius": np.full(len(s), np.inf), "half_w": np.full(len(s), 3.0), "nodes": (0, 1 if sign > 0 else 2),
                    "name": f"street {sign}"}
        e1, e2 = street(1, 0.08), street(-1, -0.08)
        car = unary_union([LineString(e["xy"]).buffer(3.0) for e in (e1, e2)])
        design_profile([e1, e2], {}, cfg, std, car)
        d = np.hypot(*(e1["xy"] - e2["xy"]).T)
        near = (d > 0.5) & (d <= 5.5)  # their carriageways overlap: one paved area
        self.assertTrue(np.all(np.abs(e1["z"] - e2["z"])[near] <= 0.09 * d[near] + 1e-6))
        e3, e4 = street(1, 0.08), street(-1, -0.08)
        design_profile([e3, e4], {}, cfg, std)  # without the carriageway: each follows its own ground
        self.assertGreater(np.abs(e3["z"] - e4["z"])[near].max(), 0.09 * d[near].max())


class StreetSurface(unittest.TestCase):
    """Street surfaces: continuous along bends, smooth across junctions, a step between streets on other levels."""

    @staticmethod
    def _edge(xy, grade=0.0, z0=100.0, hw=3.0):
        s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        return {"xy": xy, "s": s, "z": z0 + grade * s, "half_w": np.full(len(xy), hw)}

    def test_continuous_along_a_bend(self):
        from acad.roads.network import RoadNet
        t = np.radians(np.arange(0, 181, 15.0))  # a hairpin of radius 12 m, stations 3 m apart
        net = RoadNet([self._edge(np.column_stack([12 * np.cos(t), 12 * np.sin(t)]), 0.08)], None, 0.02)
        u = np.radians(np.linspace(0, 180, 2000))
        z = net.surface_z(np.column_stack([9.5 * np.cos(u), 9.5 * np.sin(u)]))  # 2.5 m inside the bend
        self.assertLess(np.abs(np.diff(z)).max(), 0.02)

    def test_junction_and_level_step(self):
        from acad.roads.network import RoadNet
        x = np.arange(-50, 51, 5.0)
        y = np.arange(0, 51, 5.0)
        main = self._edge(np.column_stack([x, 0 * x]))
        side = self._edge(np.column_stack([0 * y, y]), 0.08)  # climbs away from the junction at 8 %
        net = RoadNet([main, side], None, 0.02, blend_m=1.0)
        xs = np.linspace(-10, 10, 800)
        z = net.surface_z(np.column_stack([xs, np.full(len(xs), 3.5)]))  # across the side street's mouth
        self.assertLess(np.abs(np.diff(z)).max(), 0.02)
        low, high = self._edge(np.column_stack([x, 0 * x])), self._edge(np.column_stack([x, 8 + 0 * x]), z0=103.0)
        z = RoadNet([low, high], None, 0.02, blend_m=1.0).surface_z(np.array([[0.0, 3.0], [0.0, 5.0]]))
        self.assertTrue(np.allclose(z, [100.0 - 0.06, 103.0 - 0.06], atol=0.01), "3 m apart in height: a step")


class Standards(unittest.TestCase):
    def test_design_speed_by_terrain(self):
        from acad.config import load_config
        from acad.roads.standards import resolve, terrain_category
        cfg = load_config(use_project=False)
        cat, _ = terrain_category(cfg, 330.0)
        self.assertEqual(cat, "mountainous")
        std = resolve(cfg, "local", cat)
        self.assertEqual((std["design_speed_kmh"], std["max_grade_permille"], std["min_radius_m"]), (30, 90, 30))
        self.assertEqual((std["crest_radius_m"], std["sag_radius_m"]), (570, 180))
        self.assertEqual(resolve(cfg, "local", "normal")["design_speed_kmh"], 40)
        self.assertEqual(resolve(cfg, "district", "rugged")["lane_m"], 3.3)


class Units(unittest.TestCase):
    def test_inch_header_on_a_mm_drawing(self):
        from acad.stages.read import check_units
        rng = np.random.default_rng(3)
        prims = []
        for _ in range(40):  # 10-30 m buildings drawn in mm
            x, y = rng.uniform(0, 5e5, 2)
            w, h = rng.uniform(10000, 30000, 2)
            prims.append({"kind": "poly", "closed": True, "xy": np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])})
        unit, note = check_units(prims, 0.0254)
        self.assertEqual(unit, 0.001)
        self.assertIsNotNone(note)
        self.assertEqual(check_units(prims, 0.001), (0.001, None))


class PdfDocuments(unittest.TestCase):
    """Statements, a table with legend colours and a red outline read back from a generated PDF."""

    def test_read(self):
        import pymupdf
        from acad.io import pdf_doc as P
        doc = pymupdf.open()
        page = doc.new_page(width=1190, height=842)
        page.insert_text((800, 100), "UNDERGROUND PARKING", fontsize=12)
        page.insert_text((800, 120), "B1 B2 21900 SQM", fontsize=12)
        rows = [("APART HOTEL", 90350, (0.87, 0.72, 0.2)), ("COMMERCIAL", 29450, (1, 0, 0)), ("TOTAL", 119800, None)]
        page.insert_text((800, 300), "FUNCTION", fontsize=10)
        page.insert_text((950, 300), "AREA", fontsize=10)
        for i, (label, v, rgb) in enumerate(rows):
            y = 325 + 22 * i
            if rgb:
                page.draw_rect(pymupdf.Rect(760, y - 12, 790, y + 2), color=None, fill=rgb)
            page.insert_text((800, y), label, fontsize=10)
            page.insert_text((950, y), str(v), fontsize=10)
        # a 100 m x 60 m area outlined in red at 1:1000 (100 mm x 60 mm on paper), line 1 mm
        mm = 72 / 25.4
        page.draw_rect(pymupdf.Rect(100, 100, 100 + 100 * mm, 100 + 60 * mm), color=(1, 0, 0), width=1 * mm)
        ws = P.words(page)
        text = P.page_text(ws)
        self.assertEqual(P.area_statements(text), [(["B1", "B2"], 21900.0)])
        t = [t for t in P.tables(page, ws) if len(t["rows"]) >= 2][0]
        self.assertEqual([(r["label"], r["value"]) for r in t["rows"]], [(l, v) for l, v, _ in rows])
        self.assertEqual(t["rows"][1]["rgb"], [255, 0, 0])
        self.assertIn("AREA", t["header"])
        dpi = 150
        img = P.render(page, dpi)
        (poly, width, _), = P.marked_areas(img, [255, 0, 0], 70, min_px=5000)  # not the red legend swatch
        px_m = 0.0254 / dpi * 1000
        self.assertAlmostEqual(poly.area * px_m ** 2, 6000.0, delta=60.0)  # within 1 %


class Shadows(unittest.TestCase):
    """Storeys from drawn shadows: footprints slid along 135 deg by 0.7 m per storey."""

    def test_storeys(self):
        from shapely.geometry import box
        from acad import buildings as B
        d = np.array([math.cos(math.radians(135)), math.sin(math.radians(135))])
        faces, shadows, want = [], [], []
        for i, n in enumerate([6, 10, 10, 6, 16, 10]):
            f = box(i * 40.0, 0.0, i * 40.0 + 20.0, 24.0)
            v = 0.7 * n * d
            faces.append(f)
            shadows.append(B._sweep(f, v).difference(f).buffer(0))  # the shadow as drawn: without the building
            want.append(n)
        direction = B.shadow_direction(faces, shadows)
        self.assertAlmostEqual(direction, 135.0, delta=1.0)
        casters = B.shadow_lengths(faces, shadows, direction)
        self.assertEqual(len(casters), len(faces))
        step, fit = B.storey_step([c[1] for c in casters])
        self.assertIn(round(step, 2), (0.7, 1.4))  # 6, 10, 16 are all even: 1.4 fits as well; the documents decide
        options = [round(q, 2) for q, _ in B.storey_aliases([c[1] for c in casters], step)]
        self.assertIn(0.7, options)
        got = sorted((j, round(length / 0.7)) for j, length, _ in casters)
        self.assertEqual([n for _, n in got], want)

    def test_odd_storeys_decide(self):
        from acad import buildings as B
        even = [0.7 * n for n in (6, 10, 10, 6, 16, 10, 6, 6, 10, 10, 16, 6)]
        self.assertAlmostEqual(B.storey_step(even)[0], 1.4, places=2)  # all even: the larger step fits
        self.assertAlmostEqual(B.storey_step(even + [0.7 * 17])[0], 1.4, places=2)  # one odd one: a slip
        self.assertAlmostEqual(B.storey_step(even + [0.7 * 17, 0.7 * 9])[0], 0.7, places=2)  # two: the half step



def _volume(verts, faces):
    """Volume of a closed body (faces may be (outer, [holes]) planar loops)."""
    V = np.array(verts, dtype=float)
    vol = 0.0
    for f in faces:
        for q in ([f[0]] + list(f[1]) if isinstance(f, tuple) else [f]):
            vol += sum(np.dot(V[q[0]], np.cross(V[q[i]], V[q[i + 1]])) / 6 for i in range(1, len(q) - 1))
    return vol


class Bodies(unittest.TestCase):
    """Morph bodies: closed, facing outwards, the right volume."""

    def test_prism_with_a_hole(self):
        from shapely.geometry import Polygon
        from acad.geometry.bodies import is_closed, prism
        v, f = prism(Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(3, 3), (3, 6), (6, 6), (6, 3)]]), 2.0, 7.0)
        self.assertTrue(is_closed(f))
        self.assertAlmostEqual(_volume(v, f), 91 * 5.0, places=6)
        self.assertEqual(sum(isinstance(x, tuple) for x in f), 2, "one flat face on top, one below")

    def test_street_body_follows_the_surface(self):
        from shapely.geometry import Polygon
        from acad.geometry.bodies import is_closed, surface_body
        # an L-shaped street with a hole (an island), rising 5 % along x
        poly = Polygon([(0, 0), (40, 0), (40, 7), (7, 7), (7, 30), (0, 30)], [[(2, 2), (4, 2), (4, 4), (2, 4)]])
        zf = lambda xy: 100.0 + 0.05 * xy[:, 0]
        v, f = surface_body(poly, zf, 0.3, cell=2.0)
        self.assertTrue(is_closed(f))
        self.assertAlmostEqual(_volume(v, f), poly.area * 0.3, delta=0.01 * poly.area * 0.3)
        V = np.array(v)
        top = V[: len(V) // 2]
        self.assertTrue(np.allclose(top[:, 2], zf(top[:, :2]), atol=1e-3))


class Layers(unittest.TestCase):
    """Layer roles from geometry: tree symbols, and axis lines along the middle of hatched street strips."""

    def _site(self, prims):
        return {"prims": prims, "layers": {p["layer"]: {"name": p["layer"]} for p in prims},
                "bbox": [-20.0, -40.0, 220.0, 60.0]}

    def test_roles(self):
        from acad import layers as L
        from acad.config import load_config
        cfg = load_config(use_project=False)
        prims = []
        for i in range(30):  # tree symbols: crown fills + trunk circles
            c = np.array([10.0 * i, 40.0])
            ang = np.linspace(0, 2 * np.pi, 24, endpoint=False)
            prims.append({"kind": "fill", "layer": "X-GREEN", "rings": [c + 2.5 * np.column_stack([np.cos(ang), np.sin(ang)])]})
            prims.append({"kind": "circle", "layer": "X-GREEN", "c": c, "r": 0.8})
        # a street strip 7 m wide with a bend, its axis, and plain building rectangles elsewhere
        strip = [np.array([[0, -3.5], [150, -3.5], [150, -40], [157, -40], [157, 3.5], [0, 3.5]], float)]
        prims.append({"kind": "fill", "layer": "Q-4", "rings": strip})
        prims.append({"kind": "poly", "layer": "Q-7", "closed": False, "xy": np.array([[0, 0], [153.5, 0], [153.5, -40.0]])})
        for i in range(20):
            prims.append({"kind": "poly", "layer": "Q-9", "closed": True,
                          "xy": np.array([[10 * i, 10], [10 * i + 6, 10], [10 * i + 6, 18], [10 * i, 18]], float)})
        site = self._site(prims)
        by = L.by_layer(site)
        trees, _ = L.tree_layers(by, site["layers"], cfg)
        self.assertEqual(trees, ["X-GREEN"])
        car, axes, _ = L.street_layers(by, site["layers"], site, cfg, exclude=set(trees))
        self.assertEqual((car, axes), (["Q-4"], ["Q-7"]))


class PlaceNames(unittest.TestCase):
    def test_names_and_country(self):
        from acad.io.geocode import country_hint, phrases
        self.assertEqual(phrases(["Cascade siteplan", "Ground points Cascad - Cloud", "260824-Cascade Arts District"])[:1],
                         ["Cascade"])
        self.assertEqual(country_hint(["2918_R_SITE$0$Շենք_Ստորգետնյա Սահման", "WIL_VOIRIE"]), "am")
        self.assertIsNone(country_hint(["MP_BUILDINGS"]))


class KerbRadius(unittest.TestCase):
    def test_rounded_junction(self):
        from shapely.geometry import box
        from shapely.ops import unary_union
        from acad.roads.checks import kerb_radii
        cross = unary_union([box(-100, -4, 100, 4), box(-4, -100, 4, 100)])
        rounded = cross.buffer(12, join_style=1).buffer(-12, join_style=1)  # kerb returns of 12 m
        (j, xy, r), = kerb_radii(rounded, np.array([[0.0, 0.0]]), np.array([4]))
        self.assertAlmostEqual(r, 12.0, delta=1.5)
        (j, xy, r), = kerb_radii(cross, np.array([[0.0, 0.0]]), np.array([4]))
        self.assertLess(r, 1.0, "a sharp drawn corner")


class Skeleton(unittest.TestCase):
    def test_centre_line_of_a_street(self):
        from shapely.geometry import Polygon
        from acad.roads.geometry import skeleton
        v, chains = skeleton(Polygon([(0, 0), (200, 0), (200, 8), (0, 8)]), 0.5, 12.0)
        longest = max((v[c] for c in chains), key=lambda xy: np.hypot(*np.diff(xy, axis=0).T).sum())
        self.assertTrue(np.allclose(longest[:, 1], 4.0, atol=0.3))
        self.assertGreater(np.ptp(longest[:, 0]), 180)


class SideSlopes(unittest.TestCase):
    def test_fill_slope_from_a_raised_street(self):
        from acad.stages.earthworks import side_slopes
        res = 0.5
        X, Y = np.meshgrid(np.arange(0, 60, res) + res / 2, np.arange(0, 40, res)[::-1] + res / 2)
        PR = np.abs(Y - 20) <= 3
        top = np.where(PR, 10.0, np.nan)
        rr, cc = np.nonzero(PR)
        seg = (X[rr, cc] // 40.0).astype(int)
        lo, hi, near_lo, near_hi, d = side_slopes(PR.shape, rr, cc, seg, top, res, 10.0, 1.5, 1.5)
        r, c = 0, 60  # the far row: 17 m from the street edge -> beyond the reach
        self.assertTrue(np.isnan(d[r, c]))
        i = np.argmin(np.abs(Y[:, 0] - 13.25))  # ~6.5 m from the edge
        self.assertAlmostEqual(lo[i, 60], 10.0 - (20 - 3 - Y[i, 0]) / 1.5, delta=0.35)


class Vendored(unittest.TestCase):
    """Files copied from the relief tool must stay identical to it (update both together)."""

    def test_same_as_relief(self):
        import hashlib
        import json
        here = Path(__file__).resolve().parent.parent
        info = json.loads((here / "acad" / "VENDORED_FROM.json").read_text(encoding="utf-8"))
        relief = here.parent / info["source_tool"]
        if not relief.exists():
            self.skipTest("relief tool not next to this one")
        for mine, meta in info["files"].items():
            a = hashlib.sha256((here / mine).read_bytes()).hexdigest()
            b = hashlib.sha256((relief / meta["source"]).read_bytes()).hexdigest()
            self.assertEqual(a, b, f"{mine} differs from {meta['source']} - copy the change to both tools")


if __name__ == "__main__":
    unittest.main()
