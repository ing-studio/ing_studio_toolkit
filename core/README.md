# core — the toolkit's library and launcher

What every tool shares, so it exists once:

| path | what |
|---|---|
| `run.cmd` | the launcher: a tool's `.bat` sets `TOOL_DIR`, `TOOL_MODULE` (and `TOOL_PYTHON=qgis` to prefer QGIS's Python) and calls it. It finds the Python, puts `core\` and the tool's folder on `sys.path`, runs the tool's `main()`, and returns its exit code |
| `setup_env.ps1` | makes the toolkit's Python: Python 3.12 with `requirements.txt`, in `%LOCALAPPDATA%\ing_studio_toolkit\env` (no admin rights). Every `install.bat` runs it |
| `requirements.txt` | the Python packages, pinned |
| `ing_core\` | the library (below) |
| `tests\` | `test.bat core`: settings, the add-on installer, every tool's launcher |

## ing_core
| module | what |
|---|---|
| `util` | the toolkit's folders (`TOOLKIT_DIR`, `LOCAL_DIR`), logging (`log`, `ok`, `warn`, `skip`, `section`; coloured on a console, plain in the log file), JSON files, file signatures, `input_files` (a tool's `input\` folder), external programs (`tool`, `run`) |
| `config` | a tool's settings: `config\default.json` ← `config\project.json` ← `--config` files ← `--set KEY=VALUE`; `load(tool_dir, validate, ...)`; `settings()` (the sections a cached result depends on) |
| `archicad.client` | the Archicad JSON API and Tapir commands, the Archicad version in use, and the safety stop: an unexpected Archicad dialog stops the tool before anything is saved |
| `archicad.session` | the Archicad a tool works in: finds or starts the one with the project, never opens a file twice |
| `archicad.elements` | layers, stories, meshes, polylines, splines, morphs in Archicad |
| `archicad.addon` | Tapir (pinned release, checked by SHA-256, added to Archicad's add-on list) and each tool's palette buttons |
| `geometry.raster` | GeoTIFF rasters: read, write, sample, fill gaps |
| `geometry.terrain_mesh` | an adaptive terrain mesh from a raster |
| `cli` | `python -m ing_core tapir install\|remove\|status` and `python -m ing_core test` (the root `install.bat`, `uninstall.bat`, `test.bat` use it) |

`uid_assignment` keeps its own small Archicad client (`uids\archicad.py`): its palette button runs inside Tapir's
Python, which has only the standard library. It uses `ing_core` only to install itself.

## Changing the library
Every tool depends on it: run `test.bat` (all suites) after a change, not only the suite of the tool you work on.
