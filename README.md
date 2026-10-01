# ing_studio_toolkit

Tools used at ing studio for survey data and Archicad. Each tool is in its own folder and has a README that
explains how to use it.

## Tools
| tool | what it does |
|---|---|
| [pointcloud_to_archicad_relief](pointcloud_to_archicad_relief/README.md) | Point cloud → Archicad terrain mesh + contour layers |
| [autocad_to_archicad](autocad_to_archicad/README.md) | AutoCAD site plan + point cloud (+ optional project PDFs) → Archicad site model: terrain, existing and new streets (Armenian street norms), buildings, trees, underground levels, the drawing in 2D. The site's position and the layers' meaning are worked out automatically |
| [uid_assignment](uid_assignment/README.md) | Archicad add-on (Tapir palette button): window types → IDs Պ-01, Պ-02 … in every window, ID labels on the layer `Window IDs - Floor Plans`, and on `Window Types - Measurements` a worksheet with each type's front view, dimensions and a table (or all of it as output .pln/.pdf files) |

## Get it
```
git clone git@github.com:ing-studio/ing_studio_toolkit.git
```
Run `git pull` later to update.

## Adding a tool
- Create a new folder with a clear lower-case name, like `pointcloud_to_archicad_relief`.
- Keep everything the tool needs in that folder, including a short README.
- Keep the tool light: leave out project data, results and files the tool can download.
- Add a row to the table above.
