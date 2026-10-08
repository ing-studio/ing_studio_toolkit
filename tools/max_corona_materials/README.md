# 3ds Max model → Corona part materials

Turns a model with hundreds of imported materials (a manufacturer's FBX, a SketchUp export) into a clean Corona
scene: **one group per piece of equipment, one mesh per part inside it, and a small set of distinct Corona "part"
materials**, each based on a material of a finished reference scene. It was made for the Technogym gym equipment:
332 FBX materials became 22 part materials in the sandstone finish of Technogym's own scene.

It also **re-finishes scenes in Technogym's Sand Stone Collection** (`corona_materials.bat sandstone`): the
catalogue's Warm Titanium, Speckled Stone and Clay finishes as Corona Physical materials with texture maps made at
4096 px, the black versions of the equipment removed, every piece at its real size with rounded edges, all the scenes
in one file, and preview renders. See "Sand Stone finish" below.

What it does, step by step (`corona_materials.bat stages`):

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
**`corona_materials.bat`**, and find the results in `output\`.

**In a terminal:**
```
corona_materials.bat --model D:\gym\equipment.fbx --reference D:\gym\reference_set.max --out D:\gym\result
```

| command | what it does |
|---|---|
| `corona_materials.bat` | every step, on the files in `input\`, results in `output\` |
| `corona_materials.bat map` | only the part map: check `<model>_part_map.csv` before a long rebuild |
| `corona_materials.bat rebuild --test-groups 5` | rebuild only the first 5 equipment groups, into the work folder: a quick look |
| `corona_materials.bat --force` | redo the reference and import steps too (they are reused when their result is newer than the input) |
| `corona_materials.bat sandstone` | the scenes in `input\sandstone\` re-finished in Sand Stone, together in one file in `output\sandstone\` (see "Sand Stone finish") |
| `corona_materials.bat sandstone A.max B.max --out D:\gym\hd` | the same for these scenes |
| `corona_materials.bat stages` / `config` / `check` | the steps / the settings a run would use / is 3ds Max with Corona there |
| `corona_materials.bat --help` | every option |

A big model takes long (the Technogym FBX is 6.8 GB): check the map, then try `rebuild --test-groups 5`, before
the full rebuild.

## Input
- **The reference scene**: a `.max` whose Corona materials are the templates. Each part names the template it is
  based on (`parts` in the settings), like `Material #975`.
- **The model**: the `.fbx` to convert. The import puts the equipment groups under one node (SketchUp: `Model`,
  `max.model_root`); without it, the scene's top-level nodes are the groups.
- Optionally **`model_materials.json`**: the model's materials, `[{"name": ..., "meshes": ..., "rgb": [r, g, b]}]`.
  Without it, the list is read from the imported model.
- For `sandstone`: **the scenes** (`.max`), in `input\sandstone\` or on the command line. They are only read.

## Output
- `<model>_corona.max`: the rebuilt scene, rendered with Corona.
- `<model>_part_map.csv`: every material of the model, how many meshes use it, its colour, its part, and the rule
  that chose it.
- `<model>_part_materials.csv`: the part materials, the template each is based on, and what was changed (diffuse
  colour, glossiness, IOR).

`examples\technogym\` holds the two maps of the Technogym conversion.

`sandstone` writes to its output folder:
- `<name> - Sand Stone.max`: the scenes re-finished, at real size, in one file (renderer: Corona). `<name>` is what
  the scenes' names begin with (`Technogym Equipment` for `Technogym Equipment Part 1` ... `Part 4`). Each scene's
  equipment is under a dummy named after the scene (select it with its children to move or hide a scene), arranged
  in rows on the floor (z = 0), 1 m apart, the scenes side by side; with `sandstone.combine` false, each scene is its
  own `<scene> - Sand Stone.max`;
- `maps\`: the texture maps the materials use, and the scenes' logo and screen images. Keep them with the scenes;
  if the folder moves, 3ds Max's Asset Tracking relinks them;
- `previews\`: `material_board.png` (every Sand Stone material on a sample) and Corona renders of every scene: all
  its equipment and close-ups of the main pieces;
- `sandstone_equipment.csv`: every piece of equipment, kept / removed / recoloured, and why, and its real size
  (width, depth, height in mm, as saved);
- `sandstone_materials.csv`: every material of the scenes, the Sand Stone material it became, and why.

## How materials become parts
The rules are in `corona_materials\parts.py`:
1. **The maker's own materials** (names starting with `TG`): by the words of the name - belt, upholstery, logo,
   frame, plastic, steps, satin metal … A *diamondblack* or *anthracitesilver* finish is read as *sandstone*, the
   finish of the set.
2. **Other materials**: by keywords first (chrome, steel, rubber, leather …), then by colour: a saturated colour is
   an accent (red, yellow, green, blue), a warm mid tone is sandstone, the rest is a grey by its brightness.
3. A mesh whose material is in no map gets `fallback_part`.

Two meshes on exactly the same spot (same face count and bounding box) are one: the one whose material has the more
meaningful name is kept (`TG…` before generic names before `Material__…`). Every removal is listed in the work
folder's `duplicates.tsv`.

## Sand Stone finish
`corona_materials.bat sandstone` turns scenes of Technogym equipment into the **Sand Stone Collection**, in the
finishes of Technogym's catalogue ("Signature finishes and materials"), with their colours measured on the
catalogue's swatches:

| Sand Stone material | what | how |
|---|---|---|
| **Warm Titanium** | frames, tubes, metal parts | a satin champagne metal with a fine metallic-paint flake |
| **Speckled Stone** | casings and covers | warm off-white with fine dark specks and mica flakes, like the catalogue's swatch |
| **Clay** upholstery | seats, pads | pebble-grain vegan leather, a soft sheen |
| Clay soft-touch, Clay urethane | handles, caps, trims; dumbbells, plates, balls, mats | the clay tone, moulded or satin |
| Umber, Taupe, Ivory, Espresso rubber | the other dark, mid, light and rubber parts | warm tones instead of greys and black |
| Running belt, brushed and polished steel, Technogym yellow, red stop button, logos | as named | logos keep their own image, printed in the Sand Stone colours |

Every texture is made by code (`corona_materials\maps.py`): **4096 px and seamless**, mapped triplanar at its real
size (a speck is 0.1-0.3 mm, a leather pebble about 1 mm), so it needs no UVs and never stretches. Every material
has Corona Round Edges, so CAD-sharp edges catch the light like real ones (and plain parts get real chamfers, step 6).

What happens to the equipment (`corona_materials\sandstone.py`):
0. **Real size.** The FBX import read SketchUp's inches at 10 mm, so its equipment (everything under `Model`) was
   2.54 times too small: a wellness ball was 218 mm across. Each piece is scaled so that its meshes' inches are
   25.4 mm (`import_unit_mm`), which also brings a piece scaled by hand in its scene (the black free-weights rig in
   Part 1, 2.9 times) to its real size. That matches Technogym's published sizes: the wellness ball 553 mm (550), the two-tier dumbbell rack 2514 x 659 mm
   (2522 x 667), the Reform 2468 x 889 mm (2460 x 890), the Skillrun 1836 x 933 x 1703 mm (1850 x 870 x 1680).
   Technogym's own Artis models, merged in from elsewhere, are real already (the Artis Run 2058 x 890 x 1578 mm, sold
   at 2060 x 885 x 1605) and keep their size. Everything after this works in real millimetres.
1. Equipment **hidden in its scene** was put away as not needed (in Part 1: copies of machines shown in Parts 2
   and 4, a 15 m strip of floor): it is **removed**. **Black equipment** (a *diamondblack* / *anthracitesilver*
   finish, or mostly dark): when the scenes show the same product in Sand Stone too (the same real size within
   1.5 cm), the black one is **removed**; otherwise it is **recoloured** in Sand Stone and put on the layer
   *Sand Stone - recoloured (was black)*, so it can be hidden or deleted in one go.
2. The **colour swatches** some models carry (small red / green / blue / yellow cubes beside a machine) and the
   **free-space zones** drawn on the floor (flat coloured rectangles at the treadmills) are removed: they are not
   things.
3. **Overlaps are cleaned** (`scripts\clean_scene.ms`). SketchUp models carry surfaces that lie on each other, which
   flicker in renders in ragged patches of two colours:
   - the same surface twice (exported once per side, or once more in a component, sometimes a hair apart): the
     objects whose boxes agree to 0.4 mm and whose surfaces agree to 2 % are one; the copy whose material has the
     less meaningful name is deleted (a black frame lying on its Sand Stone twin, an `_auto_` face on a TG part).
     Parts that only share a box (a dumbbell's embossed number and its face) differ in surface and stay;
   - a screen, a label or a trim lying in the plane of a bigger part (a treadmill's display on its console, a logo
     plate on a cover), as its own object or inside the same mesh: its faces in that plane are lifted 1 mm off the
     part, so they lie on it (all of them: a rubber disc on a dumbbell's face lies partly over a groove, and lifting
     only some of its faces would leave steps that render as dark lines);
   - faces lying exactly on another face of the same mesh (same three corners) are deleted (step 5).
   The log lists every object deleted or lifted.
4. Every material becomes a Sand Stone material: by the rules of `parts.py` (name, then colour), with overrides for
   the parts those rules cannot tell apart (`OVERRIDES`). `sandstone_materials.csv` lists them all.
5. **Round parts are made smoother** (`scripts\smooth_rounds.ms`). SketchUp exports a roller, a tube or a disc as a
   few flat facets, usually with every triangle's corners unwelded, so it shows its facets and a polygon for an
   outline. Every mesh is welded (0.5 mm, at most a tenth of its thickness: SketchUp leaves corners up to half a
   millimetre apart, and the seams show as lines), its duplicate faces deleted, and smoothed again by angle: rounds blend,
   edges sharper than 30° stay hard. Round objects - mostly curved, like rollers, tubes, bars, handles, discs - get a
   **TurboSmooth** that keeps the hard edges and material borders sharp: none in the viewport (the model's own faces,
   smoothly shaded), 1 iteration in renders (rounder outlines). Raise `smooth_iterations` for more polygons in the
   viewport. A round object lying face to face on another (a screen's bezel, a cover flush on a frame) gets no
   TurboSmooth: its subdivided surface would push through the other (a bezel through its screen).
   Flat objects with rounded edges (pads, plates, frames, panels) get a **Weighted Normals** modifier instead: the
   normals are weighted by the faces' area, so a big flat face stays flat and its rim takes the bend (without it, the
   long thin triangles around a slot, a hole or a bolt streak a flat panel). Dense meshes with smoothing groups of
   their own (Technogym's Artis machines) are left as they are; dense meshes with every face in one smoothing group
   (their hard edges smoothed over: screens and consoles that shade in blotches and stars) are smoothed like the
   others. The modifiers are live: change or delete them on any object. Instances (SketchUp components) stay
   instances.
6. **Sharp edges are rounded** (`scripts\chamfer_edges.ms`), as nothing made is knife-sharp. Every solid part that
   is not round - frames, covers, plates, floor tiles, pads, boxes, bars, brackets - gets a **real rounded chamfer**
   on every edge sharper than 40°: a live *Chamfer* modifier (change its amount on any object), and a *Weighted
   Normals* modifier that keeps the flat faces flat, so the chamfer shades like a fillet, in the viewport too. Its
   size is the part's: 15 % of its smallest dimension, at most a quarter of its wall's thickness and the material's
   `chamfer_mm` (6 mm for Warm Titanium, 10 for Speckled Stone, 16 for upholstery, 5 for the plastics and urethane,
   2 for steel ...); under 0.5 mm it would not show and is left out (bolts, nuts). Round objects keep their
   TurboSmooth instead (it would serrate a chamfer under it), and objects of several materials and open surfaces keep
   their edges. Every chamfer is checked when it is made - nothing torn open, no face collapsed or folded, nothing
   sticking out - and taken off again when it fails: the check decides, not a guess about the shape. In renders every
   edge, chamfered or not, is also rounded by Corona Round Edges (`round_mm`: 6 mm for Warm Titanium, 8 for Speckled
   Stone, 12 for upholstery, 5 for the plastics, 2 for steel and screens ...), in its *Precise* mode, which also
   rounds where two objects or two parts of a mesh meet: a tube going into a frame, a bar into its bracket read as
   one welded or moulded piece instead of two parts with a crease between them.
7. **One file.** The scenes, each arranged in rows under its own dummy, are merged into one file, side by side;
   materials of the same name become one.

Every size above is a real millimetre, and so is the texture grain (the maps are mapped in world units).

The four Technogym scenes take about 30 minutes (3ds Max works on them side by side; most of it is the search for
surfaces lying on each other and the chamfers), putting them together a few more, and the previews about 30 more.

## Settings
`config\default.json`, each with a short note:
- `parts`: the part materials: their template in the reference scene, and the diffuse colour, glossiness and IOR to
  change (null = the template's);
- `fallback_part`: the part of a mesh whose material is in no map;
- `max.version` (`auto` = the newest 3ds Max) and `max.model_root`;
- `paths`: the inputs, the results folder and the work folder, when they are not the default ones;
- `sandstone`: the length of the import's unit (`import_unit_mm`, 25.4 for inches), one file or one per scene
  (`combine`, true) and the space between the equipment (`gap_mm`, 1000); the maps' size (`map_size`, 4096), the
  folder of the scenes' logo and screen images (`images_dir`), how many scenes run at once, the preview passes, width
  and close-ups; the round parts: `smooth` (on), the hard-edge angle (`smooth_angle`, 30) and the TurboSmooth
  iterations in the viewport and in renders (0 and 1); the rounded edges: `chamfer` (on), the edges it rounds
  (`chamfer_angle`, 40), its size (`chamfer_ratio`, 0.15 of the smallest dimension) and the smallest one made
  (`chamfer_min_mm`, 0.5). Each material's own limits, `chamfer_mm` and `round_mm`, are in
  `corona_materials\sandstone.py`.

Put your own values in `config\project.json` (only the keys you change); it stays on your computer. For one run:
`--set max.version=2025`.

## If something goes wrong
- The terminal shows each step, then the result files or the reason it stopped. The full log is
  `corona_materials.log` in the work folder; each 3ds Max step writes its own log there too (`reference.log`,
  `import.log`, `restructure.log`) and 3ds Max's listener output (`<step>_listener.log`).
- Work folder: `%LOCALAPPDATA%\ing_studio_toolkit\max_corona_materials\<model>`. Deleting it is safe; the next run
  redoes the steps.
- "parts used but not defined": the rules chose a part that `parts` does not have; add it to the settings.
- Texture maps that are missing on this computer are switched off in the part materials (the maps stay in place, to
  be relinked later with the Asset Tracker).
- `sandstone`: its log is `sandstone.log` in `%LOCALAPPDATA%\ing_studio_toolkit\max_corona_materials\sandstone`,
  next to each scene's step logs (`<scene>_refinish.log` ..., `combine.log`). Equipment kept black, or removed by mistake: see
  `sandstone_equipment.csv` and the rules in `sandstone.py`. A material in the wrong finish: `sandstone_materials.csv`
  says which rule chose it; add an `OVERRIDES` line.
- `sandstone`: a logo shows as a plain plate when its image was not found; set `sandstone.images_dir` to its folder.

## Uninstall
Nothing to take away: the tool adds nothing to 3ds Max. `uninstall.bat` says so, and where its cache is. The
toolkit's own `uninstall.bat` removes the toolkit's Python.

## Files
| path | what |
|---|---|
| `corona_materials.bat` | the command |
| `install.bat`, `uninstall.bat` | install (the toolkit's Python, a check of 3ds Max) / uninstall |
| `corona_materials\` | the tool: `cli` (the steps), `parts` (the part map and its rules), `maxbatch` (running a MAXScript in 3ds Max without its window); for Sand Stone `sandstone` (the materials and the rules), `maps` (the texture maps), `sandstone_run` (the steps) |
| `scripts\` | the MAXScripts of the 3ds Max steps: `dump_reference.ms`, `import_model.ms`, `rebuild_parts.ms`; for Sand Stone `survey_scene.ms`, `refinish_sandstone.ms`, `sandstone_materials.ms` (the Corona materials), `clean_scene.ms` (surfaces lying on each other), `smooth_rounds.ms` (smoother round parts), `chamfer_edges.ms` (rounded edges), `arrange_equipment.ms` (the equipment in rows), `combine_sandstone.ms` (the scenes in one file), `material_board.ms`, `preview_sandstone.ms`. They get their paths from `corona_materials.bat` and refuse to run on their own |
| `config\default.json` | the settings |
| `examples\technogym\` | the maps of the Technogym conversion (332 materials → 22 parts) |
| `input\`, `output\` | the files of a double-click run (not in git) |
| `tests\` | `test.bat max_corona_materials` in the toolkit's folder: the part map against the Technogym example, the settings, the Sand Stone rules, real size and maps (`test_sandstone.py`). With `ING_TEST_3DSMAX=1`, also every step in 3ds Max on a small made-up scene, and the Sand Stone clean-up of the meshes and the arrangement in rows (about 7 min) |
