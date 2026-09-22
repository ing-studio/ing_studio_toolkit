# Point cloud → Archicad relief

Turns a survey point cloud into an Archicad terrain mesh with contour lines.

## Quick start
1. **Install once:** Archicad 28, QGIS 3.44+ (and CloudCompare for E57 files). Then close Archicad and
   double-click `addon\install.bat`.
2. **Run:** open a terminal in the folder with your point cloud and type:
   ```
   relief.bat survey.e57
   ```
   (Use the full path to `relief.bat`, or add this folder to your PATH.)
3. **Open the result** in `output\survey_ReliefOnly.pln`. To bring it into your project, use
   **File › Interoperability › Merge** or place it as a **Hotlink**.

Or, in Archicad, click **Tapir palette › Relief from point cloud** ([how](addon/README.md)).

## What you can give it
| you have | type | result |
|---|---|---|
| only a point cloud | `relief.bat survey.e57` | a new PLN at the cloud's coordinates |
| a project and its point cloud | `relief.bat project.pln survey.e57` | a PLN that lines up with your project |
| only a project | `relief.bat project.pln` | the same, using the cloud set in `config\project.json` |

Point cloud types: E57, LAS, LAZ, PLY, PCD, PTS, PTX, XYZ, TXT and CSV. Your project is only read, never changed.

## What you get
In `output\`:
- `<name>_ReliefOnly.pln` with these layers:
  - **Relief - Terrain Mesh**: the ground, with trees, buildings and noise removed.
  - **Relief - Contours 1m / 3m / 5m**: contour lines, shown in plan and in 3D.
- `<name>_ReliefOnly_contours.dxf`: the same contour lines as a 3D DXF.

The first run on a new point cloud takes a while (about 15 min for 20 million points). Later runs take a few
minutes, because finished steps are reused.

## Common changes
Add these after the file names, for example `relief.bat survey.e57 --contours 0.5 2 --out D:\results`.

| I want… | add |
|---|---|
| other contour intervals | `--contours 0.5 2 10` (metres; one layer each) |
| smoother contour lines | `--simplify-tolerance 1` (default 0.5) |
| fewer tiny contour loops | `--min-line-length 25` (default 10 m) |
| a lighter file | `--mesh-points 20000` (default 50000) and/or `--no-3d` |
| a more detailed terrain | `--mesh-points 100000` |
| the results somewhere else | `--out D:\results` |
| to redo everything from scratch | `--force` |

## All options
| option | what it does | default |
|---|---|---|
| `--out DIR` | where the results go | `output` |
| `--no-3d` | contour lines in plan only | plan + 3D |
| `--contours N …` | contour intervals in metres | 1 3 5 |
| `--mesh-points N` | the most points the terrain mesh may have | 50000 |
| `--min-line-length M` | leave out contour lines shorter than this | 10 |
| `--simplify-tolerance M` | how much the lines are smoothed | 0.5 |
| `--reduce-tolerance M` | straighten lines before smoothing (0 = keep every bend) | 0 |
| `--curve-degree N` | 1 = straight segments, 3 = smooth curves | 3 |
| `--placement auto\|object\|coordinates` | with a project: line up with its point cloud object, or use the cloud's coordinates | auto |
| `--story N` | the story the relief goes on | 0 |
| `--origin auto\|keep\|X,Y` | new PLN only: where the project origin goes (`auto` moves it near a cloud that is far from 0,0) | auto |
| `--force` | redo every step instead of reusing earlier results | |
| `--only STEP` / `--from STEP` / `--until STEP` | run some steps only (`relief.bat stages` lists them) | |
| `--set KEY=VALUE` | change any setting for this run, e.g. `--set dem.resolution=0.25` | |

`relief.bat --help` shows the same list.

## Settings for a project
To keep settings for a project, copy `config\examples\tbilisyan_bridge.json` to `config\project.json` and edit it.
It overrides `config\default.json`, where every setting has a short note. `project.json` stays on your computer.

## If something goes wrong
- The terminal shows each step, then either the result files or the reason it failed. `WARN` lines are worth a
  look; `SKIP` means a step was reused from an earlier run.
- Full details are in `pipeline.log`. Its path is printed at the start and end of every run.
- The tool opens its own Archicad. If Archicad shows an unexpected message, the run stops and nothing is saved.
- Intermediate files are kept in `%LOCALAPPDATA%\ing_studio_toolkit\pointcloud_to_archicad_relief`. Deleting them is
  safe; the next run rebuilds them.
- No QGIS? `setup_env.ps1` makes a Python environment instead. It works only for point clouds that were already
  processed once, because new point clouds need QGIS.
