"""Inputs of one run and where every result goes.

<work>/<drawing>/           every intermediate result of that drawing, pipeline.log
<output>/<drawing>_FromDWG.pln           the Archicad file
<output>/<drawing>_FromDWG_report.html   what was done, with pictures and checks
"""
import os
from pathlib import Path

from ing_core.util import file_signature, input_files, slug

DRAWING_EXT = {".dwg", ".dxf"}
CLOUD_EXT = {".e57", ".las", ".laz", ".ply", ".pcd", ".pts", ".ptx",
             ".xyz", ".txt", ".csv", ".asc", ".neu", ".xyzrgb", ".xyzn"}
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
        raise SystemExit("The point cloud of the site is needed: site_model.bat DRAWING POINT_CLOUD")
    cloud = os.path.abspath(cloud)
    if not os.path.isfile(cloud):
        raise SystemExit(f"Point cloud not found: {cloud}")
    return path, cloud


def from_input_folder(tool_dir):
    """(drawing, point cloud or None, [PDFs]) in the tool's input folder: one drawing, at most one point cloud."""
    drawings = input_files(tool_dir, DRAWING_EXT)
    if len(drawings) != 1:
        raise SystemExit(f"The input folder needs one drawing (.dwg or .dxf), it has {len(drawings) or 'none'}: "
                         f"{Path(tool_dir) / 'input'}\nOr give them:  site_model.bat DRAWING POINT_CLOUD")
    clouds = input_files(tool_dir, CLOUD_EXT)
    if len(clouds) > 1:
        raise SystemExit(f"The input folder has {len(clouds)} point clouds; the tool takes one: "
                         + ", ".join(Path(c).name for c in clouds))
    return drawings[0], (clouds[0] if clouds else None), input_files(tool_dir, {".pdf"})


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
