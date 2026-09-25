# AutoCAD site plan → Archicad site model

Turns an AutoCAD site plan (DWG or DXF) and the survey point cloud of the site into an Archicad file (29, or 28). **These two
files are all it needs.** Where the site is, what each layer holds, the heights and the storeys of the new buildings
are all worked out by code. The project's PDFs are optional: they add the underground levels and check the floor
area.

The file has:

- a **terrain mesh** made from the point cloud, showing its **contour lines** (1 m) in 3D, with the same contours in
  colour on the plan,
- the **existing streets**, taken from OpenStreetMap and joined into one network, fitted to the kerbs in the
  drawing and regraded where new streets join them,
- the **new streets** from the drawing, with profiles designed to the Armenian street norms (ՀՀՇՆ 30-01-2023), the
  terrain cut and filled to fit them, **retaining walls** and **bridges** where they are needed,
- the **buildings**: existing ones with heights from OpenStreetMap, new ones with the storeys read from the shadows
  drawn in the plan, and (with the PDF) the **underground levels**,
- the **trees** of the drawing, as Archicad library objects,
- the **surroundings**: the OpenStreetMap buildings around the site, on a terrain from the open world terrain model
  that meets the survey terrain at its edge,
- optionally, the team's own **models of neighbouring buildings**, **hotlinked** where they stand (see "Hotlinked
  models" below),
- the **drawing itself** on its own layers, over the terrain, as it looks in AutoCAD.

Streets and sidewalks are grey solids lying on the terrain, which is cut and filled under and around them. The paving
is one connected network: new streets run into the existing ones, junctions have rounded kerbs, and the junction
aprons, the roundabout and the driveways to the buildings are paved too. The surfaces are continuous and smooth, and
the ground meets their edges flush. No street, sidewalk or tree runs into a
building. The point cloud is only used to make the terrain and is not put into the Archicad file. PDFs are read as
data: their text, tables and colours. No AI image recognition is used.

## Quick start
1. **Install once:**
   - AutoCAD 2026 (it reads the DWG, without opening a window) and Archicad 29 or 28. The file is written in the
     newest one installed (`archicad.version`); hotlinked models must not be newer than it.
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
| **Site - Terrain** | one mesh: the terrain, cut and filled for the streets. Under the paving it follows the bodies' undersides, with lines along the paving's edges. Its contour lines (every 1 m) are level lines of the mesh, and the 3D shows the mesh's own lines only (ridges *User defined*): the contours, the ground along the paving, the buildings and the walls |
| **Site - Roads existing** | the existing streets: dark grey solids (surface *Site - Asphalt*), 10 cm thick, lying on the terrain |
| **Site - Roads proposed** | the new carriageways, dark grey, 10 cm thick, on their designed profile with a 20 ‰ cross fall, with their junction aprons and the driveways to the buildings |
| **Site - Sidewalks proposed** | sidewalks, light grey (*Site - Paving*), 15 cm (kerb height) above the carriageway edge; the body reaches down to the carriageway's underside, so its side is the kerb |
| **Site - Road centre lines** | centre lines of all streets (plan) |
| **Site - Retaining walls** | the walls the new streets need, as 40 cm solid pieces with a footing (*Site - Concrete*); a bridge deck is a 1.2 m slab |
| **Site - Buildings existing** | massing of the existing buildings (Morph solids) |
| **Site - Buildings proposed** | massing of the new buildings, one per outline, with their storeys |
| **Site - Underground levels** | with the PDF: its underground levels (B1, B2 …), one slab per level |
| **Site - Trees** | trees as library objects (*Tree Model Detailed*), sized to the drawn crown |
| **Site - Walls existing** | walls drawn on the building layers (outlines thinner than 1.5 m, such as terrace parapets), in 3 m pieces that follow the ground, 1 m above its higher side (*Site - Stone*) |
| **Site - Context terrain** | a second mesh around the survey terrain (250 m, 10 m grid, open world terrain model), fitted to it along its edge; the survey terrain is its hole |
| **Site - Context buildings** | the OpenStreetMap buildings (and building parts) on it, with OSM heights or the usual storeys of their type |
| **Site - Contours** | the contour lines of the finished terrain on the plan, their colour cycling every metre over 5 colours (the survey's colour contour drawing) |
| **Site - Hotlinked models** | the models in `archicad.hotlinks` (see "Hotlinked models") as hotlinked modules, which follow their files. The drawing's buildings and walls, OpenStreetMap's buildings and the trees inside them are left out |
| **DWG - *layer*** | the drawing: lines, arcs, circles, fills and texts, one layer per AutoCAD layer, same colours. AutoCAD layers that were off stay hidden |

The surfaces are made in the PLN with the colours in `archicad.surfaces`, so they can be changed there or later in
Archicad's attribute manager.

**How the streets sit in the terrain.** All carriageways, existing and new, share one surface. A point takes the
heights of the centre lines near it, each interpolated along its line and crowned by the cross fall, weighted by the
point's distance beyond each street's edge. On a street its own surface counts, streets meeting at a junction blend,
and paving between two streets slopes evenly from one edge to the other. The centre lines' corners are rounded and
the surface is smoothed over 1 m, so there are no steps at stations, bends or junctions. Along its axes a new street
keeps its designed surface, whatever runs beside it. Where two streets side by side lie on levels the paving between
them can't join (steeper than 20 %, like a slip road beside a highway), that strip is ground, sloped or walled like
the ground beside any paving. Paving beyond a street's edge (aprons, lay-bys) leaves the edge at the street's height
and follows the ground within 10 %. A driveway that reaches a building runs toward its ground floor. A sidewalk is a
kerb above the carriageway beside it. The terrain runs `pavement_m` (10 cm) below a carriageway and kerb + 10 cm below
a sidewalk, so it passes under the kerb without a step. The street bodies are exactly that thick and lie
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
     are left out. OpenStreetMap splits a street into many pieces; they are joined back into whole streets. Each is
     moved and widened to the drawing's kerb lines. At junctions the streets meet on one point and at one height,
     with round ends and rounded kerb corners (6 m).
   - **The profile of an existing street** stays as close to the ground as a real street can: no steeper than its
     OpenStreetMap class allows (main roads 100–120 ‰, lanes 200 ‰) and with vertical curves of at least 300 m. It
     keeps to the least *absolute* difference from the ground, so a short stretch of wrong ground does not pull it
     up or down. The ground a street stands on is read across its carriageway, from the most level band within half
     a carriageway of its centre line: an OpenStreetMap line a few metres off lies partly on the slope beside the
     street. Ground that is not level across (a slope, a wall) counts less. Under an OpenStreetMap bridge the survey
     sees the deck, not the street, so that ground does not count and the street runs on below it. Stretches where the
     ground stays more than 1.5 m off the street are listed in the report.
   - **New streets** come from the drawing: the carriageway, the axis lines and the sidewalks. An axis line counts
     only where it runs inside the carriageway, at least 1.5 m from its edge. Axis lines drawn along existing streets
     or along the carriageway's edge (lane lines) are not new streets, and an axis drawn twice counts once. Their
     profile is designed for the whole network at once, following the rules below and staying as close to the ground
     as possible. Where two streets share one carriageway (a fork, a junction, the legs of a hairpin), the slope across
     it between them is kept within the grade limit too.
   - Every street surface stops at the buildings.
   - Where a new street can't join an existing one at its height within the rules, the existing street is regraded
     locally, at 4 % at most.
   - Junction kerb radii, dead ends, sidewalk widths, wheelchair grades and the new buildings' fire access (a street
     within 25 m) are checked.
9. **earthworks**: decides which paving is built in 3D, builds the street surfaces (see "How the streets sit in the
   terrain" above), sets them into the terrain and adds side slopes of 1:1.5 from their edges until they meet the
   ground.
   - Paving, in this order:
     - the drawing's carriageway along a new street's axis is new carriageway;
     - an existing street stays one where the drawing's carriageway only covers it;
     - the drawing's carriageway that joins a street within 25 m of its edge is paving too (junction aprons, the
       roundabout, lay-bys), where joining the street takes no more than 1 m of cut or fill;
     - a piece of it that reaches a building (up to 600 m²) is that building's access and is always built;
     - the drawing's sidewalks count along the streets;
     - gaps narrower than 6 m between paved pieces (medians, strips between a new and an old street) are paved too:
       existing street beside existing streets, else new carriageway (if it fits the ground like an apron).

     What remains (a plaza on a slope, a parking lot joining no street, the verge beside a highway) stays in 2D.
   - Beside existing streets the ground is only eased onto their edge, within 3 m. That regrading is reported apart
     from the cut and fill.
   - The ground under the buildings stays as it is. Slopes stop at their walls.
   - A street that would stand more than 8 m above the ground is a bridge or viaduct: the ground stays as it is under
     it.
   - Retaining walls are found where the slopes can't meet the ground, where they run into an existing street, at
     bridge abutments and between streets side by side on different levels. They are cut into pieces for Archicad.
   - Cut and fill are computed.
10. **context**: the OpenStreetMap buildings around the site (Overpass: buildings, multipolygons and building
    parts) and their ground from the open world terrain tiles. That ground differs from the survey terrain by a few metres;
    the difference along the survey terrain's edge is carried over into it, so the two meet without a step.
    `--set context.enabled=false` leaves the surroundings out.
11. **archicad**: writes the PLN, then checks and saves it. It opens its own Archicad and never touches another open
    project.
    - The hotlinked models go in first. Their plan outline (their walls, slabs, roofs and solids) decides which of the
      drawing's and OpenStreetMap's stand-ins are left out.
    - The contour lines come from the finished terrain, eased over 1 m, and are cut clear of the paving, the buildings
      and the retaining walls. Where the contour mesh would leave flat triangles (valleys, ridges, tops) more than
      30 cm off the terrain, points are added until it fits.
    - The output folder holds only the PLN and the report. A PLN that is rebuilt from the template keeps its previous
      version in the cache folder (`previous.pln`), as does Archicad's own backup of a save (`previous.bpn`).
12. **report**: writes the HTML report.

## Hotlinked models
Models the team already has of buildings next to the site (a landmark, a neighbouring project) can be placed in the
PLN as **hotlinked modules**. They stay live links to their files, and where one stands the drawing's buildings and
walls, OpenStreetMap's buildings and the trees are left out, so nothing is doubled. They are set per project in
`config\project.json` (not in `default.json`, and not in git):

```json
{"archicad": {"hotlinks": [
  {"name": "Museum", "file": "\\\\server\\projects\\museum\\museum.pln",
   "x": 1818.6, "y": 1053.4, "altitude": 1007.3, "rotation_deg": 0.16, "stories": [0, 0]}
]}}
```

| key | meaning |
|---|---|
| `x`, `y` | where the model's origin (its 0,0) lands, in the drawing's coordinates in metres |
| `altitude` | the altitude (m above sea level) of the model's zero level |
| `rotation_deg` | the model's turn, counter-clockwise |
| `stories` | the model's lowest and highest story index. The PLN gets those stories, because Archicad leaves out whatever is on a story the host lacks |

To find the numbers, place the model once in any PLN that already has the site (for example, a colleague's
coordination file): its hotlink's origin, rotation and elevation there give them. The model must not be saved in a
newer Archicad than the PLN (`archicad.version`). A model that can't be reached, or can't be linked, is left out
with a warning.

Archicad's API cannot delete a hotlink. A rerun therefore moves the existing one into place instead of adding a
second one. A model taken out of the list must be deleted in Archicad by hand; the run warns about it.

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
| steeper existing lanes allowed (a very hilly town) | `--set roads.existing.max_grade_permille.default=250` |
| exact altitudes, from a surveyed point | `--set cloud.z_to_altitude=1146.35` (metres added to the point cloud heights) |
| no 2D copy of the drawing | `--no-2d` |
| another part of the drawing | `--set drawing.region=[x1,y1,x2,y2]` (drawing units) |
| the results somewhere else | `--out D:\results` |
| to redo a step | `--only roads --force` (or `--from roads`) |
| to start afresh (delete results and cache) | `dwg2ac.bat clean plan.dwg` |
| thicker paving | `--set roads.profile.pavement_m=0.2` |
| less of the drawing's paving built in 3D | `--set roads.profile.paving_reach_m=12 --set roads.profile.paving_max_cut_fill_m=0.5` |
| sharper kerb corners at existing junctions | `--set roads.existing.kerb_return_m=3` |
| narrow gaps between paved pieces left open | `--set roads.profile.close_gaps_m=0` |

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
- OpenStreetMap bridges and flyovers are left out, so a street that continues onto one ends there. A street passing
  under one keeps its own level, and the survey's deck is cut away over the street's width.
- An existing street whose OpenStreetMap line lies well off the real street (more than half a carriageway) and has
  no kerbs in the drawing to correct it may still sit off its real level; the report lists those stretches.
- The drawing's paving that joins no street, lies farther than 25 m from one, or would need more than 1 m of cut or
  fill (a plaza on a slope, a verge on an embankment) stays in 2D on the existing ground.
- PDFs are read with PyMuPDF (AGPL licence, fine for in-house use).

Street and building data © OpenStreetMap contributors (ODbL). Place names from OpenStreetMap's Nominatim.
