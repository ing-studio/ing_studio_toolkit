"""The stages in order, and running a selection of them for a set of inputs.

  per point cloud   cloud      point cloud file(s) -> LAZ
                    ground     denoise + bare-earth classification
                    dem        clean bare-earth DEM
  per PLN           reference  placement + elevations, read once from the source PLN (never saved);
                               without a PLN: the point cloud's own coordinates
                    contours   one terrain mesh, cut at the contour sizes, smoothed; <name>_ReliefOnly_contours.dxf
                    archicad   the mesh + contour layers into <name>_ReliefOnly.pln; saved

A stage whose results exist for the same inputs and settings is skipped; --force re-runs the selected stages.
"""
import time
import traceback
from dataclasses import dataclass
from importlib import import_module

from .io import cloud_formats
from .job import Job
from .util import load_json, log, save_json, set_log_file


@dataclass(frozen=True)
class Stage:
    name: str
    scope: str  # "cloud": once per point cloud input, "pln": once per source PLN
    module: str
    help: str

    def run(self, job, force):
        import_module(f"relief.stages.{self.module}").run(job, force=force)


STAGES = (
    Stage("cloud", "cloud", "cloud", "point cloud file(s) -> LAZ"),
    Stage("ground", "cloud", "ground", "denoise + bare-earth classification (PDAL)"),
    Stage("dem", "cloud", "dem", "clean bare-earth DEM"),
    Stage("reference", "pln", "reference", "placement + elevations from the source PLN (read only), if one is given"),
    Stage("contours", "pln", "contours", "one terrain mesh, cut at the contour sizes, smoothed"),
    Stage("archicad", "pln", "archicad", "write <name>_ReliefOnly.pln"),
)
STAGE_NAMES = [s.name for s in STAGES]


def select(stage=None, start=None, until=None):
    """Stage names to run: one stage, or a range (from `start` to `until`, both included)."""
    if stage:
        return [stage]
    i = STAGE_NAMES.index(start) if start else 0
    j = STAGE_NAMES.index(until) + 1 if until else len(STAGE_NAMES)
    if i >= j:
        raise SystemExit(f"--from {start} comes after --until {until}")
    return STAGE_NAMES[i:j]


def _cloud_changed(job, selected, force):
    """A work folder is never reused for a different point cloud; returns the effective force flag."""
    summary = load_json(job.c("cloud_summary.json"))
    if summary is None:
        return force
    current = cloud_formats.signature(job)
    previous = summary.get("inputs")
    if previous is None or cloud_formats.same_signature(previous, current):
        if previous != current:
            summary["inputs"] = current  # an equivalent record in an older format: store the current one
            save_json(job.c("cloud_summary.json"), summary)
        return force
    if "cloud" not in selected:
        raise SystemExit(f"The point cloud differs from the one {job.cloud_dir} was built from - run all stages")
    log("input point cloud changed -> rebuilding all selected stages")
    return True


def run(cfg, clouds, plns, selected, force=False):
    """Run the selected stages for the point cloud(s) and each PLN (none: a new PLN is made); returns
    (exit code, log file). Only the work folder and the results in the output folder are written."""
    job = Job(cfg, clouds)
    job.cloud_dir.mkdir(parents=True, exist_ok=True)
    log_path = job.c("pipeline.log")
    set_log_file(log_path)
    stages = [s for s in STAGES if s.name in selected]
    pln_stages = [s for s in stages if s.scope == "pln"]
    targets = list(plns) or [None]
    try:
        log(f"===== run: {', '.join(selected)}{' (forced)' if force else ''} =====")
        log(f"point cloud(s): {clouds}")
        log(f"PLN(s): {plns or 'none - a new PLN is made from the point cloud'}")
        log(f"config: {cfg['_files']}")
        force = _cloud_changed(job, selected, force)
        steps = [(s, job) for s in stages if s.scope == "cloud"]
        for pln in targets if pln_stages else []:
            pj = job.with_pln(pln)
            pj.pln_dir.mkdir(parents=True, exist_ok=True)
            steps += [(s, pj) for s in pln_stages]
        for stage, j in steps:
            t0 = time.time()
            log(f"===== stage {stage.name}{f' [{j.output_pln}]' if stage.scope == 'pln' else ''} =====")
            stage.run(j, force)
            log(f"===== stage {stage.name} done in {time.time() - t0:.1f}s =====")
    except (Exception, KeyboardInterrupt):
        log("FAILED:\n" + traceback.format_exc())
        return 1, log_path
    log("===== finished =====")
    for pln in targets if "archicad" in selected else []:
        log(f"result: {job.with_pln(pln).output_pln}")
    return 0, log_path
