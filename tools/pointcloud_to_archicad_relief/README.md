# Point cloud → Archicad relief

Turns a survey point cloud into an Archicad terrain mesh with contour lines.

## Install
Once per computer:
1. Install Archicad 28 or 29 and QGIS 3.44+ (it reads new point clouds). For E57 files, also install CloudCompare.
2. Close Archicad and double-click **`install.bat`**. It sets up the toolkit's Python and adds the
   **Relief from point cloud** button to Archicad's Tapir palette (and Tapir itself, if it is missing).
3. Start Archicad and open **Window › Palettes › Tapir**. If the button is missing, click **Reload scripts**.

Run `install.bat` again after moving the toolkit folder.

## Use
**In Archicad**
1. Open and **save** your project.
2. Click **Relief from point cloud** in the Tapir palette.
3. Pick the point cloud file(s), or choose **No** to use the survey cloud set in `config\project.json`.
4. The tool runs in its own window, so you can keep working. A message appears when it finishes.
5. The result, `<project>_ReliefOnly.pln`, is in the `output` folder next to your project. To bring it into your
   project, use **File › Interoperability › Merge** or place it as a **Hotlink**.

Teamwork projects are not supported. Save a solo copy of the project (`.pln`) and run the button there.

**Double-click:** put the point cloud (and, if you like, the project) in `input\`, double-click **`relief.bat`**,
and find the result in `output\`.

**In a terminal**, in the folder with your point cloud:
```
relief.bat survey.e57
```
(Use the full path to `relief.bat`, or add this folder to your PATH.) The result goes to an `output` folder there.

| you have | type | result |
|---|---|---|
| only a point cloud | `relief.bat survey.e57` | a new PLN at the cloud's coordinates |
| a project and its point cloud | `relief.bat project.pln survey.e57` | a PLN that lines up with your project |
| only a project | `relief.bat project.pln` | the same, using the cloud set in `config\project.json` |
| the files in `input\` | `relief.bat` | the same, with the results in `output\` |

Your project is only read, never changed. The first run on a new point cloud takes a while (about 15 min for 20
million points). Later runs take a few minutes, because finished steps are reused.

## Input
- Point clouds: E57, LAS, LAZ, PLY, PCD, PTS, PTX, and text formats (XYZ, TXT, CSV, ASC…). Several are merged into
  one relief.
- Optionally the Archicad project (`.pln`) the relief must line up with: with its point cloud object, or at the
  cloud's coordinates.

## Output
- `<name>_ReliefOnly.pln` with these layers:
  - **Relief - Terrain Mesh**: the ground, with trees, buildings and noise removed.
  - **Relief - Contours 1m / 3m / 5m**: contour lines, shown in plan and in 3D.
- `<name>_ReliefOnly_contours.dxf`: the same contour lines as a 3D DXF.

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

`relief.bat --help` shows the same list. Other commands: `relief.bat stages` (the steps), `relief.bat config` (the
settings a run would use), `relief.bat addon install|remove|status`.

## Settings
Every setting, each with a short note, is in `config\default.json`. To keep settings for a project, copy
`config\examples\tbilisyan_bridge.json` to `config\project.json` and edit it. It overrides `default.json` and stays
on your computer (not in git).

## If something goes wrong
- The terminal shows each step, then either the result files or the reason it failed. `WARN` lines are worth a
  look; `SKIP` means a step was reused from an earlier run.
- Full details are in `pipeline.log`. Its path is printed at the start and end of every run.
- The tool opens its own Archicad. If Archicad shows an unexpected message, the run stops and nothing is saved.
- Intermediate files are kept in `%LOCALAPPDATA%\ing_studio_toolkit\pointcloud_to_archicad_relief`. Deleting them is
  safe; the next run rebuilds them.
- No QGIS? The toolkit's Python is used instead. It works only for point clouds that were already processed once,
  because new point clouds need QGIS (PDAL).
- The button says the tool is not found: the toolkit folder has moved. Run `install.bat` again.

## Uninstall
Double-click **`uninstall.bat`**: it takes the button out of the Tapir palette. Tapir and the toolkit's Python stay
for the other tools; the toolkit's own `uninstall.bat` removes everything.

## Files
| path | what |
|---|---|
| `relief.bat` | the command |
| `install.bat`, `uninstall.bat` | install / uninstall (the toolkit's Python, the palette button) |
| `addon\Relief from point cloud.py` | the palette button (it only starts `relief.bat`) |
| `relief\` | the tool: `cli`, `pipeline` and its `stages\` (cloud, ground, dem, reference, contours, archicad), `job` (inputs and result paths), `config`, `geometry\` (polylines, smoothing), `io\` (point cloud formats, PDAL, the relief data). Archicad, logging, settings and the terrain mesh come from the toolkit's library (`core\ing_core`) |
| `config\default.json`, `config\examples\` | the settings |
| `input\`, `output\` | the files of a double-click run (not in git) |
| `tests\` | `test.bat pointcloud_to_archicad_relief` in the toolkit's folder: settings, inputs, contour smoothing, the command line |
