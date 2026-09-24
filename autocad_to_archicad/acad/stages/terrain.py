"""Stage terrain: the existing terrain in drawing coordinates, altitudes in metres above sea level.

From the point cloud: the relief tool builds its clean bare-earth terrain model (relief.bat CLOUD --until dem, reused
from its cache when it was built before). A ground-only cloud has holes where buildings stand; those holes are matched
to the drawing's building outlines (every rotation, then fine), which places the cloud on the drawing. A survey
aligned to true north shows up as a small rotation (the map grid convergence, reported). Point cloud heights are often
local; cloud.z_to_altitude (auto: the open world terrain model over open ground) turns them into altitudes.
Results: terrain_existing.tif (drawing metres, north up), terrain.json (placement, altitude offset, outline).
"""
import json
import math
import os
import subprocess
from pathlib import Path

import numpy as np
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import unary_union

from ..config import settings
from ..geometry.crs import LonLatUTM, Rigid2D
from ..geometry.raster import read_raster, sample_raster, write_raster
from ..geometry.register import densify_polylines, peak_angle, rotation_search, to_rigid
from ..io import world_dem
from ..site import load_site, on_layers, polylines
from ..util import PIPELINE_DIR, detail, load_json, log, save_json, skip, slug


# --------------------------------------------------------------------------- relief tool
def relief_cache(cfg, cloud):
    """The relief tool's work folder of this cloud (its Job.cloud_dir rule: <work>/<slug of the file name>)."""
    base = cfg["paths"]["relief_work_dir"]
    if not base:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "ing_studio_toolkit" / "pointcloud_to_archicad_relief"
    return Path(base) / slug(Path(cloud).stem)


def run_relief_dem(cfg, cloud):
    """The relief tool's clean terrain model of the cloud; returns its cache folder."""
    tool_dir = Path(cfg["paths"]["relief_tool"] or PIPELINE_DIR.parent / "pointcloud_to_archicad_relief")
    bat = tool_dir / "relief.bat"
    if not bat.exists():
        raise RuntimeError(f"the relief tool is needed for the point cloud terrain and was not found at {tool_dir} "
                           "(set paths.relief_tool)")
    cache = relief_cache(cfg, cloud)
    log("terrain: terrain model of the point cloud by the relief tool (reused if it was built before) ...")
    args = f'"{bat}" "{cloud}" --until dem'
    if cfg["paths"]["relief_work_dir"]:
        args += f' --cache "{cfg["paths"]["relief_work_dir"]}"'
    # cmd /s /c "..." keeps the inner quotes of paths with spaces (plain cmd /c strips the first and last quote)
    p = subprocess.run(f'cmd /s /c "{args}"', capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=str(tool_dir))
    for line in p.stdout.splitlines():
        if any(k in line for k in (" SKIP ", " OK ", " WARN ", " FAIL ", "  INFO  ground", "  INFO  dem", "  INFO  cloud")):
            detail("relief: " + line.split("  ", 2)[-1].strip())
    if p.returncode != 0:
        raise RuntimeError(f"the relief tool failed (exit code {p.returncode}); its log is in {cache}\\pipeline.log\n"
                           + p.stdout[-2000:] + p.stderr[-1000:])
    for f in ("dem_clean.tif", "count.tif", "footprint.tif"):
        if not (cache / f).exists():
            raise RuntimeError(f"the relief tool did not leave {f} in {cache}")
    return cache


# --------------------------------------------------------------------------- placing the cloud
def building_mask(site, names, res, margin=20.0):
    """Filled building outlines of the drawing as an image (rows increase with y): (image, x0, y0)."""
    pts = densify_polylines(polylines(on_layers(site, names)), res / 2)
    x0, y0 = pts.min(axis=0) - margin
    W = int((pts[:, 0].max() - x0 + margin) / res) + 1
    H = int((pts[:, 1].max() - y0 + margin) / res) + 1
    g = np.zeros((H, W), bool)
    g[((pts[:, 1] - y0) / res).astype(int), ((pts[:, 0] - x0) / res).astype(int)] = True
    return ndimage.binary_fill_holes(g).astype(np.float32), float(x0), float(y0)


def cloud_holes(count, gt, step_px=2):
    """Cell centres (cloud coordinates) of the gaps buildings leave in the ground points."""
    px = abs(gt[1])
    cov = ndimage.binary_opening(np.nan_to_num(count) > 0, iterations=1)
    hull = ndimage.binary_erosion(ndimage.binary_closing(cov, iterations=int(15 / px)), iterations=int(4 / px))
    holes = ndimage.binary_opening(hull & ~cov, iterations=2)
    rr, cc = np.nonzero(holes[::step_px, ::step_px])
    rr, cc = rr * step_px, cc * step_px
    return np.column_stack([gt[0] + (cc + 0.5) * gt[1], gt[3] + (rr + 0.5) * gt[5]])


def place_cloud(job, cache):
    cfg = job.cfg["cloud"]
    if cfg["mode"] == "manual":
        rigid = Rigid2D(math.radians(float(cfg["manual_rotation_deg"])), *cfg["manual_origin_dwg_m"])
        log(f"terrain: manual placement of the point cloud: rotation {cfg['manual_rotation_deg']} deg, "
            f"cloud 0,0 = drawing {cfg['manual_origin_dwg_m']} m")
        return rigid, {"method": "manual"}
    count, gt, _ = read_raster(cache / "count.tif")
    holes = cloud_holes(count, gt)
    site = load_site(job)
    names = load_json(job.w("georef.json"))["building_layers"]
    log(f"terrain: matching {len(holes):,} building gaps of the point cloud to the drawing's buildings ...")
    img2 = building_mask(site, names, 2.0)
    coarse = rotation_search(holes, None, 2.0, np.arange(-180.0, 180.0, 2.0), sigma_px=0.5, fixed_image=img2)
    if coarse["peak_ratio"] < float(cfg["min_peak_ratio"]):
        raise RuntimeError(f"terrain: the point cloud could not be placed on the drawing (peak ratio "
                           f"{coarse['peak_ratio']:.2f} < {cfg['min_peak_ratio']}); set cloud.mode=manual")
    img1 = building_mask(site, names, 1.0)
    fine = rotation_search(holes, None, 1.0, np.arange(coarse["angle_deg"] - 2.0, coarse["angle_deg"] + 2.001, 0.05),
                           coarse["T"], 6.0, sigma_px=0.5, fixed_image=img1)
    angle = peak_angle(fine)
    final = rotation_search(holes, None, 1.0, [angle], fine["T"], 4.0, sigma_px=0.5, fixed_image=img1)
    rigid = to_rigid(final)
    stats = {"method": "building_gaps", "peak_ratio": coarse["peak_ratio"], "best_angle_deg": fine["angle_deg"],
             "fitted_angle_deg": angle, "coarse_scores": coarse["scores"][:30], "fine_scores": sorted(fine["scores"])}
    return rigid, stats


def z_offset(job, cache, rigid, g2u, tr):
    """Metres to add to cloud heights: median (world terrain - cloud) over open ground, with its spread."""
    zc = job.cfg["cloud"]
    if zc["z_to_altitude"] != "auto":
        return float(zc["z_to_altitude"]), {"method": "setting"}
    dem, gt, _ = read_raster(cache / "dem_clean.tif")
    ng, _, _ = read_raster(cache / "nonground_count.tif") if (cache / "nonground_count.tif").exists() else (None, 0, 0)
    open_ground = np.isfinite(dem)
    if ng is not None:
        open_ground &= ~ndimage.binary_dilation(np.nan_to_num(ng) > 0, iterations=int(10 / abs(gt[1])))
    step = max(1, int(10 / abs(gt[1])))
    rr, cc = np.nonzero(open_ground[::step, ::step])
    rr, cc = rr * step, cc * step
    if len(rr) < 50:
        rr, cc = np.nonzero(np.isfinite(dem)[::step, ::step])
        rr, cc = rr * step, cc * step
    xy = np.column_stack([gt[0] + (cc + 0.5) * gt[1], gt[3] + (rr + 0.5) * gt[5]])
    lonlat = tr.to_lonlat(g2u.apply(rigid.apply(xy)))
    world = world_dem.heights(lonlat, zc["world_terrain_url"], int(zc["world_terrain_zoom"]))
    d = world - dem[rr, cc]
    d = d[np.isfinite(d)]
    if len(d) < 20:
        raise RuntimeError("terrain: no world terrain heights for the site (network?) - set cloud.z_to_altitude")
    off = float(np.median(d))
    mad = float(np.median(np.abs(d - off)))
    return off, {"method": "world_terrain", "samples": int(len(d)), "mad_m": round(mad, 2),
                 "p10_p90": [round(float(np.percentile(d, 10)), 2), round(float(np.percentile(d, 90)), 2)]}


# --------------------------------------------------------------------------- stage
def outline_polygon(valid, gt, simplify):
    """The largest connected area of `valid` as a polygon (drawing metres)."""
    from osgeo import gdal, ogr
    drv = gdal.GetDriverByName("MEM")
    ds = drv.Create("", valid.shape[1], valid.shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    band = ds.GetRasterBand(1)
    band.WriteArray(valid.astype(np.uint8))
    vds = (ogr.GetDriverByName("MEM") or ogr.GetDriverByName("Memory")).CreateDataSource("o")
    lyr = vds.CreateLayer("o", geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, band, lyr, 0)
    polys = [shape(json.loads(f.GetGeometryRef().ExportToJson())) for f in lyr if f.GetField("v") == 1]
    geom = unary_union(polys).buffer(0).simplify(simplify, preserve_topology=True).buffer(0)
    parts = sorted(list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom], key=lambda p: -p.area)
    poly = parts[0]
    return Polygon(poly.exterior, [r for r in poly.interiors if Polygon(r).area > 100.0]), len(parts)


def run(job, force=False):
    cfg = job.cfg
    out_json, out_tif = job.w("terrain.json"), job.w("terrain_existing.tif")
    geo = load_json(job.w("georef.json"))
    if not geo:
        raise RuntimeError("the drawing is not placed yet - run the georef stage first")
    wanted = {"cloud": job.cloud_signature(), "georef": geo["transform"], "buildings": geo.get("building_layers"),
              **settings(cfg, "cloud", "terrain")}
    prev = load_json(out_json) or {}
    if not force and prev.get("inputs") == wanted and out_tif.exists():
        skip(f"terrain: already built ({prev['source']}, altitudes {prev['z_range'][0]:.1f}..{prev['z_range'][1]:.1f} m)")
        return
    g2u = Rigid2D.from_json(geo["transform"])
    tr = LonLatUTM(geo["epsg"])
    site = load_site(job)
    bx = site["bbox"]
    res = float(cfg["terrain"]["resolution_m"])
    result = {"inputs": wanted}

    cache = run_relief_dem(cfg, job.cloud)
    rigid, placement = place_cloud(job, cache)
    dz, zinfo = z_offset(job, cache, rigid, g2u, tr)
    dem, gt, _ = read_raster(cache / "dem_clean.tif")
    fp, fgt, _ = read_raster(cache / "footprint.tif")
    # the cloud footprint in drawing coordinates, cut to the site plan
    corners = np.array([[gt[0], gt[3]], [gt[0] + gt[1] * dem.shape[1], gt[3]],
                        [gt[0] + gt[1] * dem.shape[1], gt[3] + gt[5] * dem.shape[0]],
                        [gt[0], gt[3] + gt[5] * dem.shape[0]]])
    c = rigid.apply(corners)
    area = box(*c.min(axis=0), *c.max(axis=0)).intersection(box(*bx))
    x0, y0, x1, y1 = (math.floor(area.bounds[0]), math.floor(area.bounds[1]),
                      math.ceil(area.bounds[2]), math.ceil(area.bounds[3]))
    W, H = int((x1 - x0) / res), int((y1 - y0) / res)
    X, Y = np.meshgrid(x0 + (np.arange(W) + 0.5) * res, y1 - (np.arange(H) + 0.5) * res)
    src = rigid.inverse(np.column_stack([X.ravel(), Y.ravel()]))
    z = sample_raster(dem, gt, src).reshape(H, W) + dz
    inside = sample_raster(np.nan_to_num(fp), fgt, src, nan_outside=False).reshape(H, W) > 0.5
    z[~inside] = np.nan
    result.update({"source": "point cloud", "cloud_to_drawing": rigid.to_json(), "placement": placement,
                   "z_to_altitude": dz, "altitude": zinfo, "relief_cache": str(cache)})
    conv = geo.get("grid_convergence_deg")
    log(f"terrain: point cloud placed: rotation {math.degrees(rigid.angle):+.3f} deg (map grid convergence here "
        f"{conv:+.3f} deg), cloud 0,0 = drawing ({rigid.t[0]:.2f}, {rigid.t[1]:.2f}) m, peak ratio "
        f"{placement.get('peak_ratio', float('nan')):.2f}")
    log(f"terrain: altitude = cloud height {dz:+.2f} m ({zinfo['method']}"
        + (f", {zinfo['samples']} samples, spread +-{zinfo['mad_m']} m)" if "mad_m" in zinfo else ")"))
    tgt = (float(x0), res, 0.0, float(y1), 0.0, -res)
    valid = np.isfinite(z)
    if valid.sum() < 100:
        raise RuntimeError("terrain: the terrain does not cover the site plan (placement wrong?)")
    poly, parts = outline_polygon(valid, tgt, float(cfg["terrain"]["outline_simplify_m"]))
    if parts > 1:
        detail(f"terrain: the terrain covers {parts} separate areas; the mesh uses the largest ({poly.area / 1e4:.1f} ha)")
    write_raster(out_tif, z, tgt)
    result.update({"grid": {"geotransform": tgt, "shape": [H, W]}, "outline": mapping(poly),
                   "area_ha": round(poly.area / 1e4, 2),
                   "z_range": [float(np.nanmin(z)), float(np.nanmax(z))]})
    log(f"terrain: {poly.area / 1e4:.1f} ha of terrain on a {res} m grid, altitudes "
        f"{np.nanmin(z):.1f}..{np.nanmax(z):.1f} m")
    save_json(out_json, result)
