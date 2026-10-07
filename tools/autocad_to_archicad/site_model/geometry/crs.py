"""Map coordinates: longitude/latitude <-> UTM (the zone of the site), and the drawing <-> UTM placement."""
import math

import numpy as np
from osgeo import osr

osr.UseExceptions()


def utm_epsg(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def _srs(epsg):
    s = osr.SpatialReference()
    s.ImportFromEPSG(int(epsg))
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


class LonLatUTM:
    def __init__(self, epsg):
        self.epsg = int(epsg)
        self._fwd = osr.CoordinateTransformation(_srs(4326), _srs(epsg))
        self._inv = osr.CoordinateTransformation(_srs(epsg), _srs(4326))

    def to_utm(self, lonlat):
        a = np.asarray(lonlat, dtype=np.float64).reshape(-1, 2)
        return np.array(self._fwd.TransformPoints(a))[:, :2]

    def to_lonlat(self, xy):
        a = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        return np.array(self._inv.TransformPoints(a))[:, :2]


class Rigid2D:
    """p' = R(angle) p + t (no scale)."""

    def __init__(self, angle_rad, tx, ty):
        self.angle, self.t = float(angle_rad), np.array([tx, ty], dtype=np.float64)

    @property
    def R(self):
        c, s = math.cos(self.angle), math.sin(self.angle)
        return np.array([[c, -s], [s, c]])

    def apply(self, xy):
        return np.asarray(xy, dtype=np.float64).reshape(-1, 2) @ self.R.T + self.t

    def inverse(self, xy):
        return (np.asarray(xy, dtype=np.float64).reshape(-1, 2) - self.t) @ self.R

    def to_json(self):
        return {"rotation_deg": math.degrees(self.angle), "tx": float(self.t[0]), "ty": float(self.t[1])}

    @classmethod
    def from_json(cls, d):
        return cls(math.radians(d["rotation_deg"]), d["tx"], d["ty"])
