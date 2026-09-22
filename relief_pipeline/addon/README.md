# Archicad add-on of the relief pipeline

Runs the relief pipeline from inside Archicad 28 with one click: Tapir palette › **Relief from point cloud**.

```
addon\
  install.bat                          installs everything below (install.bat remove = uninstall)
  tapir\TapirAddOn_AC28_Win.apx        Tapir 1.5.9 for Archicad 28 (open source, github.com/ENZYME-APD/tapir-archicad-automation)
  palette\Relief from point cloud.py   the palette button
```

## What is installed
| part | where | why |
|---|---|---|
| Tapir add-on | copied to `%LOCALAPPDATA%\Tapir\Archicad 28\`, added to Archicad's Add-On Manager list (registry, current user; other add-ons are kept, the previous list is backed up next to it) | the JSON commands the pipeline uses to read the project and write the mesh and contours |
| palette button | `Documents\Tapir\custom-scripts\Relief from point cloud.py`, pointing at this pipeline | starts the pipeline for the open project |

## Install
1. Close Archicad: it reads its add-on list only when it starts.
2. Double-click `install.bat`, or run `relief.bat addon install`.
3. Start Archicad and open the Tapir palette (Window › Palettes › Tapir). If the button is not listed, click
   **Reload scripts**.

Other commands:
- `relief.bat addon status` shows what is installed.
- `relief.bat addon install --palette-only` updates only the button, which is safe while Archicad is running.
- `relief.bat addon remove` uninstalls.

## Use
1. Open and **save** the source project. The pipeline reads the saved `.pln`, never the open model.
2. Tapir palette › **Relief from point cloud**.
3. Choose whether to pick point cloud file(s):
   - **Yes**: pick E57 / LAS / LAZ / PLY / XYZ … files.
   - **No**: use the clouds in the `input` folder, or the survey cloud set in `config\project.json`.
4. The pipeline runs in its own console window, so Archicad stays free.
5. A message appears when `output\<project>_ReliefOnly.pln` is ready. Merge it, or hotlink it at the project origin.

The button is only a launcher: it runs `relief.bat run --pln <this project> [--cloud …] --notify`. All logic and
settings are in the pipeline (`config\*.json`). Tapir runs palette scripts with `uv` and offers to install it on
first use.

Not supported:
- **Teamwork projects**: save a solo copy (`.pln`) and open that.
- **Untitled projects**: save first.
- **`_ReliefOnly` files**: run the button in the source project.
