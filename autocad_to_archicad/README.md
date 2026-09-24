# AutoCAD site plan → Archicad site model

Turns an AutoCAD site plan (DWG or DXF) and the survey point cloud of the site into an Archicad 28 file. **These two
files are all it needs.** Where the site is, what each layer holds, the heights and the storeys of the new buildings
are all worked out by code. The project's PDFs are optional: they add the underground levels and check the floor
area.

The file has:

- a **terrain mesh** made from the point cloud,
- the **existing streets**, taken from OpenStreetMap, fitted to the kerbs in the drawing and regraded where new
  streets join them,
- the **new streets** from the drawing, with profiles designed to the Armenian street norms (ՀՀՇՆ 30-01-2023), the
  terrain cut and filled to fit them, **retaining walls** and **bridges** where they are needed,
- the **buildings**: existing ones with heights from OpenStreetMap, new ones with the storeys read from the shadows
  drawn in the plan, and (with the PDF) the **underground levels**,
- the **trees** of the drawing, as Archicad library objects,
- the **drawing itself** on its own layers, over the terrain, as it looks in AutoCAD.

Streets and sidewalks are grey solids lying on the terrain, which is cut and filled under and around them: their
surfaces are continuous and smooth, and the ground meets their edges flush. No street, sidewalk or tree runs into a
building. The point cloud is only used to make the terrain and is not put into the Archicad file. PDFs are read as
data: their text, tables and colours. No AI image recognition is used.

## Quick start
1. **Install once:**
   - AutoCAD 2026 (it reads the DWG, without opening a window) and Archicad 28.
   - Tapir. If the relief tool is installed, you already have it. Otherwise run `dwg2ac.bat addon install` with
     Archicad closed.
   - This tool's Python: `powershell -ExecutionPolicy Bypass -File setup_env.ps1`.
2. **Run** in a terminal:
   ```
   dwg2ac.bat plan.dwg survey.e57
   ```
   Optionally add the project PDF: `dwg2ac.bat plan.dwg survey.e57 --doc areas.pdf`.
3. **Open the results** in `output\`:
   - `plan_FromDWG.pln`: the site model.
   - `plan_FromDWG_report.html`: where the site was found, what each layer holds, the rules applied, the street
     profiles, cut and fill, buildings (including those to be demolished), what the PDF says, the norms to keep in
     mind, and a list of what needs checking.

## What is worked out, and how
| what | how | to fix it by hand |
|---|---|---|
| **where the site is** | The names of the input files, and any texts in the drawing, are looked up on OpenStreetMap's gazetteer. Generic words such as *site, plan, survey, cloud* are ignored. Armenian letters in the layer names limit the search to Armenia. Each candidate place is then checked by matching the drawing's buildings to OpenStreetMap, and only a clear match is accepted. | `--lonlat 44.515,40.192` |
| **the drawing unit** | The unit the DWG states is checked against the size of its shapes (drawings made from an inch template often say inches but are in mm). | `--units mm` |
| **existing buildings** | Among the layers with the most building-like closed shapes (square corners, building size), the one that matches OpenStreetMap's buildings. | `--set layers.existing_buildings=["*BUILDINGS*"]` |
| **new streets** | A hatch layer whose strips have a line layer running along their middle. These are the carriageway and its axis lines. Axes that follow OpenStreetMap streets are existing streets, not new ones. | `layers.carriageway`, `layers.axes` |
| **sidewalks** | The hatch layers that line the carriageway's edges. | `layers.sidewalks` |
| **kerbs of existing streets** | Line layers found on both sides of OpenStreetMap's streets at a street's width. | `layers.kerbs` |
| **new buildings and their shadows** | Architects draw a shadow as the footprint slid in one direction. The layer pair where one layer's outlines, slid along one common direction, explain most of the other layer's shapes gives the buildings and the shadows. | `layers.proposed_buildings`, `layers.shadows` |
| **trees** | Layers made of round symbols (circles, round hatches) of tree size. | `layers.trees` |
| **storeys of the new buildings** | The shadow lengths are whole multiples of one storey's shadow: the largest step that makes every shadow (but at most one) a whole number of storeys, within 15 cm. Half of that step fits too when every building has an even number of storeys, so a shadow of an odd number decides. The drawing alone can't rule out the half step (twice the storeys); with the PDF, its floor area decides. | `--set buildings.shadow_per_storey_m=0.708` |
| **heights of existing buildings** | OpenStreetMap: height, else storeys, else the usual storeys of its building type. | – |
| **the terrain and its altitude** | The point cloud's gaps where buildings stand are matched to the drawing's buildings. The altitude comes from an open world terrain model (±3 to 5 m). | `--set cloud.z_to_altitude=1146.35` |
| **what gets demolished** | An existing building that the new buildings, carriageways or sidewalks cover by a quarter, or by 40 m², is left out and listed. A smaller overlap is a drawing tolerance, and the building is trimmed. | `buildings.demolish_share`, `buildings.demolish_m2` |

Layer names only order the candidates and break ties, so a drawing with unusual layer names still works. The report's
"What the layers hold" table says why each layer was chosen. Patterns such as `["*ROADS*"]` fix a role. Put them on
the command line (`--set`) or keep them in `config\project.json`.

## What you get
The PLN keeps the drawing's plan coordinates, in metres, so an Xref of the DWG lines up with it. Heights are
altitudes. Project zero is a round altitude just below the site, and the report shows which one. The project is
placed on the map (latitude, longitude and UTM survey point).

| layer | content |
|---|---|
| **Site - Terrain** | one mesh: the terrain, cut and filled for the streets. Under the paving it follows the bodies' undersides, with lines along the paving's edges |
| **Site - Roads existing** | the existing streets: dark grey solids (surface *Site - Asphalt*), 10 cm thick, lying on the terrain |
| **Site - Roads proposed** | the new carriageways, dark grey, 10 cm thick, on their designed profile with a 20 ‰ cross fall |
| **Site - Sidewalks proposed** | sidewalks, light grey (*Site - Paving*), 15 cm (kerb height) above the carriageway edge; the body reaches down to the carriageway's underside, so its side is the kerb |
| **Site - Road centre lines** | centre lines of all streets (plan) |
| **Site - Retaining walls** | the walls the new streets need, as 40 cm solid pieces with a footing (*Site - Concrete*); a bridge deck is a 1.2 m slab |
| **Site - Buildings existing** | massing of the existing buildings (Morph solids) |
| **Site - Buildings proposed** | massing of the new buildings, one per outline, with their storeys |
| **Site - Underground levels** | with the PDF: its underground levels (B1, B2 …), one slab per level |
| **Site - Trees** | trees as library objects (*Tree Model Detailed*), sized to the drawn crown |
| **DWG - *layer*** | the drawing: lines, arcs, circles, fills and texts, one layer per AutoCAD layer, same colours. AutoCAD layers that were off stay hidden |

The surfaces are made in the PLN with the colours in `archicad.surfaces`, so they can be changed there or later in
Archicad's attribute manager.

**How the streets sit in the terrain.** Each street surface is one continuous height function: a point takes the
height of the centre line nearest to it, interpolated along that line, minus the cross fall. The centre lines'
corners are rounded, surfaces of streets that meet are blended over 1 m, and each surface is smoothed over 1 m, so
there are no steps at stations, bends or junctions. Streets side by side on clearly different levels (a slip road
beside a highway) keep a step between them. The terrain runs `pavement_m` (10 cm) below a carriageway and kerb +
10 cm below a sidewalk, so it passes under the kerb without a step. The street bodies are exactly that thick and lie
on it, without overlapping it. The mesh has a point at every corner of the grid the bodies are triangulated on, and
a line just inside each paved piece's edge at its underside. A second line 20 cm outside the paving lifts the ground
flush with its top.

## How it works
`dwg2ac.bat stages` lists the steps. Finished steps are reused on the next run.

1. **read**: AutoCAD's console turns AutoCAD Architecture objects into plain AutoCAD objects and saves a DXF.
   - Blocks are exploded.
   - Old Armenian font text (ARMSCII-8) becomes real Armenian letters.
   - The drawing unit is checked (see above).
2. **inventory**: finds the site plan among the drawings in model space. Sections, details and legends are left out.
3. **documents** (only with `--doc`): reads the project PDFs:
   - the sheets' texts, such as `B1 B2 21900 SQM`, and tables, such as area by function, with their legend colours;
   - the drawing scale, from a `1 : N` text or, if there is none, from the sheets' own stated areas against the
     areas they outline;
   - the areas outlined in red on the level plans, measured on the centre of the outline and placed on the drawing
     by matching the page's lines to the drawing's lines.
4. **georef**: finds where the site is and matches the drawing's building outlines to OpenStreetMap buildings, which
   places the drawing on the map. It tries every rotation and position.
5. **layers**: works out what each layer holds (see above).
6. **terrain**: the relief tool builds the point cloud's bare-earth terrain. Its building gaps are matched to the
   drawing's buildings, and its heights are turned into altitudes.
7. **buildings**:
   - **Existing buildings**: the drawing's outlines, with heights from OpenStreetMap. The ones where the new
     development goes are listed as demolished.
   - **New buildings**: storeys from the drawn shadows. With the PDF, its floor area checks the result.
   - **Underground levels** (with the PDF): stacked down from the ground floor.
   - **Trees**: from the tree symbols.
   - The gaps between the new buildings are checked.
8. **roads**:
   - **Existing streets** come from OpenStreetMap, only those on the ground: tunnels, covered passages and bridges
     are left out. They are moved and widened to the drawing's kerb lines, and their profile follows the smoothed
     ground.
   - **New streets** come from the drawing: the carriageway, the axis lines and the sidewalks. Their profile is
     designed for the whole network at once, following the rules below and staying as close to the ground as
     possible. Where two streets share one carriageway (a fork, a junction, the legs of a hairpin), the slope across
     it between them is kept within the grade limit too.
   - Every street surface stops at the buildings.
   - Where a new street can't join an existing one at its height within the rules, the existing street is regraded
     locally, at 4 % at most.
   - Junction kerb radii, dead ends, sidewalk widths, wheelchair grades and the new buildings' fire access (a street
     within 25 m) are checked.
9. **earthworks**: builds the street surfaces (see "How the streets sit in the terrain" above), sets them into the
   terrain and adds side slopes of 1:1.5 from their edges until they meet the ground.
   - Beside existing streets the ground is only eased onto their edge, within 3 m. That regrading is reported apart
     from the cut and fill.
   - The ground under the buildings stays as it is. Slopes stop at their walls.
   - A street that would stand more than 8 m above the ground is a bridge or viaduct: the ground stays as it is under
     it.
   - Retaining walls are found where the slopes can't meet the ground, and cut into pieces for Archicad.
   - Cut and fill are computed.
10. **archicad**: writes the PLN, then checks and saves it. It opens its own Archicad and never touches another open
    project.
11. **report**: writes the HTML report.

## Street rules
The new streets follow **ՀՀՇՆ 30-01-2023** (Armenia, in force since 30 May 2023). It replaced ՀՀՇՆ 30-01-2014 and the
Soviet SNiP 2.07.01-89. The street class (`--street-class`) and the terrain give the design speed (Table 29). The
terrain's type is a setting, or `auto`, which reads it from the ground slope under the new streets (this is the
tool's rule of thumb).

| class | design speed: normal / rugged / mountainous | lane | lanes | sidewalk |
|---|---|---|---|---|
| `city_main` | 80 / 70 / 60 km/h | 3.6 m | 4+ | 4.5 m |
| `district` | 60 / 50 / 50 km/h | 3.3 m | 2+ | 2.25 m |
| `local` (default) | 40 / 40 / 30 km/h | 3.0 m | 2+ | 1.5 m |
| `driveway` | 40 km/h | 3.0 m | 2 | 1.0 m |
| `driveway_secondary` | 30 km/h | 4.5 m | 1 | 0.75 m |

The design speed sets the geometry:

| speed | min radius | max grade | vertical curves (crest / sag) | source |
|---|---|---|---|---|
| 30 km/h | 30 m | 90 ‰ (120 ‰ on up to 150 m) | 570 / 180 m | ՀՀՇՆ 30-01-2023 |
| 40 km/h | 60 m | 90 ‰ | 1000 / 1000 m | SNiP 2.05.02-85 table (continued by ՀՀՇՆ 32-01-2022) |
| 50 km/h | 100 m | 80 ‰ | 1500 / 1200 m | 〃 |
| 60 km/h | 150 m | 70 ‰ | 2500 / 1500 m | 〃 |

The values for 40–60 km/h are the ones ՀՀՇՆ 32-01-2022 builds on. Confirm them against its text.

These apply to every class:
- **Serpentine bends** (radius under 30 m): at most 40 ‰, radius at least 15 m.
- **The exceptional grade** (120 ‰ at 30 km/h) is used only where it saves real earthworks. Longer stretches than
  allowed are reported.
- **Drainage:** at least 4 ‰. This is checked and reported, not enforced.
- **Cross fall and kerb:** 20 ‰ cross fall, 15 cm kerb.
- **Checks, reported:** kerb radius at junctions at least 12 m (6 m where constrained), a 15 m turning place at dead
  ends, sidewalks at least the class width, wheelchair routes at most 1:12 (83 ‰), gaps between new buildings
  (10 m, and 6 m fire distance), and a street within 25 m of every new building of 3 or more storeys.
- **Joining existing streets:** a new street end is pulled to the existing street's height. If the rules don't allow
  that, the existing street is regraded locally and the report says where.
- **Streets sharing a carriageway:** across the paving between two streets (a fork, the legs of a hairpin) no slope
  is steeper than the grade limit. Where even that can't be met, the step (a wall) is reported.

The report also lists the other norms and laws that apply: fire, seismic, accessibility, parking, density, noise,
monuments and the Law on Urban Development. It says for each what the model checks and what is left to the
designers. With the PDF, it computes the programme's **parking demand** (ՀՀՇՆ 30-01-2023 Table 56) and its
**density** (Table 8).

## Common changes
Add these after the file names, for example `dwg2ac.bat plan.dwg survey.e57 --street-class district`.

| I want… | add |
|---|---|
| to give the site's position (when the names don't lead to it) | `--lonlat 44.515,40.192` |
| to read a project PDF | `--doc areas.pdf` (repeat for more) |
| another street class | `--street-class district` |
| the terrain's type fixed | `--set roads.terrain=rugged` |
| a layer role fixed | `--set layers.shadows=["*OMBRE*"]` (any role of the table above) |
| a fixed shadow per storey | `--set buildings.shadow_per_storey_m=0.708` |
| other storey heights | `--set buildings.storey_m=3.2 --set buildings.ground_storey_m=4.2` |
| other colours | `--set archicad.surfaces.roads.rgb=[0.25,0.25,0.27]` |
| other trees | `--set archicad.tree_objects=["Deciduous Trees"]` |
| steeper serpentine bends | `--set roads.profile.serpentine_max_grade_permille=60` |
| never the exceptional grade | `--set roads.profile.exceptional_grade_cost=null` |
| embankments instead of bridges | `--set roads.earthworks.max_fill_m=null` |
| gentler side slopes | `--set roads.earthworks.fill_slope_h_per_v=2 --set roads.earthworks.cut_slope_h_per_v=2` |
| existing streets never regraded | `--set roads.existing.regrade_grade_permille=null` |
| exact altitudes, from a surveyed point | `--set cloud.z_to_altitude=1146.35` (metres added to the point cloud heights) |
| no 2D copy of the drawing | `--no-2d` |
| another part of the drawing | `--set drawing.region=[x1,y1,x2,y2]` (drawing units) |
| the results somewhere else | `--out D:\results` |
| to redo a step | `--only roads --force` (or `--from roads`) |
| to start afresh (delete results and cache) | `dwg2ac.bat clean plan.dwg` |
| thicker paving | `--set roads.profile.pavement_m=0.2` |

To keep values for a project, write only those keys into `config\project.json`, in the layout of
`config\default.json`. All settings, each with a short note, are in `config\default.json`.

## Commands
| command | what it does |
|---|---|
| `dwg2ac.bat DRAWING POINT_CLOUD [options]` | builds the site model (the same as `dwg2ac.bat run ...`) |
| `dwg2ac.bat clean DRAWING [--out DIR]` | deletes that drawing's results and cached steps, so the next run starts afresh |
| `dwg2ac.bat stages` | lists the steps |
| `dwg2ac.bat config [options]` | prints the settings a run would use |
| `dwg2ac.bat addon install\|remove\|status` | installs, removes or checks Tapir (shared with the relief tool) |

`dwg2ac.bat --help` and `dwg2ac.bat run --help` show every option.

## If something goes wrong
- The terminal shows each step, then the result files or the reason it failed. `WARN` lines are worth reading. The
  full log is in `pipeline.log`, and its path is printed at the start and end of every run.
- **"could not work out where the site is"** or **"no clear match between the drawing and OpenStreetMap":** give
  the position with `--lonlat`, and check the drawing unit (`--units mm`). Or place the drawing by hand:
  `georef.mode=manual` with `georef.manual_origin_utm`.
- **A layer was read wrongly:** see "What the layers hold" in the report, and fix that role with
  `--set layers.<role>=[...]`.
- **The point cloud could not be placed:** use `cloud.mode=manual` with `cloud.manual_origin_dwg_m`.
- **A PDF plan could not be placed on the drawing:** the page doesn't share enough lines with the drawing. Its
  numbers are still read.
- **An element Archicad refused:** these are listed in `archicad_refused.json` in the cache folder. There are usually
  only a handful, and they are also counted in the report.
- Intermediate files are kept in `%LOCALAPPDATA%\ing_studio_toolkit\autocad_to_archicad`. Deleting them is safe:
  `dwg2ac.bat clean plan.dwg` removes a drawing's cache and its results (close the PLN in Archicad first).

## Known limits
- The placement needs building outlines in the drawing and OpenStreetMap buildings around the site. Finding the site
  from names needs a place name in the file names or the drawing's texts; otherwise give `--lonlat`.
- New streets are found only where the drawing has hatched carriageways (with axis lines, or on a layer named like a
  street layer).
- Automatic altitudes come from an open world terrain model (±3 to 5 m). For exact altitudes, give a surveyed height.
- Existing buildings that OpenStreetMap has no height for get an assumed one, and the report counts them.
- New buildings without a drawn shadow are shown 1 storey high and listed.
- Buildings and walls are massing (Morph solids), not Archicad walls or slabs.
- Bridges are shown as the street deck above the ground. Piers are not modelled.
- Existing streets side by side on different levels meet with a step inside the street body, not a modelled wall.
- Paved areas with no street axis through them (ramps, parking) stay on the existing ground.
- PDFs are read with PyMuPDF (AGPL licence, fine for in-house use).

Street and building data © OpenStreetMap contributors (ODbL). Place names from OpenStreetMap's Nominatim.
