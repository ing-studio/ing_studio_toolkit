# ing_studio_toolkit
A collection of ing studio tools and functions for working with project data: survey data (point clouds), Archicad
models, and the automation between them.

The repo will keep growing, one tool at a time. Each tool is a self-contained folder at the top level. Its own
README explains what it does, what it needs and how to use it.

## Tools
| tool | purpose |
|---|---|
| [`pointcloud_to_archicad_relief/`](pointcloud_to_archicad_relief/README.md) | Builds an Archicad terrain from a point cloud: one mesh, plus contour layers cut from it. |

Open a tool's folder and read its `README.md` to get started.

## Repository layout
```
ing_studio_toolkit\
  README.md            this file: what the repo is and which tools it holds
  .gitignore           repo-wide ignores
  .gitattributes       line endings (Windows scripts keep CRLF)
  <tool_name>\         one folder per tool
    README.md          what the tool does, requirements, setup, usage, functions
    ...                code, config, entry script - only what the tool needs
```

## Getting the tools
```
git clone git@github.com:ing-studio/ing_studio_toolkit.git
cd ing_studio_toolkit
git pull                       later: update all tools
```
The repo can be cloned next to the project data it works on, or anywhere else. Each tool's README says where it
expects its inputs.

## Adding a tool
1. Create a top-level folder named after what the tool does, in lower case with underscores (for example
   `pointcloud_to_archicad_relief`).
2. Put everything the tool needs inside it:
   - a `README.md` covering purpose, requirements, setup, usage and the main functions;
   - an entry script;
   - its configuration, with an example config.

   Keep the tool light: no bundled binaries that can be downloaded, no generated files, no extras it does not
   need to run.
3. Keep project data out of git: inputs, outputs, caches, and machine- or project-specific config go into the
   tool's `.gitignore`.
4. Add one row to the **Tools** table above, linking to the tool's README.
5. Commit with a message that names the tool.

## Conventions
- Tools are independent: one tool never imports code from another tool's folder.
- A tool's README is the single place for its details. This file only lists the tools.
- Windows first (Archicad, QGIS). Each tool's README lists the software it needs.
