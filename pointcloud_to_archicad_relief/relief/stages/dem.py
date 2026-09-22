"""Stage dem: precise bare-earth DEM from the classified cloud (pits, raised objects, gaps, spikes, smoothing)."""
import math

import numpy as np
from osgeo import gdal
from scipy import ndimage
from scipy.interpolate import griddata

from ..geometry.raster import NODATA, nearest_fill, read_raster, write_raster
from ..io.pdal import pdal_json, pdal_pipeline
from ..util import all_exist, log, save_json


def _disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def _tin_fill(z, fill_mask, max_hole_px):
    """Linear (Delaunay) interpolation of each gap from its valid rim; returns (array, filled cell count)."""
    out = z.copy()
    lab, _ = ndimage.label(fill_mask)
    filled = 0
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None or (lab[sl] == i).sum() > max_hole_px:
            continue
        pad = 4
        r0, r1 = max(sl[0].start - pad, 0), min(sl[0].stop + pad, z.shape[0])
        c0, c1 = max(sl[1].start - pad, 0), min(sl[1].stop + pad, z.shape[1])
        sub = z[r0:r1, c0:c1]
        h = lab[r0:r1, c0:c1] == i
        rim = ndimage.binary_dilation(h, iterations=3) & ~h & np.isfinite(sub)
        if rim.sum() < 3:
            continue
        rr, cc = np.nonzero(rim)
        hr, hc = np.nonzero(h)
        try:
            v = griddata((rr, cc), sub[rr, cc], (hr, hc), method="linear")
        except Exception:  # degenerate rim (collinear)
            v = np.full(len(hr), np.nan)
        bad = ~np.isfinite(v)
        if bad.any():
            v[bad] = griddata((rr, cc), sub[rr, cc], (hr[bad], hc[bad]), method="nearest")
        out[r0:r1, c0:c1][hr, hc] = v
        filled += len(hr)
    return out, filled


def _rasterize(job, res):
    """Point coverage, non-ground density and ground IDW DEM on one aligned grid (separate PDAL runs: branched
    multi-writer pipelines only execute one leaf)."""
    classified = job.c("classified.laz")
    b = pdal_json(job, ["info", "--summary", str(classified)])["summary"]["bounds"]
    minx, miny = math.floor(b["minx"] / res) * res, math.floor(b["miny"] / res) * res
    maxx, maxy = math.ceil(b["maxx"] / res) * res, math.ceil(b["maxy"] / res) * res
    grid = {"resolution": res, "bounds": f"([{minx},{maxx}],[{miny},{maxy}])", "nodata": NODATA,
            "data_type": "float32", "gdaldriver": "GTiff", "gdalopts": "COMPRESS=DEFLATE,TILED=YES"}
    reader = {"type": "readers.las", "filename": str(classified)}

    def writer(name, output_type, **extra):
        return dict({"type": "writers.gdal", "filename": str(job.c(name)), "output_type": output_type}, **grid, **extra)

    log("dem: rasterizing point coverage, non-ground density and ground DEM (idw) ...")
    pdal_pipeline(job, [reader, {"type": "filters.range", "limits": "Classification![7:7]"},
                        writer("count.tif", "count")], "dem_count")
    pdal_pipeline(job, [reader, {"type": "filters.range", "limits": "Classification[1:1]"},
                        writer("nonground_count.tif", "count")], "dem_nonground")
    pdal_pipeline(job, [reader, {"type": "filters.range", "limits": "Classification[2:2]"},
                        writer("dem_raw.tif", "idw", window_size=int(job.cfg["dem"]["idw_window"]))], "dem_idw")


def run(job, force=False):
    d = job.cfg["dem"]
    res = float(d["resolution"])
    dem_clean, footprint_tif = job.c("dem_clean.tif"), job.c("footprint.tif")
    if not force and all_exist([dem_clean, footprint_tif]):
        log("dem: skip, dem_clean.tif exists")
        return

    _rasterize(job, res)
    z, gt, proj = read_raster(job.c("dem_raw.tif"))
    cnt, gt2, _ = read_raster(job.c("count.tif"))
    ng, gt3, _ = read_raster(job.c("nonground_count.tif"))
    for g2 in (gt2, gt3):
        if any(abs(a - b) > 1e-9 for a, b in zip(gt, g2)):
            raise RuntimeError("PDAL rasters are not aligned")
    cnt, ng = np.nan_to_num(cnt, nan=0.0), np.nan_to_num(ng, nan=0.0)
    cell = res * res

    def px(m):
        return max(1, int(round(m / res)))

    # 1) Survey footprint: cells with any real (non-noise) point, closed + hole-filled, tiny islands removed.
    #    Nothing is extrapolated outside it.
    r_px = d["footprint_close_m"] / res
    fp = cnt > 0
    dilated = ndimage.distance_transform_edt(~fp) <= r_px
    fp = ndimage.distance_transform_edt(dilated) > r_px
    fp = ndimage.binary_fill_holes(fp)
    lab, n = ndimage.label(fp)
    if n > 1:
        sizes = ndimage.sum(fp, lab, index=np.arange(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sizes * cell >= d["footprint_min_island_m2"]
        fp = keep[lab]

    valid_raw = np.isfinite(z) & fp
    zx = nearest_fill(z, valid_raw)

    # 2) Pits: small, deep depressions (low noise, water reflections).
    clo = ndimage.grey_closing(zx, footprint=_disk(int(round(d["pit_close_radius_m"] / res))))
    pit = valid_raw & ((clo - zx) > d["pit_depth_m"])
    lab, n = ndimage.label(pit)
    if n:
        sizes = ndimage.sum(pit, lab, index=np.arange(1, n + 1))
        small = np.zeros(n + 1, bool)
        small[1:] = sizes * cell <= d["pit_max_area_m2"]
        pit = small[lab]
    zx[pit] = clo[pit]

    # 3) Raised objects the point filter kept (dense canopy, houses: no ground visible under them).
    #    Slope-corrected top-hat, and only where above-ground points were actually seen nearby,
    #    so bare-earth embankments and terraces stay.
    step = px(2.0)  # opening computed on a ~2 m grid for speed
    radius = d["object_radius_m"]
    op = ndimage.grey_opening(zx[::step, ::step], footprint=_disk(int(round(radius / (res * step)))))
    op = ndimage.zoom(op, step, order=1)
    op = np.pad(op, ((0, max(0, z.shape[0] - op.shape[0])), (0, max(0, z.shape[1] - op.shape[1]))), mode="edge")
    op = op[: z.shape[0], : z.shape[1]]
    trend = ndimage.gaussian_filter(zx, 10.0 / res)
    gy, gx = np.gradient(trend, res, res)
    # Opening reproduces planar slopes exactly; only slope breaks need a small allowance.
    cand = valid_raw & ((zx - op) > d["object_min_height_m"] + np.hypot(gx, gy) * radius * d["object_slope_factor"])
    cand = ndimage.binary_opening(cand, iterations=px(0.5))
    frac = ndimage.gaussian_filter(ng, 2.0 / res) / np.maximum(ndimage.gaussian_filter(cnt, 2.0 / res), 1e-6)
    frac_local = ndimage.gaussian_filter(ng, 1.0 / res) / np.maximum(ndimage.gaussian_filter(cnt, 1.0 / res), 1e-6)
    lab, n = ndimage.label(cand)
    obj = np.zeros_like(cand)
    if n:
        ids = np.arange(1, n + 1)
        areas = ndimage.sum(cand, lab, index=ids) * cell
        ring = ndimage.binary_dilation(cand, iterations=px(2.0))
        lab_ring = ndimage.grey_dilation(lab, size=(2 * px(2.0) + 1, 2 * px(2.0) + 1)) * ring
        mean_frac = np.nan_to_num(ndimage.mean(frac, lab_ring, index=ids))
        large = np.zeros(n + 1, bool)
        large[1:] = areas >= d["object_large_component_m2"]
        # small raised blobs (a tree group, a house): whole blob, if vegetation / walls were seen around it
        remove_small = np.zeros(n + 1, bool)
        remove_small[1:] = ~large[1:] & (mean_frac > d["object_nonground_frac"])
        obj_small = remove_small[lab]
        # large raised areas can mix real ground (embankments, roads) with canopy along them:
        # remove only cells with vegetation over them, then the small roof-like leftovers
        large_cells = large[lab]
        veg = large_cells & (frac_local > d["object_cell_nonground_frac"])
        veg = ndimage.binary_dilation(veg, iterations=px(1.0)) & large_cells
        rest = large_cells & ~veg
        rl, rn = ndimage.label(rest)
        leftover = np.zeros(rn + 1, bool)
        if rn:
            leftover[1:] = ndimage.sum(rest, rl, index=np.arange(1, rn + 1)) * cell < d["object_leftover_max_m2"]
        obj = ndimage.binary_dilation(obj_small | veg | leftover[rl], iterations=px(1.0))

    # 4) TIN-fill every gap inside the footprint (removed objects, bridge, water) up to a max size.
    zg = np.where(valid_raw & ~obj, zx, np.nan)
    holes = fp & ~np.isfinite(zg)
    zf, filled_cells = _tin_fill(zg, holes, int(d["tin_max_hole_m2"] / cell))
    valid = np.isfinite(zf) & fp
    filled = holes & valid
    # soften TIN facets inside filled areas (feathered blend)
    sb = d["filled_blend_sigma_m"] / res
    soft = (ndimage.gaussian_filter(np.where(valid, zf, 0.0), sb)
            / np.maximum(ndimage.gaussian_filter(valid.astype(float), sb), 1e-6))
    wgt = np.clip(ndimage.gaussian_filter(filled.astype(float), 1.5 / res) * 1.5, 0, 1)
    zf = np.where(valid, (1 - wgt) * zf + wgt * soft, np.nan)
    zx = nearest_fill(zf, valid)

    # 5) Spike removal against a local median.
    k = px(d["spike_window_m"]) | 1
    med = ndimage.median_filter(zx, size=k, mode="nearest")
    spikes = valid & (np.abs(zx - med) > d["spike_threshold_m"])
    zx[spikes] = med[spikes]

    # 6) Normalized Gaussian smoothing (only valid cells contribute).
    sigma = d["gaussian_sigma_m"] / res
    num = ndimage.gaussian_filter(np.where(valid, zx, 0.0), sigma, mode="nearest")
    den = ndimage.gaussian_filter(valid.astype(np.float64), sigma, mode="nearest")
    zs = np.where(valid & (den > 1e-6), num / np.maximum(den, 1e-6), np.nan)

    write_raster(dem_clean, zs, gt, proj)
    write_raster(footprint_tif, valid.astype(np.uint8), gt, proj, dtype=gdal.GDT_Byte, nodata=None)

    stats = {
        "grid": {"cols": z.shape[1], "rows": z.shape[0], "resolution": res, "geotransform": gt},
        "footprint_area_m2": round(float(valid.sum() * cell), 1),
        "ground_cells_pct_of_footprint": round(100.0 * valid_raw.sum() / max(valid.sum(), 1), 2),
        "pits_removed_area_m2": round(float(pit.sum() * cell), 1),
        "raised_objects_removed_area_m2": round(float(obj.sum() * cell), 1),
        "tin_filled_area_m2": round(filled_cells * cell, 1),
        "unfilled_holes_area_m2": round(float((fp & ~valid).sum() * cell), 1),
        "spikes_fixed": int(spikes.sum()),
        "z_min": round(float(np.nanmin(zs)), 3),
        "z_max": round(float(np.nanmax(zs)), 3),
    }
    save_json(job.c("dem_summary.json"), stats)
    log("dem: " + ", ".join(f"{k}={v}" for k, v in stats.items() if k != "grid"))
