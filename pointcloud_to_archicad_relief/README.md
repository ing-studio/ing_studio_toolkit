# pointcloud_to_archicad_relief

Turns a survey point cloud into an Archicad terrain.

**You give:** a point cloud, and optionally the Archicad project it belongs to.
**You get:** `<name>_ReliefOnly.pln` with:

| layer | content |
|---|---|
| Relief - Terrain Mesh | one clean terrain mesh (trees, buildings and noise removed) |
| Relief - Contours 1m | contour lines every 1 m |
| Relief - Contours 3m | contour lines every 3 m |
| Relief - Contours 5m | contour lines every 5 m |

You also get `<name>_ReliefOnly_contours.dxf`, the same contour lines as a 3D DXF.

Contours show in plan and in 3D. Bring the result into your project with **File › Interoperability › Merge**, or
place it as a **Hotlink**. Your own project is never changed.

## Setup (once per computer)
1. Install **Archicad 28** and **QGIS 3.44+**. To read E57 files, also install **CloudCompare**.
2. Close Archicad and double-click `addon\install.bat`. It installs the Tapir add-on and the palette button.

## Use
Run from a terminal in the folder where you want the results:

```
relief.bat survey.e57                      point cloud only -> a new PLN is made
relief.bat project.pln survey.e57          placed to match the point cloud in your project
relief.bat project.pln                     uses the survey cloud set in config\project.json
```

Or in Archicad: **Tapir palette › Relief from point cloud** (see [addon/README.md](addon/README.md)).

The first run on a point cloud takes a while (minutes to hours for a big E57). After that, runs take a few
minutes, because finished steps are reused.

## Options
| option | what it does | default |
|---|---|---|
| `--out DIR` | where the results go | current folder |
| `--contours 1 3 5` | contour intervals in metres, one layer each | 1 3 5 |
| `--mesh-points N` | mesh size: fewer points = a lighter mesh | 50000 |
| `--no-3d` | contours in plan only | off |
| `--reduce`, `--min-length`, `--degree`, `--simplify` | contour smoothing | 0, 10 m, 3, 0.5 m |
| `--origin auto\|keep\|X,Y` | new PLN only: where the project origin is | auto |
| `--placement auto\|object\|coordinates` | with a PLN: how the relief is placed | auto |
| `--force` | redo everything instead of reusing finished steps | off |

Run `relief.bat --help` for the full list.

**Placement.**
- **With a PLN:** the relief goes where the point cloud sits in that project. If the project has no point cloud
  object, the cloud's own coordinates are used.
- **Without a PLN:** the cloud's coordinates are used, and heights are metres above sea level. If the cloud is far
  from 0,0, the project origin is moved next to it (rounded to 100 m, shown in the log). Archicad is inaccurate
  far from its origin.

## Settings
- `config\default.json` holds every setting, with a short note on each one.
- For project-specific values, copy `config\examples\tbilisyan_bridge.json` to `config\project.json` and edit it.
  That file stays on your computer and is not shared through git.
- To change a single value for one run, use `--set`, for example `--set dem.resolution=0.25`.

## Good to know
- **Cache.** Intermediate files are kept in `%LOCALAPPDATA%\ing_studio_toolkit\pointcloud_to_archicad_relief`.
  You can delete them at any time; they are rebuilt.
- **Log.** Each run writes a log, `pipeline.log`, into that cache folder.
- **Archicad runs on its own.** The tool opens Archicad itself. If Archicad shows an unexpected message, the run
  stops and nothing is saved.
- **Without QGIS.** Run `setup_env.ps1` to create a Python environment instead. This works when the point cloud
  steps are already cached; processing a new point cloud needs QGIS.
