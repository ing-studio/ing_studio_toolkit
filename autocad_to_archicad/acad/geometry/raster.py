"""Raster IO, sampling and adaptive terrain points."""
import numpy as np
from osgeo import gdal
from scipy import ndimage

gdal.UseExceptions()
NODATA = -9999.0


def read_raster(path):
    """(array with NaN for nodata, geotransform, projection)."""
    ds = gdal.Open(str(path))
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype(np.float64)
    nd = band.GetNoDataValue()
    if nd is not None:
        arr[arr == nd] = np.nan
    return arr, ds.GetGeoTransform(), ds.GetProjection()


def write_raster(path, arr, gt, proj="", dtype=gdal.GDT_Float32, nodata=NODATA):
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(path), arr.shape[1], arr.shape[0], 1, dtype, options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform(gt)
    if proj:
        ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    out = arr
    if nodata is not None:
        band.SetNoDataValue(nodata)
        if arr.dtype.kind == "f":
            out = np.where(np.isfinite(arr), arr, nodata)
    band.WriteArray(out)
    ds.FlushCache()


def nearest_fill(z, valid):
    """Copy of z where invalid cells take the value of the nearest valid cell (keeps filters away from edges)."""
    idx = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return z[idx[0], idx[1]]


def sample_raster(arr, gt, xy, nan_outside=True):
    """Bilinear sample at (x, y) world coordinates; NaN where any neighbour is NaN (if nan_outside)."""
    xy = np.asarray(xy, dtype=np.float64)
    col = (xy[:, 0] - gt[0]) / gt[1] - 0.5
    row = (xy[:, 1] - gt[3]) / gt[5] - 0.5
    finite = np.isfinite(arr)
    val = ndimage.map_coordinates(np.where(finite, arr, 0.0), [row, col], order=1, mode="nearest")
    if nan_outside:
        w = ndimage.map_coordinates(finite.astype(np.float64), [row, col], order=1, mode="constant", cval=0.0)
        val[w < 0.999] = np.nan
    return val


def quadtree_points(z, gt, valid, tol, min_px=2, max_px=64):
    """Adaptive terrain points: split square blocks until bilinear-from-corners error <= tol.
    Returns (N, 3) array of x, y, z (cell centres) inside `valid`."""
    rows, cols = z.shape
    zx = nearest_fill(z, valid)
    # pad to a multiple of max_px (+1 for the far corners); padding is invalid
    R = int(np.ceil((rows - 1) / max_px)) * max_px + 1
    C = int(np.ceil((cols - 1) / max_px)) * max_px + 1
    zp = np.pad(zx, ((0, R - rows), (0, C - cols)), mode="edge")
    vp = np.pad(valid, ((0, R - rows), (0, C - cols)), constant_values=False)
    rr0, cc0 = np.meshgrid(np.arange(0, R - 1, max_px), np.arange(0, C - 1, max_px), indexing="ij")
    blocks = np.column_stack([rr0.ravel(), cc0.ravel()])
    keep_rc = []
    size = max_px
    chunk = 40000
    while len(blocks) and size >= 1:
        w = np.linspace(0.0, 1.0, size + 1)
        wy, wx = w[:, None], w[None, :]
        off = np.arange(size + 1)
        split_parts = []
        for s0 in range(0, len(blocks), chunk):
            b = blocks[s0:s0 + chunk]
            ri = b[:, 0][:, None, None] + off[None, :, None]
            ci = b[:, 1][:, None, None] + off[None, None, :]
            sub, sv = zp[ri, ci], vp[ri, ci]
            anyv = sv.any(axis=(1, 2))
            a, bb = sub[:, 0, 0, None, None], sub[:, 0, -1, None, None]
            c, d = sub[:, -1, 0, None, None], sub[:, -1, -1, None, None]
            bil = a * (1 - wy) * (1 - wx) + bb * (1 - wy) * wx + c * wy * (1 - wx) + d * wy * wx
            err = np.max(np.abs(np.where(sv, sub - bil, 0.0)), axis=(1, 2))
            split = anyv & (err > tol) & (size > min_px)
            done = anyv & ~split
            if done.any():
                bd = b[done]
                for dr, dc in ((0, 0), (0, size), (size, 0), (size, size)):
                    keep_rc.append(bd + [dr, dc])
            if split.any():
                bs = b[split]
                h = size // 2
                split_parts.append(np.vstack([bs, bs + [0, h], bs + [h, 0], bs + [h, h]]))
        blocks = np.vstack(split_parts) if split_parts else np.zeros((0, 2), int)
        size //= 2
    if not keep_rc:
        return np.zeros((0, 3))
    rc = np.unique(np.vstack(keep_rc), axis=0)
    rc = rc[(rc[:, 0] < rows) & (rc[:, 1] < cols)]
    rc = rc[valid[rc[:, 0], rc[:, 1]]]
    xs = gt[0] + (rc[:, 1] + 0.5) * gt[1]
    ys = gt[3] + (rc[:, 0] + 0.5) * gt[5]
    return np.column_stack([xs, ys, z[rc[:, 0], rc[:, 1]]])
