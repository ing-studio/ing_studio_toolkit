# 3ds Max model → Corona part materials

Turns a model with hundreds of imported materials (a manufacturer's FBX, a SketchUp export) into a clean Corona
scene: **one group per piece of equipment, one mesh per part inside it, and a small set of distinct Corona "part"
materials**, each based on a material of a finished reference scene. It was made for the Technogym gym equipment:
332 FBX materials became 22 part materials in the sandstone finish of Technogym's own scene.

What it does, step by step (`max_materials.bat stages`):

| step | what | where |
|---|---|---|
| **reference** | the reference scene's Corona materials → a material library (the templates) | 3ds Max |
| **import** | the model's FBX → a raw .max, and the list of its materials with how many meshes use them and their colour | 3ds Max |
| **map** | every material of the model → one part material, by its name and colour (the rules below) | Python |
| **rebuild** | the raw import → one group per equipment; in each, one Editable Mesh per part; one Corona material and one layer per part; meshes lying exactly on top of each other removed | 3ds Max |

3ds Max does its steps without opening its window (`3dsmaxbatch`), so you can keep working in it.

## Install
Once per computer:
1. Install 3ds Max (2025 is tested) with the **Corona** renderer.
2. Double-click **`install.bat`**. It sets up the toolkit's Python and checks that 3ds Max and Corona are there.
   Nothing is added to 3ds Max.

## Use
**Double-click:** put the reference scene (`.max`) and the model (`.fbx`) in `input\`, double-click
**`max_materials.bat`**, and find the results in `output\`.

**In a terminal:**
```
max_materials.bat --model D:\gym\equipment.fbx --reference D:\gym\reference_set.max --out D:\gym\result
```

| command | what it does |
|---|---|
| `max_materials.bat` | every step, on the files in `input\`, results in `output\` |
| `max_materials.bat map` | only the part map: check `<model>_part_map.csv` before a long rebuild |
| `max_materials.bat rebuild --test-groups 5` | rebuild only the first 5 equipment groups, into the work folder: a quick look |
| `max_materials.bat --force` | redo the reference and import steps too (they are reused when their result is newer than the input) |
| `max_materials.bat stages` / `config` / `check` | the steps / the settings a run would use / is 3ds Max with Corona there |
| `max_materials.bat --help` | every option |

A big model takes long (the Technogym FBX is 6.8 GB): check the map, then try `rebuild --test-groups 5`, before
the full rebuild.

## Input
- **The reference scene**: a `.max` whose Corona materials are the templates. Each part names the template it is
  based on (`parts` in the settings), like `Material #975`.
- **The model**: the `.fbx` to convert. The import puts the equipment groups under one node (SketchUp: `Model`,
  `max.model_root`); without it, the scene's top-level nodes are the groups.
- Optionally **`model_materials.json`**: the model's materials, `[{"name": ..., "meshes": ..., "rgb": [r, g, b]}]`.
  Without it, the list is read from the imported model.

## Output
- `<model>_corona.max`: the rebuilt scene, rendered with Corona.
- `<model>_part_map.csv`: every material of the model, how many meshes use it, its colour, its part, and the rule
  that chose it.
- `<model>_part_materials.csv`: the part materials, the template each is based on, and what was changed (diffuse
  colour, glossiness, IOR).

`examples\technogym\` holds the two maps of the Technogym conversion.

## How materials become parts
The rules are in `maxmat\parts.py`:
1. **The maker's own materials** (names starting with `TG`): by the words of the name - belt, upholstery, logo,
   frame, plastic, steps, satin metal … A *diamondblack* or *anthracitesilver* finish is read as *sandstone*, the
   finish of the set.
2. **Other materials**: by keywords first (chrome, steel, rubber, leather …), then by colour: a saturated colour is
   an accent (red, yellow, green, blue), a warm mid tone is sandstone, the rest is a grey by its brightness.
3. A mesh whose material is in no map gets `fallback_part`.

Two meshes on exactly the same spot (same face count and bounding box) are one: the one whose material has the more
meaningful name is kept (`TG…` before generic names before `Material__…`). Every removal is listed in the work
folder's `duplicates.tsv`.

## Settings
`config\default.json`, each with a short note:
- `parts`: the part materials: their template in the reference scene, and the diffuse colour, glossiness and IOR to
  change (null = the template's);
- `fallback_part`: the part of a mesh whose material is in no map;
- `max.version` (`auto` = the newest 3ds Max) and `max.model_root`;
- `paths`: the inputs, the results folder and the work folder, when they are not the default ones.

Put your own values in `config\project.json` (only the keys you change); it stays on your computer. For one run:
`--set max.version=2025`.

## If something goes wrong
- The terminal shows each step, then the result files or the reason it stopped. The full log is
  `max_materials.log` in the work folder; each 3ds Max step writes its own log there too (`reference.log`,
  `import.log`, `restructure.log`) and 3ds Max's listener output (`<step>_listener.log`).
- Work folder: `%LOCALAPPDATA%\ing_studio_toolkit\max_corona_materials\<model>`. Deleting it is safe; the next run
  redoes the steps.
- "parts used but not defined": the rules chose a part that `parts` does not have; add it to the settings.
- Texture maps that are missing on this computer are switched off in the part materials (the maps stay in place, to
  be relinked later with the Asset Tracker).

## Uninstall
Nothing to take away: the tool adds nothing to 3ds Max. `uninstall.bat` says so, and where its cache is. The
toolkit's own `uninstall.bat` removes the toolkit's Python.

## Files
| path | what |
|---|---|
| `max_materials.bat` | the command |
| `install.bat`, `uninstall.bat` | install (the toolkit's Python, a check of 3ds Max) / uninstall |
| `maxmat\` | the tool: `cli` (the steps), `parts` (the part map and its rules), `maxbatch` (running a MAXScript in 3ds Max without its window) |
| `scripts\` | the MAXScripts of the 3ds Max steps: `dump_reference.ms`, `import_model.ms`, `rebuild_parts.ms`. They get their paths from `max_materials.bat` and refuse to run on their own |
| `config\default.json` | the settings |
| `examples\technogym\` | the maps of the Technogym conversion (332 materials → 22 parts) |
| `input\`, `output\` | the files of a double-click run (not in git) |
| `tests\` | `test.bat max_corona_materials` in the toolkit's folder: the part map against the Technogym example, the settings. With `ING_TEST_3DSMAX=1`, also every step in 3ds Max on a small made-up scene (about 1.5 min) |
