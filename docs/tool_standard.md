# The tool standard

Every tool in `tools\` is built the same way, so a person who knows one knows them all. `test.bat core` checks the
parts marked *checked*.

## Layout
```
tools\<tool_name>\
  README.md          what it does and how to use it (sections below)                    checked
  <command>.bat      the command (one per tool): relief.bat, site_model.bat, ...         checked
  install.bat        once per computer: the toolkit's Python, then the tool's add-on      checked
  uninstall.bat      takes the tool's add-on away (Tapir and the Python stay)             checked
  addon\             the button(s) inside the host program, if the tool has one
  config\
    default.json     every setting, explained by a note: "_<key>" beside it (or "_about"   checked (valid JSON)
                     for a group of them); keys starting with _ are notes, never settings
    examples\        example project.json files, if any
    project.json     this machine's settings (not in git)
  input\             the files of a double-click run (only README.md in git)              checked
  output\            its results (only README.md in git)                                  checked
  <command>\         the code: a Python package named like the command, with cli.py     checked
  tests\             test_*.py: run without the host program, network or real data        checked
  scripts\           scripts that run inside the host program (MAXScript, ...), if any
  examples\          example inputs or results, if any
```

## Names
| what | rule | examples |
|---|---|---|
| the tool's folder | lower case, words joined by `_`; the program it works with and what it makes | `pointcloud_to_archicad_relief`, `autocad_to_archicad`, `archicad_window_ids`, `max_corona_materials` |
| the command | what the tool makes, lower case with `_`, like its button | `relief.bat`, `site_model.bat`, `window_ids.bat`, `corona_materials.bat` |
| the package | the command's name: `<command>.bat` runs `<command>\cli.py` | `relief\`, `site_model\`, `window_ids\`, `corona_materials\` |
| the button | what the tool makes, in words, as a person says it | *Relief from point cloud*, *Site model from AutoCAD*, *Window IDs* |
| the README title | `<what goes in> → <what comes out>` | *Point cloud → Archicad relief* |
| the cache | the tool's folder name, under `%LOCALAPPDATA%\ing_studio_toolkit` | |
| the tests | `tests\test_<command>.py`, or one file per topic | `test_relief.py`; `test_types.py`, `test_layers.py` |

A result file keeps the name of its input, with the tool's suffix (`survey_ReliefOnly.pln`, `plan_FromDWG.pln`,
`project_window_ids.pln`, `model_corona.max`). Those suffixes stay as they are: projects hotlink these files by name.

## Behaviour
- **The command** is a `.bat` of ten lines: it sets `TOOL_DIR`, `TOOL_MODULE` and `TOOL_PYTHON` and calls
  `core\run.cmd`. The tool's code lives in its package; `main(argv)` returns the exit code (0 = done, 1 = failed,
  2 = wrong settings).
- **Without arguments** (a double-click) a tool takes its files from `input\` and writes to `output\`, and the window
  waits for a key at the end. Given files, it works where they are and writes to `output\` in the current folder
  (or `--out`).
- **Settings** come from `config\default.json` ← `config\project.json` ← `--config FILE` ← `--set KEY=VALUE`
  (`ing_core.config`). Unknown keys are errors.
- **Caches** of intermediate results go to `%LOCALAPPDATA%\ing_studio_toolkit\<tool_name>` and are safe to delete.
- **The add-on** for Archicad is a Tapir palette button: `addon\<Button name>.py`, with `TOOL_DIR = r"__TOOL_DIR__"`
  (filled in when it is installed). The button only collects the inputs and starts the tool; the logic stays in the
  package. `<command>.bat addon install|remove|status` handles it, through `ing_core.archicad.addon`.
- **Shared code** goes into `core\ing_core`, never into a copy in a tool. A tool may keep its own version of
  something only for a reason written in its README.
- **Data never goes into git**: drawings, point clouds, models and results stay in `input\` / `output\`, on the
  machine or on the shared drive (`.gitignore` takes care of the usual file types).

## README sections
In this order; a tool adds its own sections (how it works, rules, …) between them where they fit:

| section | says |
|---|---|
| `# <Title>` + a paragraph | what the tool turns into what |
| `## Install` | what to install first, then `install.bat` |
| `## Use` | the button, the double-click, the terminal (a table of commands) |
| `## Input` | what files it takes, in what formats |
| `## Output` | what it makes: files, layers, reports |
| `## Settings` | where the settings are and the ones worth knowing |
| `## If something goes wrong` | the log, the usual problems and their fixes |
| `## Uninstall` | `uninstall.bat` and what stays |
| `## Files` | a table of the tool's files |

The section names are checked; the text is written for the people who use the tool: short sentences, the words they
see on the screen.

## Adding a tool
1. Copy the layout above into `tools\<tool_name>`, named as in "Names".
2. Write the package, its `cli.main`, and the tests; use `ing_core` for logging, settings and Archicad.
3. Write the README and the `input\` / `output\` READMEs.
4. Add a row to the table in the toolkit's `README.md`.
5. Run `test.bat`: every suite, including the layout check, must pass.
