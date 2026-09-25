"""The stages in order, and running a selection of them for one drawing.

  read        DWG -> DXF through AutoCAD's console (AEC objects made plain)
  inventory   units, drawing regions (the site plan), layers, old Armenian text
  documents   optional project PDFs read as data: programme tables, stated areas, level outlines placed on the drawing
  georef      the drawing on the map: its building outlines matched to OpenStreetMap (where: the given position, or the
              places the input names point to)
  layers      what each layer holds (buildings, shadows, trees, streets, sidewalks, kerbs), from the geometry
  terrain     the point cloud terrain placed on the drawing, in altitudes
  buildings   existing (OSM heights) and proposed buildings (storeys from the drawn shadows), trees, underground levels;
              existing buildings under the new development are listed as demolished
  roads       existing streets (OpenStreetMap, fitted to the kerbs) and the new streets (outline, centre line, profile);
              their surfaces stop at the buildings
  earthworks  the street surfaces (continuous, smooth), the terrain under them and cut and filled around them; the
              ground under the buildings stays as it is
  context     the surroundings: OSM buildings (with their building:parts) around the site, on a terrain from the
              open world terrain model fitted to the survey terrain at its edge
  archicad    the PLN: terrain mesh, grey street and sidewalk solids lying on it, buildings, retaining walls, trees
              (library objects), the drawing in 2D; checked and saved
  report      the HTML report next to the PLN

A stage whose results exist for the same inputs and settings is skipped; --force re-runs the selected stages
(dwg2ac.bat clean DRAWING deletes them all).
"""
import time
import traceback
from dataclasses import dataclass
from importlib import import_module

from . import __version__
from .util import detail, duration, error, log, ok, section, set_log_file, set_stage


@dataclass(frozen=True)
class Stage:
    name: str
    module: str
    help: str

    def run(self, job, force):
        import_module(f"acad.stages.{self.module}").run(job, force=force)


STAGES = (
    Stage("read", "read", "read the drawing"),
    Stage("inventory", "inventory", "find the site plan, units and layers"),
    Stage("documents", "documents", "read the project PDFs (optional)"),
    Stage("georef", "georef", "place the drawing on the map"),
    Stage("layers", "layers", "work out what each layer holds"),
    Stage("terrain", "terrain", "place the point cloud terrain on the drawing"),
    Stage("buildings", "buildings", "buildings, trees and underground levels"),
    Stage("roads", "roads", "existing and new streets"),
    Stage("earthworks", "earthworks", "street surfaces; cut and fill the terrain for them"),
    Stage("context", "context", "the surroundings: OSM buildings on the world terrain around the site"),
    Stage("archicad", "archicad", "write the Archicad file"),
    Stage("report", "report", "write the report"),
)
STAGE_NAMES = [s.name for s in STAGES]


def select(stage=None, start=None, until=None):
    if stage:
        return [stage]
    i = STAGE_NAMES.index(start) if start else 0
    j = STAGE_NAMES.index(until) + 1 if until else len(STAGE_NAMES)
    if i >= j:
        raise SystemExit(f"--from {start} comes after --until {until}")
    return STAGE_NAMES[i:j]


def run(job, selected, force=False):
    """Run the selected stages; returns (exit code, log file)."""
    t_start = time.time()
    job.work_dir.mkdir(parents=True, exist_ok=True)
    log_path = job.w("pipeline.log")
    set_log_file(log_path)
    set_stage("run")
    section(f"autocad_to_archicad {__version__}  -  {time.strftime('%Y-%m-%d %H:%M')}")
    log(f"drawing       {job.drawing}")
    log(f"point cloud   {job.cloud}")
    log(f"output        {job.cfg['_output']}")
    log(f"stages        {', '.join(selected)}{'  (forced: cached results are redone)' if force else ''}")
    detail(f"settings      {', '.join(job.cfg['_files'])}")
    detail(f"cache         {job.work_dir}")
    detail(f"log file      {log_path}")
    stages = [s for s in STAGES if s.name in selected]
    try:
        for n, stage in enumerate(stages, 1):
            t0 = time.time()
            section(f"{n}/{len(stages)}  {stage.name}  -  {stage.help}")
            set_stage(stage.name)
            stage.run(job, force)
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
    if "archicad" in selected:
        ok(f"Archicad      {job.output_pln}")
    if "report" in selected:
        ok(f"report        {job.output_report}")
    detail(f"log file      {log_path}")
    return 0, log_path
