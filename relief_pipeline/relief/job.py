"""Inputs of one run and where every result goes."""
import os
from pathlib import Path

from .util import same_path, slug

CLOUD_EXT = {".e57", ".las", ".laz", ".ply", ".pcd", ".pts", ".ptx",
             ".xyz", ".txt", ".csv", ".asc", ".neu", ".xyzrgb", ".xyzn"}


def discover_inputs(cfg, clouds=None, plns=None):
    """Point clouds and PLNs: given ones first, then the input folder; clouds fall back to paths.source_cloud."""
    folder = cfg["_input"]
    files = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    if not clouds:
        clouds = [str(p) for p in files if p.suffix.lower() in CLOUD_EXT]
    if not clouds:
        src = cfg["paths"].get("source_cloud")
        clouds = [str(s) for s in (src if isinstance(src, list) else [src])] if src else []
    if not plns:
        plns = [str(p) for p in files if p.suffix.lower() == ".pln"]
    if not clouds:
        raise SystemExit(f"No point cloud: pass --cloud, put one into {folder} or set paths.source_cloud")
    for path in list(clouds) + list(plns):
        if not os.path.exists(path):
            raise SystemExit(f"Input not found: {path}")
    return [str(c) for c in clouds], [str(p) for p in plns]


class Job:
    """Work paths for one point cloud input and (optionally) one source PLN.

    <work>/<cloud>/          cloud, ground and DEM results (shared by every PLN), pipeline.log
    <work>/<cloud>/<pln>/    placement, mesh + contours, Archicad and QA results for that PLN
    <output>/<pln>_ReliefOnly.pln and _ReliefOnly_contours.dxf
    """

    def __init__(self, cfg, clouds, pln=None):
        self.cfg = cfg
        self.clouds = [str(c) for c in clouds]
        name = slug(Path(self.clouds[0]).stem)
        if len(self.clouds) > 1:
            name += f"_and_{len(self.clouds) - 1}_more"
        self.cloud_dir = cfg["_work"] / name
        self.pln = str(pln) if pln else None
        self.pln_dir = self.cloud_dir / slug(Path(pln).stem) if pln else None
        stem = Path(pln).stem if pln else None
        self.output_pln = str(cfg["_output"] / f"{stem}_ReliefOnly.pln") if pln else None
        self.output_dxf = str(cfg["_output"] / f"{stem}_ReliefOnly_contours.dxf") if pln else None

    def c(self, name):
        """File in the point cloud work folder."""
        return self.cloud_dir / name

    def p(self, name):
        """File in the PLN work folder."""
        return self.pln_dir / name

    def with_pln(self, pln):
        job = Job(self.cfg, self.clouds, pln)
        if same_path(job.pln, job.output_pln):
            raise SystemExit(f"The source PLN is already in the output folder: {pln}")
        return job
