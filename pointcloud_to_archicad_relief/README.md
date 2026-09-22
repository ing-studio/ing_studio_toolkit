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
Open a terminal in any folder and give the tool your files:

```
relief.bat survey.e57                      point cloud only -> a new PLN is made
relief.bat project.pln survey.e57          placed to match the point cloud in your project
relief.bat project.pln                     uses the survey cloud set in config\project.json
```

The results go into an `output` folder inside the folder you ran the command from. Use `--out DIR` to put them
somewhere else.

Or in Archicad: **Tapir palette › Relief from point cloud** (see [addon/README.md](addon/README.md)).

The first run on a point cloud takes a while (about 15 minutes for a 20-million-point E57). After that, a run
takes a few minutes, because finished steps are reused.

## Options
Add options after the file names, for example:
```
relief.bat survey.e57 --contours 0.5 1 5 --mesh-points 80000 --out D:\results
```

**Output**
| option | what it does | default |
|---|---|---|
| `--out DIR` | folder for the results | `output` |
| `--no-3d` | contour lines in plan only (faster, lighter file) | also in 3D |

**Terrain**
| option | what it does | default |
|---|---|---|
| `--contours 1 3 5` | contour line intervals in metres; each gets its own layer | 1 3 5 |
| `--mesh-points N` | most points the terrain mesh may have. Fewer = lighter file, more = finer detail | 50000 |

**Contour lines**: how the lines are cleaned and smoothed.
| option | what it does | default |
|---|---|---|
| `--min-line-length M` | leaves out lines up to this long in metres (small bumps and dips) | 10 |
| `--simplify-tolerance M` | how far the smoothed line may move from the exact one. Larger = smoother, fewer points | 0.5 |
| `--reduce-tolerance M` | straightens the line before smoothing. 0 keeps every bend | 0 |
| `--curve-degree N` | 1 = straight segments, 3 = smooth curves | 3 |

**Placement**
| option | what it does | default |
|---|---|---|
| `--placement MODE` | with a PLN: `auto` matches the point cloud in the project if it has one, otherwise uses coordinates. `object` must match it; `coordinates` uses the cloud's own coordinates | auto |
| `--story N` | the story the relief goes on (coordinates placement) | 0 |
| `--origin auto\|keep\|X,Y` | new PLN only: `auto` moves the project origin next to a cloud that is far from 0,0. `keep` uses the cloud's coordinates; `X,Y` makes this cloud point the origin | auto |

- **With a PLN,** the relief goes where the point cloud sits in that project.
- **Without a PLN,** heights are the cloud's Z values. The project origin moves only when the cloud is more than
  1 km from 0,0; the log shows where it went.

**Running**
| option | what it does |
|---|---|
| `--force` | redo every step instead of reusing finished ones |
| `--only STEP`, `--from STEP`, `--until STEP` | run one step or a range of steps (`relief.bat stages` lists them) |
| `--cache DIR` | folder for intermediate files |

`relief.bat --help` shows the same list in the terminal.

## Settings
- `config\default.json` holds every setting, with a short note on each one.
- For project-specific values, copy `config\examples\tbilisyan_bridge.json` to `config\project.json` and edit it.
  That file stays on your computer and is not shared through git.
- To change a single value for one run, use `--set`, for example `--set dem.resolution=0.25`.

## Good to know
- **Cache.** Intermediate files are kept in `%LOCALAPPDATA%\ing_studio_toolkit\pointcloud_to_archicad_relief`.
  You can delete them at any time; they are rebuilt.
- **What you see while it runs.** The run is split into its steps (cloud, ground, dem, reference, contours,
  archicad). Each line is marked `INFO`, `SKIP` (reused from an earlier run), ` OK `, `WARN` or `FAIL`, in colour in
  the terminal. At the end you get either the result files or the reason it failed.
- **Log file.** Every run also writes `pipeline.log` into the cache folder, with full details of any error. The
  path is printed at the start and end of each run.
- **Archicad runs on its own.** The tool opens Archicad itself. If Archicad shows an unexpected message, the run
  stops and nothing is saved.
- **Without QGIS.** Run `setup_env.ps1` to create a Python environment instead. This works when the point cloud
  steps are already cached; processing a new point cloud needs QGIS.
