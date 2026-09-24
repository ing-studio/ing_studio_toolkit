"""Heights from the open world terrain tiles (AWS Terrain Tiles: SRTM and national models, ~30 m, metres above sea
level, Web Mercator GeoTIFF tiles). Read over the network by GDAL, only the tiles that are needed."""
import math
from collections import defaultdict

import numpy as np
from osgeo import gdal, osr

from ..geometry.raster import sample_raster

gdal.UseExceptions()


def _tile(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def heights(lonlat, url, zoom):
    """Altitude at each [lon, lat] (NaN where no tile)."""
    lonlat = np.asarray(lonlat, dtype=np.float64).reshape(-1, 2)
    out = np.full(len(lonlat), np.nan)
    groups = defaultdict(list)
    for i, (lon, lat) in enumerate(lonlat):
        groups[_tile(lon, lat, zoom)].append(i)
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    wgs = osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    for (x, y), idx in groups.items():
        try:
            ds = gdal.Open(url.format(z=zoom, x=x, y=y))
        except RuntimeError:
            continue
        arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
        dst = osr.SpatialReference(wkt=ds.GetProjection())
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        xy = np.array(osr.CoordinateTransformation(wgs, dst).TransformPoints(lonlat[idx]))[:, :2]
        out[idx] = sample_raster(arr, ds.GetGeoTransform(), xy)
    return out
