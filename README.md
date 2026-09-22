# ing_studio_toolkit

Tools used at ing studio for survey data and Archicad. Each tool is in its own folder and has a README that
explains how to use it.

## Tools
| tool | what it does |
|---|---|
| [pointcloud_to_archicad_relief](pointcloud_to_archicad_relief/README.md) | Point cloud → Archicad terrain mesh + contour layers |

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
