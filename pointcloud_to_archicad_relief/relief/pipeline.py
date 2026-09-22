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
from pathlib import Path

from . import __version__
from .io import cloud_formats
from .job import Job
from .util import (detail, duration, error, load_json, log, ok, save_json, section, set_log_file,
                   set_stage, warn)


@dataclass(frozen=True)
class Stage:
    name: str
    scope: str  # "cloud": once per point cloud input, "pln": once per source PLN
    module: str
    help: str

    def run(self, job, force):
        import_module(f"relief.stages.{self.module}").run(job, force=force)


STAGES = (
    Stage("cloud", "cloud", "cloud", "read the point cloud"),
    Stage("ground", "cloud", "ground", "separate the ground from trees, buildings and noise"),
    Stage("dem", "cloud", "dem", "build a clean terrain model"),
    Stage("reference", "pln", "reference", "work out where the relief goes"),
    Stage("contours", "pln", "contours", "build the mesh and cut the contour lines"),
    Stage("archicad", "pln", "archicad", "write the Archicad file"),
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
    warn("the point cloud changed since the last run - all selected stages are redone")
    return True


def run(cfg, clouds, plns, selected, force=False):
    """Run the selected stages for the point cloud(s) and each PLN (none: a new PLN is made); returns
    (exit code, log file). Only the cache folder and the results in the output folder are written."""
    t_start = time.time()
    job = Job(cfg, clouds)
    job.cloud_dir.mkdir(parents=True, exist_ok=True)
    log_path = job.c("pipeline.log")
    set_log_file(log_path)
    stages = [s for s in STAGES if s.name in selected]
    pln_stages = [s for s in stages if s.scope == "pln"]
    targets = list(plns) or [None]
    set_stage("run")
    section(f"relief {__version__}  -  {time.strftime('%Y-%m-%d %H:%M')}")
    for c in clouds:
        log(f"point cloud   {c}")
    for p in plns:
        log(f"project       {p}  (read only)")
    if not plns:
        log("project       none - a new PLN is made from the point cloud")
    log(f"output        {cfg['_output']}")
    log(f"stages        {', '.join(selected)}{'  (forced: cached results are redone)' if force else ''}")
    detail(f"settings      {', '.join(cfg['_files'])}")
    detail(f"cache         {job.cloud_dir}")
    detail(f"log file      {log_path}")
    try:
        force = _cloud_changed(job, selected, force)
        steps = [(s, job) for s in stages if s.scope == "cloud"]
        for pln in targets if pln_stages else []:
            pj = job.with_pln(pln)
            pj.pln_dir.mkdir(parents=True, exist_ok=True)
            steps += [(s, pj) for s in pln_stages]
        for n, (stage, j) in enumerate(steps, 1):
            t0 = time.time()
            target = f"  [{Path(j.output_pln).name}]" if stage.scope == "pln" and len(targets) > 1 else ""
            section(f"{n}/{len(steps)}  {stage.name}  -  {stage.help}{target}")
            set_stage(stage.name)
            stage.run(j, force)
            ok(f"done in {duration(time.time() - t0)}")
    except (Exception, KeyboardInterrupt) as e:
        error("the traceback:\n" + traceback.format_exc(), console=False)
        section("FAILED")
        set_stage("run")
        error(f"{type(e).__name__}: {e}" if str(e) else type(e).__name__)
        error("nothing unsafe was saved; the full error is in the log file")
        log(f"log file      {log_path}")
        return 1, log_path
    set_stage("run")
    section(f"done in {duration(time.time() - t_start)}")
    for pln in targets if "archicad" in selected else []:
        pj = job.with_pln(pln)
        ok(f"Archicad      {pj.output_pln}")
        ok(f"contours DXF  {pj.output_dxf}")
    detail(f"log file      {log_path}")
    return 0, log_path
