# ing_studio_toolkit
This repo contains different tools & functions to work with data: survey data, Archicad models, and the automation
between them. Each tool lives in its own folder, with its own README, configuration and tests.

## Tools
| folder | what it does | entry |
|---|---|---|
| [`pointcloud_to_archicad_relief/`](pointcloud_to_archicad_relief/README.md) | Point cloud (E57, LAS/LAZ, PLY, XYZ …) + Archicad project → relief-only Archicad project: **one terrain mesh** and **contour layers cut from it** (1 m / 3 m / 5 m by default, configurable), as plan splines and 3D lines, plus a 3D DXF of the contours. Includes an Archicad 28 add-on (Tapir palette button). | `pointcloud_to_archicad_relief\relief.bat run --pln site.pln --cloud scan.e57` |

## Relief pipeline in short
```
pointcloud_to_archicad_relief\relief.bat run --pln D:\site.pln --cloud D:\scan.e57                 build the relief
pointcloud_to_archicad_relief\relief.bat run --pln D:\site.pln --cut 1 2 5 --mesh-points 30000     other sizes / lighter mesh
pointcloud_to_archicad_relief\relief.bat run --stage archicad --force                              rebuild only the Archicad file
pointcloud_to_archicad_relief\relief.bat addon install                                             Archicad add-on (Archicad closed)
pointcloud_to_archicad_relief\relief.bat stages | config | test
```
- **Stages**: cloud → ground → dem → reference → contours → archicad → qa. Each stage is cached, so a re-run only
  redoes what changed.
- **Settings**: `config\default.json`, overridden by `config\project.json` (local, not in git; examples are in
  `config\examples\`), then by `--set key=value` and the flags.
- **Output**: `output\<source>_ReliefOnly.pln` and `output\<source>_ReliefOnly_contours.dxf`. The source project
  is only read, never saved.

See [pointcloud_to_archicad_relief/README.md](pointcloud_to_archicad_relief/README.md) for every option, the stages, and the functions of each
module. [pointcloud_to_archicad_relief/addon/README.md](pointcloud_to_archicad_relief/addon/README.md) covers the Archicad button.

## Conventions for tools in this repo
- One folder per tool, self-contained: code, `README.md`, configuration, tests, and an entry script.
- No project data in git: inputs, outputs, caches and machine- or project-specific config are ignored. Each tool
  ships example configs instead.
- Windows first (Archicad, QGIS). A tool's README lists what it needs.
