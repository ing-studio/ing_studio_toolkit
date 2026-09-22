"""relief.gpkg: the mesh and the contour layers, handed from the contours stage to the Archicad and QA stages.

Layers (source coordinates):
  mesh_outline      one Polygon25D: outline + holes, Z = terrain height at each vertex
  mesh_points       Point25D: the interior mesh points
  contours_<size>   LineString25D per contour: the curve Archicad draws, CTRL_JSON = the spline points
"""
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
from osgeo import ogr

from ..geometry.transform import apply_transform

ogr.UseExceptions()

CONTOUR_FIELDS = (("ELEV_SRC", ogr.OFTReal), ("ELEV_ABS", ogr.OFTReal), ("ELEV_PZ", ogr.OFTReal),
                  ("CLOSED", ogr.OFTInteger), ("LEN", ogr.OFTReal), ("N_CTRL", ogr.OFTInteger),
                  ("ERR_MESH_P95", ogr.OFTReal), ("CTRL_JSON", ogr.OFTString))


def _write_local_then_copy(final, write):
    """OGR writes feature by feature, which is very slow on a network share: build the file locally, then copy."""
    final = Path(final)
    with tempfile.TemporaryDirectory(prefix="relief_") as tmp:
        local = Path(tmp) / final.name
        write(local)
        final.parent.mkdir(parents=True, exist_ok=True)
        final.unlink(missing_ok=True)
        shutil.copyfile(local, final)


def _ring(pts):
    r = ogr.Geometry(ogr.wkbLinearRing)
    for x, y, z in list(pts) + [pts[0]]:
        r.AddPoint(float(x), float(y), float(z))
    return r


def write_relief(path, mesh, layers, to_pz):
    """mesh: dict(outline, holes, points); layers: {label: [line dict]} with elev, elev_abs, closed, length,
    ctrl, curve, err_mesh_p95."""
    def write(local):
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(local))
        ds.StartTransaction()
        ol = ds.CreateLayer("mesh_outline", geom_type=ogr.wkbPolygon25D)
        poly = ogr.Geometry(ogr.wkbPolygon25D)
        for ring in [mesh["outline"]] + list(mesh["holes"]):
            poly.AddGeometry(_ring(ring))
        f = ogr.Feature(ol.GetLayerDefn())
        f.SetGeometry(poly)
        ol.CreateFeature(f)
        ml = ds.CreateLayer("mesh_points", geom_type=ogr.wkbPoint25D)
        for x, y, z in mesh["points"]:
            g = ogr.Geometry(ogr.wkbPoint25D)
            g.AddPoint(float(x), float(y), float(z))
            f = ogr.Feature(ml.GetLayerDefn())
            f.SetGeometry(g)
            ml.CreateFeature(f)
        for label, lines in layers.items():
            cl = ds.CreateLayer(f"contours_{label}", geom_type=ogr.wkbLineString25D)
            for name, typ in CONTOUR_FIELDS:
                cl.CreateField(ogr.FieldDefn(name, typ))
            for ln in lines:
                g = ogr.Geometry(ogr.wkbLineString25D)
                for x, y in ln["curve"]:
                    g.AddPoint(float(x), float(y), ln["elev"])
                f = ogr.Feature(cl.GetLayerDefn())
                f.SetField("ELEV_SRC", ln["elev"])
                f.SetField("ELEV_ABS", ln["elev_abs"])
                f.SetField("ELEV_PZ", round(ln["elev"] + to_pz, 4))
                f.SetField("CLOSED", int(ln["closed"]))
                f.SetField("LEN", ln["length"])
                f.SetField("N_CTRL", len(ln["ctrl"]))
                f.SetField("ERR_MESH_P95", ln["err_mesh_p95"])
                f.SetField("CTRL_JSON", json.dumps(np.round(ln["ctrl"], 4).tolist()))
                f.SetGeometry(g)
                cl.CreateFeature(f)
        ds.CommitTransaction()
        ds = None  # noqa: F841 - closes the file before it is copied

    _write_local_then_copy(path, write)


def read_relief(path, labels):
    """(mesh dict(outline, holes, points), {label: [dict(elev_src, elev_abs, closed, ctrl, curve)]})."""
    ds = ogr.Open(str(path))
    feat = ds.GetLayer("mesh_outline").GetNextFeature()  # the feature must stay alive while its geometry is read
    geom = feat.GetGeometryRef()
    rings = [np.array(geom.GetGeometryRef(i).GetPoints())[:-1] for i in range(geom.GetGeometryCount())]
    pts = np.array([f.GetGeometryRef().GetPoint() for f in ds.GetLayer("mesh_points")], dtype=np.float64)
    mesh = {"outline": rings[0], "holes": rings[1:], "points": pts.reshape(-1, 3)}
    layers = {}
    for label in labels:
        lyr = ds.GetLayer(f"contours_{label}")
        if lyr is None:
            raise RuntimeError(f"{Path(path).name} has no contours_{label} layer - run the contours stage again")
        layers[label] = [{"elev_src": f.GetField("ELEV_SRC"), "elev_abs": f.GetField("ELEV_ABS"),
                          "closed": bool(f.GetField("CLOSED")),
                          "ctrl": np.array(json.loads(f.GetField("CTRL_JSON"))),
                          "curve": np.array(f.GetGeometryRef().GetPoints())[:, :2]} for f in lyr]
    return mesh, layers


def write_contours_dxf(path, t, layers):
    """3D contours for CAD tools: PLN coordinates, Z = metres above sea level, one DXF layer per cut size."""
    def write(local):
        ds = ogr.GetDriverByName("DXF").CreateDataSource(str(local))
        lyr = ds.CreateLayer("contours", geom_type=ogr.wkbLineString25D)
        for label, lines in layers.items():
            for c in lines:
                p = apply_transform(t, np.column_stack([c["curve"], np.zeros(len(c["curve"]))]))
                g = ogr.Geometry(ogr.wkbLineString25D)
                for x, y in p[:, :2]:
                    g.AddPoint(float(x), float(y), float(c["elev_abs"]))
                f = ogr.Feature(lyr.GetLayerDefn())
                f.SetField("Layer", f"CONTOUR_{label.upper()}")
                f.SetGeometry(g)
                lyr.CreateFeature(f)
        ds = None  # noqa: F841

    _write_local_then_copy(path, write)
