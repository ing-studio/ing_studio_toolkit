# Relief pipeline

Point cloud + Archicad project in → **relief-only Archicad project** out, in the coordinates of the source project:

| layer | content |
|---|---|
| `Relief - Terrain Mesh` | **one** Mesh: adaptive points of the clean bare-earth terrain inside one outline |
| `Relief - Contours 1m` | the mesh cut every 1 m (whole metres above sea level) |
| `Relief - Contours 3m` | the mesh cut every 3 m |
| `Relief - Contours 5m` | the mesh cut every 5 m |

- Each contour layer is complete on its own: show the one you need.
- Every contour line is a plan Spline and a thin 3D ribbon on the same layer, so it shows in plan and in 3D.
- The same contours are also written as a 3D DXF: `<source>_ReliefOnly_contours.dxf`, in PLN coordinates with
  Z = m a.s.l.
- Bring the relief into the real project with **File › Interoperability › Merge**, or place it as a **Hotlink**
  at the project origin.
- The source project is only read, never saved.

## Quick start
```
relief.bat run                                             everything, inputs from input\ (+ config\project.json)
relief.bat run --pln D:\site.pln --cloud D:\scan.e57       explicit files
relief.bat run --pln site.pln --cloud a.las b.las --cut 1 2 5 --mesh-points 30000
```
Or from inside Archicad: Tapir palette › **Relief from point cloud** (see [addon/README.md](addon/README.md)).

Only the first run needs to process the point cloud (minutes to hours for a large E57). After that a run reuses
the cached steps and takes about 2–4 minutes, most of it spent in Archicad.

## Folders
```
relief_pipeline\
  relief.bat               terminal entry
  config\default.json      all settings with their defaults (documented inline)
  config\project.json      your project's values - not in git; start from config\examples\
  config\examples\         example project configs (tbilisyan_bridge.json)
  relief\                  Python package (see Code and Functions below)
  addon\                   Archicad add-on: Tapir + palette button, installer
  tests\                   unit tests (relief.bat test)
  setup_env.ps1            Python environment for machines without QGIS
  pyproject.toml
  input\    source .pln (+ point cloud files, optional)                     - not in git
  output\   <source>_ReliefOnly.pln, <source>_ReliefOnly_contours.dxf       - not in git
  work\     cache per point cloud / per project, pipeline.log, qa\ report   - not in git, safe to delete
```
Input, output and work folders can live anywhere: set `paths.input_dir`, `paths.output_dir` and `paths.work_dir`
in `config\project.json`, or pass `--out` / `--work`. Relative paths are relative to this folder.

## Setup for a project
1. Copy `config\examples\tbilisyan_bridge.json` to `config\project.json`.
2. Set the survey point cloud (`paths.source_cloud`) and, optionally, the QA reference points and preview windows.
3. Put the source `.pln` into `input\`, or pass `--pln`.
4. Run `relief.bat addon install` once per machine, with Archicad closed.

## Command line
```
relief.bat run      [--pln FILE ...] [--cloud FILE ...] [stage options] [parameters]
relief.bat stages   list the stages
relief.bat config   [parameters]          print the effective configuration
relief.bat addon    install | remove | status [--palette-only]
relief.bat test     run the unit tests
```
**Inputs.** Without `--pln` / `--cloud`, the inputs are taken as follows:
- every `.pln` in `input\`;
- the point clouds in `input\`, or `paths.source_cloud` when `input\` has none.

Point clouds: E57, LAS, LAZ, PLY, PCD, PTS, PTX, XYZ/TXT/CSV. Several files are merged; they must share one
coordinate system.

**Stage options.**
- `--stage NAME` runs one stage.
- `--from NAME` and `--until NAME` run a range of stages.
- `--force` re-runs the selected stages even when their results exist.

A stage is skipped when its results exist for the same inputs and settings, so changing a parameter re-runs only
what depends on it.

**Parameters.** Settings are layered, each overriding the one before:
1. `config\default.json`
2. `config\project.json`
3. `--config FILE` (repeatable)
4. `--set section.key=value` (any key; the value is JSON)
5. the flags below

| flag | config key | default |
|---|---|---|
| `--cut 1 3 5` | `contours.cut_sizes_m` | 1, 3, 5 m — one layer per size |
| `--mesh-points N` | `mesh.target_points` | 50,000 |
| `--reduce M` | `contours.smoothing.reduce_tolerance_m` | 0.0 |
| `--min-length M` | `contours.smoothing.min_length_m` | 10 m |
| `--degree N` | `contours.smoothing.nurbs_degree` | 3 |
| `--simplify M` | `contours.smoothing.simplify_tolerance_m` | 0.5 m |
| `--placement MODE` | `placement.mode` | auto |
| `--floor N` | `placement.floor_index` | 0 |
| `--no-3d` | `archicad.contours_3d` | on |
| `--out DIR`, `--work DIR` | `paths.output_dir`, `paths.work_dir` | `output\`, `work\` |

Examples: `--set archicad.contour_pens=[4,2,1]`, `--set ground.method=smrf`, `--config D:\other_site.json`.

## Stages
| stage | per | what it does | results (work folder) |
|---|---|---|---|
| cloud | cloud | point cloud file(s) → LAZ (PDAL; E57 via CloudCompare) | `cloud_raw.laz`, `cloud_summary.json` |
| ground | cloud | voxel thinning, statistical + ELM noise removal, CSF (or SMRF) ground classification | `classified.laz`, `ground.laz` |
| dem | cloud | bare-earth DEM: pits, trees/houses the filter kept, gap filling, spikes, light smoothing | `dem_clean.tif`, `footprint.tif` |
| reference | pln | placement (the point cloud object in the PLN, or the cloud's own coordinates) and elevations, read once from the source PLN | `elevation_reference.json`, `transform.json` |
| contours | pln | **one mesh** → **cut** at every contour level → **smoothing** of every line | `relief.gpkg`, `contours_summary.json`, output DXF |
| archicad | pln | relief-only PLN from the Archicad template: the mesh, the contour Splines + 3D ribbons per layer; verified, saved | output PLN, `archicad_result.json` |
| qa | pln | accuracy vs reference ground points, preview images | `qa\report.md`, `qa\*.png` |

### Mesh, cut, smoothing (contours stage)
1. **Mesh.**
   - The clean DEM is sampled adaptively: dense where the terrain bends, sparse where it is flat.
   - The pipeline uses the smallest height tolerance that stays within `mesh.target_points`, and reports how close
     the mesh is to the DEM.
   - The outline is the survey footprint, as one polygon.
   - Exactly these vertices become the Archicad Mesh.
2. **Cut.**
   - The triangulated mesh is intersected with horizontal planes on whole metres above sea level.
   - The cut lines are exact on the mesh: they end on its outline or close on themselves.
   - A level belongs to every layer whose size divides it, so 15 m appears in both the 1 m and the 5 m layer.
3. **Smoothing** (`contours.smoothing`), applied to every cut line:
   1. **Reduce** (Douglas–Peucker).
   2. **Cull** lines up to `min_length_m` long.
   3. **NURBS**: the line's vertices become control points of a clamped curve of `nurbs_degree`.
   4. **Simplify**: Archicad spline points are picked on that curve, and the spline Archicad draws stays within
      `simplify_tolerance_m` of it.

   Nothing else changes the lines. `contours_summary.json` reports the line heights on the mesh and on the DEM, and
   the number of crossing lines.

### Archicad and the safety stop
- **Which Archicad is used.** The pipeline talks only to the Archicad 28 that has the project it needs open (found
  by its path). If none has it, it starts Archicad on that file. Other instances, Teamwork projects and other
  versions are never touched.
- **Dialogs.** While the pipeline uses an Archicad, its dialogs are watched:
  - Archicad's "invalid elements were fixed" note is confirmed.
  - **Any other dialog stops the pipeline, and nothing is saved.** The dialog text is written to `pipeline.log`.
- **Replacing the output.** The output PLN is recreated from the template unless an Archicad has it open. In that
  case everything on the `Relief - *` layers is replaced in place.
- **Checks before saving.** The pipeline checks the mesh height, the mesh vertex read-back, the 3D ribbon heights,
  and that no pre-existing element disappeared.

### Placement (`placement`)
- `auto` (default): if the PLN contains a point cloud object with the same extent as the input cloud, the relief
  is fitted to it (origin, rotation and Z; min and max Z must agree). Otherwise the cloud's own coordinates are used.
- `coordinates`: X/Y are the cloud coordinates plus `offset`, rotated by `rotation_deg`. `source_z` says whether
  Z is metres a.s.l. or relative to project zero.
- `object`: a matching point cloud object is required.

## Code
```
relief\
  cli.py            command line (argparse) -> config + pipeline
  config.py         layered configuration, validation, overrides
  pipeline.py       the stage list and the runner (skip / force / logging)
  job.py            inputs of a run and where every result goes
  util.py           logging, JSON, file identity, external tools
  stages\           one module per stage, each with run(job, force)
  geometry\         terrain_mesh (mesh, triangulation, cut), smoothing, polyline, raster, transform
  io\               cloud_formats (point cloud readers), pdal, relief_data (relief.gpkg, DXF)
  archicad\         client (JSON API, Tapir, safety stop), session (instances), elements, addon (install)
```
- **Stages.** Stages exchange data only through files in the work folder, so each one can be re-run on its own.
- **Geometry.** The `geometry` modules are pure functions of numpy arrays and are covered by `tests\`.
- **Adding a stage.** Write `relief\stages\<name>.py` with `run(job, force)` and add a `Stage(...)` entry in
  `pipeline.py`.

## Functions
Every function can be imported once the pipeline folder is on `sys.path`, for example in QGIS Python:
```python
import sys; sys.path.insert(0, r"C:\path\to\relief_pipeline")
from relief.config import load_config
from relief.job import discover_inputs
from relief import pipeline

cfg = load_config(assignments=["contours.cut_sizes_m=[1,2,5]"])
clouds, plns = discover_inputs(cfg, clouds=[r"D:\scan.e57"], plns=[r"D:\site.pln"])
code, log_path = pipeline.run(cfg, clouds, plns, pipeline.select(until="contours"))
```

### Entry points
| function | what it does |
|---|---|
| `cli.main(argv=None)` | the command line (`relief.bat` / `python -m relief`); returns the exit code |
| `pipeline.run(cfg, clouds, plns, selected, force=False)` | runs the selected stages for the inputs; returns `(exit code, log file)` |
| `pipeline.select(stage=None, start=None, until=None)` | stage names for one stage or a range |
| `pipeline.STAGES` | the stage list: `Stage(name, scope, module, help)`; each stage module has `run(job, force)` |
| `job.discover_inputs(cfg, clouds=None, plns=None)` | the given files, else the input folder, else `paths.source_cloud` |
| `job.Job(cfg, clouds, pln=None)` | work and output paths of one run: `.c(name)` cloud folder, `.p(name)` PLN folder, `.output_pln`, `.output_dxf` |

### Configuration (`relief.config`)
| function | what it does |
|---|---|
| `load_config(extra_files=(), assignments=(), use_project=True)` | default.json <- project.json <- extra files <- `"key.sub=value"` assignments; validated |
| `parse_assignment("a.b=value")`, `set_value(cfg, keys, value)` | one override; the value is JSON, else a string; unknown keys are rejected |
| `deep_merge(base, over)` | nested merge (sections merged, lists replaced) |
| `validate(cfg)` | raises `ConfigError` for invalid values |
| `cut_sizes(cfg)`, `cut_label(size)` | `{"1m": 1.0, ...}` finest first; `2.5 -> "2.5m"` |
| `settings(cfg, *sections)` | the sections without notes, stored with a result to decide when to re-run |

### Geometry (`relief.geometry`): functions of numpy arrays, no files or Archicad
| function | what it does |
|---|---|
| `terrain_mesh.build_mesh(z, gt, valid, footprint_tif, m)` | the one mesh: outline (+ holes) and adaptive interior points of a DEM; `m` = config `mesh` |
| `terrain_mesh.adaptive_points(z, gt, valid, m)` | the smallest height tolerance within `m["target_points"]` -> `(tolerance, points)` |
| `terrain_mesh.footprint_polygon(footprint_tif, simplify_m)` | the survey footprint as one polygon |
| `terrain_mesh.triangulate(mesh)` | Delaunay triangulation of exactly the mesh vertices -> `(vertices, delaunay, triangles)` |
| `terrain_mesh.cut(v, triangles, level)` | the mesh cut by the plane z = level -> list of `(N, 2)` polylines, exact on the triangles |
| `terrain_mesh.cut_levels(zmin, zmax, sizes)`, `on_size(level, size)` | all levels the sizes need; whether a level belongs to a size |
| `smoothing.smooth_contour(pts, closed, s)` | Reduce -> cull -> NURBS -> Simplify of one line (`s` = `contours.smoothing`); `None` when culled, else `{ctrl, curve}` |
| `smoothing.clamped_nurbs(ctrl, degree)` | clamped, non-periodic B-spline, sampled densely |
| `polyline.rdp_mask(pts, tol)` | Douglas-Peucker keep-mask (scalar or per-vertex tolerance) |
| `polyline.control_points(pts, closed, tol, spacing)` | spline points on a curve |
| `polyline.catmull_rom(points, closed)` | the curve Archicad draws through spline points |
| `polyline.arc_length`, `max_deviation(a, b)`, `crossing_pairs(curves)` | length along a line; largest distance between curves; number of touching pairs |
| `raster.read_raster`, `write_raster`, `sample_raster`, `nearest_fill`, `quadtree_points` | GeoTIFF IO, bilinear sampling, gap fill, adaptive points |
| `transform.apply_transform(t, pts)`, `xy_to_pln(t, xy)` | point cloud coordinates -> PLN coordinates |

### Files (`relief.io`)
| function | what it does |
|---|---|
| `relief_data.write_relief(path, mesh, layers, to_pz)`, `read_relief(path, labels)` | `relief.gpkg`: mesh outline, mesh points, `contours_<size>` layers |
| `relief_data.write_contours_dxf(path, t, layers)` | the contours as 3D DXF in PLN coordinates, one layer per size |
| `cloud_formats.convert_all(job, out)`, `convert_one(job, src, out)` | any supported point cloud file(s) -> one LAZ |
| `cloud_formats.text_reader(src)` | detects delimiter, header and columns of XYZ/TXT/CSV clouds |
| `pdal.pdal_pipeline(job, stages, name)`, `pdal_json(job, args)` | run PDAL |

### Archicad (`relief.archicad`)
| function | what it does |
|---|---|
| `session.connect_project(job, pln)` | the Archicad that has `pln` open, or a new Archicad 28 started on it; with the safety stop |
| `session.scan_instances(host)`, `find_instance`, `project_is_open` | running instances, their ports and open projects |
| `client.Archicad(host, port, watch)` | `.api(command, params)` JSON API; `.tapir(name, params)` Tapir commands |
| `client.DialogWatch(pid)` | watches Archicad's dialogs; `.check()` raises `SafetyStop` |
| `elements.remove_relief_layers(ac, prefix)` | deletes the elements on the relief layers |
| `elements.batched(ac, command, key, items, batch, label)` | creates elements in batches, returns their GUIDs |
| `elements.contour_3d_items(...)`, `ribbon_body(pts, half)` | contour lines as Morph ribbons (3D) |
| `elements.probe_mesh(ac, floor, level)`, `probe_morph(ac, floor)` | learn how this Archicad takes mesh and Morph heights (throw-away test elements) |
| `addon.install(remove=False, palette_only=False)`, `status()` | install / remove / show Tapir and the palette button |

## Requirements
- Windows, Archicad 28 with Tapir (installed by `relief.bat addon install`).
- Python: QGIS 3.44+ (includes GDAL and PDAL) is used automatically. Without QGIS, run
  `powershell -ExecutionPolicy Bypass -File setup_env.ps1`: it creates an environment in
  `%LOCALAPPDATA%\pipeline_env` for every stage from `reference` on. The point cloud stages need PDAL.
- CloudCompare, for E57 input only.
