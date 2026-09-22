"""Geometry: cutting a triangulated mesh, cut levels, polyline helpers, contour smoothing."""
import unittest

import numpy as np
from scipy.interpolate import LinearNDInterpolator

from relief.geometry import terrain_mesh
from relief.geometry.polyline import arc_length, catmull_rom, control_points, crossing_pairs, max_deviation, rdp_mask
from relief.geometry.smoothing import clamped_nurbs, smooth_contour

SMOOTHING = {"reduce_tolerance_m": 0.0, "min_length_m": 10.0, "nurbs_degree": 3, "simplify_tolerance_m": 0.5,
             "max_control_spacing_m": 18.75}


def cone_mesh(peak=50.0, slope=0.5, radius=100.0, n_ring=200, grid=4.0):
    """A cone (height peak - slope * r) as a mesh dict like terrain_mesh.build_mesh returns."""
    a = np.linspace(0, 2 * np.pi, n_ring, endpoint=False)
    ring = np.column_stack([radius * np.cos(a), radius * np.sin(a)])
    g = np.arange(-radius, radius + grid, grid)
    xx, yy = np.meshgrid(g, g)
    inner = np.column_stack([xx.ravel(), yy.ravel()])
    inner = inner[np.hypot(*inner.T) < radius - 1.0]

    def z(xy):
        return peak - slope * np.hypot(*xy.T)

    return {"outline": np.column_stack([ring, z(ring)]), "holes": [], "points": np.column_stack([inner, z(inner)])}


class CutTest(unittest.TestCase):
    def setUp(self):
        self.mesh = cone_mesh()
        self.v, self.tri, self.triangles = terrain_mesh.triangulate(self.mesh)

    def test_closed_ring_on_the_level(self):
        lines = terrain_mesh.cut(self.v, self.triangles, 30.0)
        self.assertEqual(len(lines), 1)
        ring = lines[0]
        self.assertTrue(np.allclose(ring[0], ring[-1]), "a cut around a peak closes on itself")
        tin = LinearNDInterpolator(self.tri, self.v[:, 2])
        self.assertLess(np.nanmax(np.abs(tin(ring) - 30.0)), 1e-6, "every cut point lies on the mesh at the level")
        r = np.hypot(*ring.T)
        self.assertAlmostEqual(float(np.median(r)), 40.0, delta=1.0)  # (50 - 30) / 0.5

    def test_open_line_ends_on_outline(self):
        mesh = cone_mesh()
        mesh["outline"][:, 2] += mesh["outline"][:, 0] * 0.3  # tilt the rim so a low level leaves the mesh
        mesh["points"][:, 2] += mesh["points"][:, 0] * 0.3
        v, _, tris = terrain_mesh.triangulate(mesh)
        lines = terrain_mesh.cut(v, tris, 10.0)
        self.assertTrue(lines)
        for ln in lines:
            if not np.allclose(ln[0], ln[-1]):
                self.assertGreater(np.hypot(*ln[0]), 95.0, "open lines start and end on the outline")

    def test_no_line_outside_range(self):
        self.assertEqual(terrain_mesh.cut(self.v, self.triangles, 60.0), [])

    def test_levels_serve_every_size(self):
        np.testing.assert_allclose(terrain_mesh.cut_levels(0.2, 10.0, [2.0, 5.0]), np.arange(1.0, 11.0))
        np.testing.assert_allclose(terrain_mesh.cut_levels(0.0, 12.0, [2.0, 4.0]), np.arange(0.0, 13.0, 2.0))
        self.assertTrue(terrain_mesh.on_size(1215.0, 5.0))
        self.assertFalse(terrain_mesh.on_size(1216.0, 5.0))


class PolylineTest(unittest.TestCase):
    def test_rdp_zero_tolerance_drops_collinear_only(self):
        pts = np.array([[0, 0], [1, 0], [2, 0], [3, 1], [4, 2]], float)
        self.assertEqual(rdp_mask(pts, 1e-6).tolist(), [True, False, True, False, True])

    def test_control_points_of_closed_ring(self):
        a = np.linspace(0, 2 * np.pi, 101)
        ring = np.column_stack([10 * np.cos(a), 10 * np.sin(a)])
        ctrl = control_points(ring, True, 0.05, 5.0)
        self.assertFalse(np.allclose(ctrl[0], ctrl[-1]), "the closing point is dropped")
        self.assertLess(max_deviation(catmull_rom(ctrl, True), ring), 0.1)

    def test_crossing_pairs(self):
        a = np.array([[0, 0], [10, 10]], float)
        b = np.array([[0, 10], [10, 0]], float)
        c = np.array([[20, 0], [30, 0]], float)
        self.assertEqual(crossing_pairs([a, b, c]), 1)


class SmoothingTest(unittest.TestCase):
    def test_short_line_is_culled(self):
        self.assertIsNone(smooth_contour(np.array([[0, 0], [4, 3], [8, 0]], float), False, SMOOTHING))

    def test_wavy_line_is_smoothed_within_tolerance(self):
        x = np.linspace(0, 100, 201)
        pts = np.column_stack([x, 0.4 * np.sin(x)])
        out = smooth_contour(pts, False, SMOOTHING)
        self.assertIsNotNone(out)
        np.testing.assert_allclose(out["curve"][0], pts[0], atol=1e-9)  # clamped: keeps its end points
        np.testing.assert_allclose(out["curve"][-1], pts[-1], atol=1e-9)
        nurbs = clamped_nurbs(pts, 3)
        self.assertLessEqual(max_deviation(out["curve"], nurbs), SMOOTHING["simplify_tolerance_m"] + 1e-9)
        self.assertLess(np.abs(out["curve"][:, 1]).max(), 0.4, "the NURBS pulls towards, not through, the wiggles")
        self.assertLess(arc_length(out["curve"])[-1], arc_length(pts)[-1], "calmer than the input")

    def test_closed_line_stays_closed(self):
        a = np.linspace(0, 2 * np.pi, 81)
        ring = np.column_stack([20 * np.cos(a), 20 * np.sin(a)])
        out = smooth_contour(ring, True, SMOOTHING)
        np.testing.assert_allclose(out["curve"][0], out["curve"][-1], atol=1e-9)


if __name__ == "__main__":
    unittest.main()
