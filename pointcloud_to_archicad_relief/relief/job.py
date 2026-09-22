"""Inputs of one run and where every result goes."""
import os
from pathlib import Path

from .util import slug

CLOUD_EXT = {".e57", ".las", ".laz", ".ply", ".pcd", ".pts", ".ptx",
             ".xyz", ".txt", ".csv", ".asc", ".neu", ".xyzrgb", ".xyzn"}
RESULT_SUFFIX = "_ReliefOnly"


def sort_inputs(cfg, files):
    """Files given on the command line -> (point clouds, PLNs), by extension.

    Only PLN(s): the point cloud comes from paths.source_cloud. Only point cloud(s): a new PLN is made from them."""
    clouds, plns = [], []
    for f in files or []:
        path = os.path.abspath(f)
        if not os.path.isfile(path):
            raise SystemExit(f"File not found: {f}")
        ext = Path(path).suffix.lower()
        if ext == ".pln":
            if Path(path).stem.endswith(RESULT_SUFFIX):
                raise SystemExit(f"{f} is a result of this tool - give the source project instead")
            plns.append(path)
        elif ext in CLOUD_EXT:
            clouds.append(path)
        else:
            raise SystemExit(f"Not a point cloud or .pln file: {f}\n"
                             f"Point clouds: {' '.join(sorted(e[1:].upper() for e in CLOUD_EXT))}")
    if not clouds and plns:
        src = cfg["paths"].get("source_cloud")
        clouds = [str(s) for s in (src if isinstance(src, list) else [src])] if src else []
        if not clouds:
            raise SystemExit("No point cloud: give one next to the .pln, or set paths.source_cloud in "
                             "config/project.json")
        for c in clouds:
            if not os.path.isfile(c):
                raise SystemExit(f"Point cloud from paths.source_cloud not found: {c}")
    if not clouds:
        raise SystemExit("Nothing to do: give a point cloud file (and optionally the .pln to place it in).\n"
                         "Example:  relief.bat survey.e57   (see relief.bat --help)")
    return clouds, plns


class Job:
    """Work paths for one point cloud input and one target: a source PLN, or (pln=None) a new PLN.

    <work>/<cloud>/            cloud, ground and DEM results (shared by every PLN), pipeline.log
    <work>/<cloud>/<pln>/      placement, mesh + contours and Archicad results for that PLN
    <work>/<cloud>/new_pln/    the same for a PLN made from the point cloud alone
    <output>/<name>_ReliefOnly.pln and <name>_ReliefOnly_contours.dxf   (name = the PLN's, else the cloud's)
    """

    def __init__(self, cfg, clouds, pln=None):
        self.cfg = cfg
        self.clouds = [str(c) for c in clouds]
        name = slug(Path(self.clouds[0]).stem)
        if len(self.clouds) > 1:
            name += f"_and_{len(self.clouds) - 1}_more"
        self.cloud_dir = cfg["_work"] / name
        self.pln = str(pln) if pln else None
        self.pln_dir = self.cloud_dir / (slug(Path(pln).stem) if pln else "new_pln")
        stem = Path(pln).stem if pln else Path(self.clouds[0]).stem
        self.output_pln = str(cfg["_output"] / f"{stem}{RESULT_SUFFIX}.pln")
        self.output_dxf = str(cfg["_output"] / f"{stem}{RESULT_SUFFIX}_contours.dxf")

    def c(self, name):
        """File in the point cloud work folder."""
        return self.cloud_dir / name

    def p(self, name):
        """File in the PLN work folder."""
        return self.pln_dir / name

    def with_pln(self, pln):
        """The job for one target: a source PLN, or None for a new PLN."""
        return Job(self.cfg, self.clouds, pln)
