"""Inputs of one run and where every result goes.

<work>/<drawing>/           every intermediate result of that drawing, pipeline.log
<output>/<drawing>_FromDWG.pln           the Archicad file
<output>/<drawing>_FromDWG_report.html   what was done, with pictures and checks
"""
import os
from pathlib import Path

from .util import file_signature, slug

DRAWING_EXT = {".dwg", ".dxf"}
RESULT_SUFFIX = "_FromDWG"


def check_input(cfg, drawing, cloud=None):
    """(drawing path, point cloud path) from the command line and the config: both are needed."""
    path = os.path.abspath(drawing)
    if not os.path.isfile(path):
        raise SystemExit(f"File not found: {drawing}")
    if Path(path).suffix.lower() not in DRAWING_EXT:
        raise SystemExit(f"Not a DWG or DXF file: {drawing}")
    cloud = cloud or cfg["paths"].get("point_cloud")
    if not cloud:
        raise SystemExit("The point cloud of the site is needed: dwg2ac.bat DRAWING POINT_CLOUD")
    cloud = os.path.abspath(cloud)
    if not os.path.isfile(cloud):
        raise SystemExit(f"Point cloud not found: {cloud}")
    return path, cloud


class Job:
    def __init__(self, cfg, drawing, cloud):
        self.cfg = cfg
        self.drawing = str(drawing)
        self.cloud = str(cloud)
        stem = Path(self.drawing).stem
        self.work_dir = cfg["_work"] / slug(stem)
        self.pln_dir = self.work_dir  # the Archicad session keeps dialog reports here
        self.output_pln = str(cfg["_output"] / f"{stem}{RESULT_SUFFIX}.pln")
        self.output_report = str(cfg["_output"] / f"{stem}{RESULT_SUFFIX}_report.html")

    def w(self, name):
        """File in the work folder of this drawing."""
        return self.work_dir / name

    def drawing_signature(self):
        return file_signature(self.drawing)

    def cloud_signature(self):
        return file_signature(self.cloud)
