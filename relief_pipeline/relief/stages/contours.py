"""Stage contours: ONE terrain mesh from the clean DEM, then that mesh cut level by level.

1. Mesh: adaptive points of the DEM (at most mesh.target_points) inside one outline. Exactly these vertices become
   the Archicad Mesh, so the contours below lie on the mesh Archicad shows.
2. Cut: the triangulated mesh is intersected with horizontal planes on whole metres above sea level.
3. Smoothing of every cut line: Reduce -> cull short lines -> NURBS -> Simplify (contours.smoothing).
4. One layer per cut size (contours.cut_sizes_m): every level that is a multiple of that size.

Results: <pln work>/relief.gpkg (for the Archicad and QA stages), contours_summary.json, and
output/<pln>_ReliefOnly_contours.dxf (3D contours in PLN coordinates).
"""
import numpy as np
from scipy.interpolate import LinearNDInterpolator

from ..config import cut_sizes, settings
from ..geometry import terrain_mesh
from ..geometry.polyline import arc_length, crossing_pairs
from ..geometry.raster import read_raster, sample_raster
from ..geometry.smoothing import smooth_contour
from ..io.relief_data import write_contours_dxf, write_relief
from ..util import load_json, log, save_json
from .names import CONTOURS_SUMMARY, RELIEF_FILE
from .reference import load_placement


def _abs_stats(d):
    d = np.abs(d[np.isfinite(d)])
    if not len(d):
        return None
    return {"median": round(float(np.median(d)), 3), "p90": round(float(np.percentile(d, 90)), 3),
            "p95": round(float(np.percentile(d, 95)), 3), "max": round(float(d.max()), 3)}


def run(job, force=False):
    cfg = job.cfg
    out_gpkg, summary_path = job.p(RELIEF_FILE), job.p(CONTOURS_SUMMARY)
    ref, t, _, _ = load_placement(job)
    to_sea, to_pz = ref["source_to_sea_level"], ref["dz_source_to_project_zero"]
    wanted = settings(cfg, "mesh", "contours")
    previous = load_json(summary_path) or {}
    if not force and out_gpkg.exists() and abs(previous.get("source_to_sea_level", 1e9) - to_sea) < 1e-3 \
            and previous.get("settings") == wanted:
        log(f"contours: skip, {RELIEF_FILE} exists for this elevation reference and these settings")
        return

    z, gt, _ = read_raster(job.c("dem_clean.tif"))
    fp, _, _ = read_raster(job.c("footprint.tif"))
    valid = np.isfinite(z) & (np.nan_to_num(fp) > 0)

    # --- 1. one mesh
    log("contours: building the terrain mesh (adaptive points of the clean DEM, one outline) ...")
    mesh = terrain_mesh.build_mesh(z, gt, valid, job.c("footprint.tif"), cfg["mesh"])
    v, tri, triangles = terrain_mesh.triangulate(mesh)
    log(f"contours: mesh tolerance {mesh['tolerance']:.3f} m -> {len(mesh['points']):,} interior points, "
        f"outline {len(mesh['outline']):,}, holes {len(mesh['holes'])}, {len(triangles):,} triangles")
    tin = LinearNDInterpolator(tri, v[:, 2])
    rng = np.random.default_rng(0)
    rr, cc = np.nonzero(valid)
    pick = rng.choice(len(rr), size=min(300000, len(rr)), replace=False)
    qx, qy = gt[0] + (cc[pick] + 0.5) * gt[1], gt[3] + (rr[pick] + 0.5) * gt[5]
    mesh_vs_dem = tin(qx, qy) - z[rr[pick], cc[pick]]

    # --- 2. + 3. cut on whole metres a.s.l., smooth every line
    sizes = cut_sizes(cfg)
    smoothing = cfg["contours"]["smoothing"]
    levels = terrain_mesh.cut_levels(v[:, 2].min() + to_sea, v[:, 2].max() + to_sea, list(sizes.values()))
    log(f"contours: cutting the mesh at {len(levels)} levels {levels[0]:g}..{levels[-1]:g} m a.s.l. "
        f"for layers {', '.join(sizes)} ...")
    lines, n_cut, n_culled = [], 0, 0
    for e_abs in levels:
        if not any(terrain_mesh.on_size(e_abs, s) for s in sizes.values()):
            continue
        e_src = float(e_abs - to_sea)
        for pts in terrain_mesh.cut(v, triangles, e_src):
            n_cut += 1
            closed = len(pts) >= 4 and np.allclose(pts[0], pts[-1], atol=1e-6)
            smooth = smooth_contour(pts, closed, smoothing)
            if smooth is None:
                n_culled += 1
                continue
            curve = smooth["curve"]
            lines.append(dict(smooth, elev=e_src, elev_abs=round(float(e_abs), 3), closed=closed,
                              length=float(arc_length(curve)[-1]),
                              err_mesh_p95=float(np.nanpercentile(np.abs(tin(curve) - e_src), 95))))
    layers = {label: [ln for ln in lines if terrain_mesh.on_size(ln["elev_abs"], s)] for label, s in sizes.items()}

    # --- checks (reported only): line heights on the mesh and on the DEM, crossings
    on_mesh = np.concatenate([tin(ln["curve"]) - ln["elev"] for ln in lines]) if lines else np.zeros(0)
    on_dem = np.concatenate([sample_raster(z, gt, ln["curve"]) - ln["elev"] for ln in lines]) if lines else np.zeros(0)
    finest = next(iter(layers))

    write_relief(out_gpkg, mesh, layers, to_pz)
    write_contours_dxf(job.output_dxf, t, layers)
    log(f"contours: wrote {out_gpkg} and {job.output_dxf}")

    stats = {
        "source_to_sea_level": to_sea,
        "mesh": {"pieces": 1, "interior_points": int(len(mesh["points"])),
                 "outline_vertices": int(len(mesh["outline"])), "holes": len(mesh["holes"]),
                 "triangles": int(len(triangles)), "point_tolerance_used_m": round(mesh["tolerance"], 4),
                 "area_m2": round(float(mesh["polygon"].area), 1), "error_vs_dem_m": _abs_stats(mesh_vs_dem)},
        "cut": {"levels_m_asl": [float(levels[0]), float(levels[-1])], "lines_cut": n_cut,
                "culled_not_longer_than_m": [n_culled, smoothing["min_length_m"]], "lines_kept": len(lines)},
        "layers": {label: {"every_m": sizes[label], "lines": len(ls),
                           "spline_points": int(sum(len(ln["ctrl"]) for ln in ls))} for label, ls in layers.items()},
        "line_height_error_on_mesh_m": _abs_stats(on_mesh),
        "line_height_error_vs_dem_m": _abs_stats(on_dem),
        f"crossing_pairs_{finest}": crossing_pairs([ln["curve"] for ln in layers[finest]]),
        "settings": wanted,
    }
    save_json(summary_path, stats)
    for k, val in stats.items():
        if k != "settings":
            log(f"contours: {k} = {val}")
