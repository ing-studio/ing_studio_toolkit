# ing_studio_toolkit

Tools used at ing studio for survey data, Archicad and 3ds Max. Every tool is built the same way: a command, an
installer and an uninstaller, an add-on button where the host program has one, an `input` and an `output` folder,
its settings, its tests, and a README that explains how to use it. The code they share is one library, `core`.

## Tools
| tool | what it does | command | button |
|---|---|---|---|
| [pointcloud_to_archicad_relief](tools/pointcloud_to_archicad_relief/README.md) | Point cloud → Archicad terrain mesh + contour layers | `relief.bat` | Archicad: *Relief from point cloud* |
| [autocad_to_archicad](tools/autocad_to_archicad/README.md) | AutoCAD site plan + point cloud (+ optional project PDFs) → Archicad site model: terrain, existing and new streets (Armenian street norms), buildings, trees, underground levels, the drawing in 2D. The site's position and the layers' meaning are worked out automatically | `site_model.bat` | Archicad: *Site model from AutoCAD* |
| [archicad_window_ids](tools/archicad_window_ids/README.md) | Window types → IDs Պ-01, Պ-02 … in every window, ID labels on the layer `Window IDs - Floor Plans`, and on `Window Types - Measurements` a worksheet with each type's front view, dimensions and a table (or all of it as output .pln/.pdf files) | `window_ids.bat` | Archicad: *Window IDs* |
| [max_corona_materials](tools/max_corona_materials/README.md) | A 3ds Max model's many imported materials → one group per equipment and a small set of clean Corona part materials, based on a reference scene. `sandstone`: gym scenes re-finished in Technogym's Sand Stone materials (4K maps, black equipment removed or recoloured, previews) | `corona_materials.bat` | – (runs 3ds Max in the background) |

## Get it
```
git clone git@github.com:ing-studio/ing_studio_toolkit.git
```
Then double-click **`install.bat`** in the toolkit's folder (close Archicad first). It sets up the toolkit's Python
once and installs every tool; each tool's own `install.bat` installs just that one. Run `git pull` later to update,
and `install.bat` again if a tool was added or the folder moved.

## Use a tool
Three ways, the same for every tool (see its README):
- **the button** in the host program (Archicad: *Window › Palettes › Tapir*);
- **a double-click** on the tool's command (`relief.bat`, …): it takes the files in the tool's `input\` folder and
  writes the results to its `output\` folder;
- **a terminal**: `relief.bat survey.e57`, `site_model.bat plan.dwg survey.e57`, … (`--help` lists everything).

## How it is organised
```
ing_studio_toolkit\
  install.bat, uninstall.bat   the whole toolkit
  test.bat                     every test suite (test.bat <name> for one)
  core\                        the shared library (ing_core), the launcher, the Python setup
  tools\<tool>\                one folder per tool, all with the same layout
  docs\tool_standard.md        that layout, and how to add a tool
```
- **Python:** one environment for every tool, Python 3.12 with the packages in `core\requirements.txt`, made by
  `install.bat` in `%LOCALAPPDATA%\ing_studio_toolkit\env` (no admin rights). The relief tool prefers QGIS's Python
  when QGIS is installed: it brings PDAL, for new point clouds.
- **Archicad:** the tools talk to Archicad 28 / 29 through [Tapir](https://github.com/ENZYME-APD/tapir-archicad-automation),
  a free add-on that `install.bat` adds (a pinned, checksum-checked release).
- **Caches** of intermediate results: `%LOCALAPPDATA%\ing_studio_toolkit\<tool>`, safe to delete.
- **Data stays out of git:** drawings, point clouds, models and results stay in the tools' `input\` / `output\`
  folders, on your computer, or on the shared drive. Any other folder put in the toolkit's folder is ignored by git.

## Uninstall
`uninstall.bat` in the toolkit's folder takes every button away, removes the Tapir it added and the toolkit's
Python, and offers to delete the caches. A tool's own `uninstall.bat` removes only that tool's button.

## Develop
- `test.bat` runs every test suite; none needs Archicad, AutoCAD, 3ds Max or the network (`set ING_TEST_3DSMAX=1`
  adds max_corona_materials' steps in 3ds Max). `ruff check .` looks for errors in the code (settings in
  `pyproject.toml`); without ruff installed, the toolkit's uv runs it:
  `%LOCALAPPDATA%\ing_studio_toolkit\env\uv\uv.exe tool run ruff check .`
- A new tool follows [the tool standard](docs/tool_standard.md); `test.bat core` checks its layout and its README.
- Shared code goes into `core\ing_core` ([core\README.md](core/README.md)), never into a copy in a tool.
