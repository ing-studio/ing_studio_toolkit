# Archicad windows → window IDs and types

An Archicad add-on (a button in the Tapir palette) that finds every window of the project, groups them into types,
and gives each type an ID: **Պ-01, Պ-02, …** (Պ for պատուհան). It writes the ID into every window. It then adds
two layers of its own, named in English so they are easy to find in the Layer Settings:

| layer | what is on it |
|---|---|
| **Window IDs - Floor Plans** | an ID label on every window, on its story |
| **Window Types - Measurements** | the worksheet **«Պ Պատուհանների տեսքեր»**: every type's front view with its width and height as real Archicad dimensions, its sills, count and opening, and the table «Պատուհանների մասնագիր» (ID, sizes, count per story, total) |

**The ID labels** are Archicad's associative labels, the usual way to mark windows in a drawing set. Each label
belongs to its window and shows the window's own Element ID, so it moves with the window and changes when the ID
changes. A label sits just outside the wall, in a rounded frame, with a leader to a dot on the window. It reads
level even on a plan turned with *Set Orientation*.

**The worksheet** follows the usual rules of a window schedule (the ГОСТ 21.501 window schemes, ISO 129
dimensions):
- the views of a row stand on one line, with their marks (Պ-01 …) on one line above them;
- each view has its overall width below it and its height on its left, 8 mm off the outline;
- the sills, quantity and opening (sliding, fixed …) are centred under each view, on lines the whole row shares;
- every view has room for its dimensions and text, so nothing overlaps, and the rows are spread to one width;
- text heights are the standard 5 mm and 2.5 mm, and the texts are always level;
- the table's columns are as wide as their text, the story columns share the heading «Քանակ ըստ հարկերի», and
  the units are in the headings.

Archicad reports how wide each text really came out, and the tool warns if one is wider than its space (for
example, with a very wide font in the Text tool).

**Layer combinations:** Archicad adds a new layer to every layer combination as *hidden*, so a View Map view would
not show it. When the tool first makes its layers, it therefore shows:
- the measurements layer in every combination (it only holds the worksheet, so no plan changes);
- the IDs layer only in the combinations meant for window marks (the ones whose name contains «պատուհան» or
  "window", like «Դռների և պատուհանների մակնիշավորում») that also show the windows: not on the heating or
  lighting plans, and never as marks without their windows;
- and it makes the combination **Window IDs - Floor Plans**: the layers as they were, with the windows and their
  labels shown.

It also adds the View Map folder **Window IDs - Floor Plans**, with a view of every story that has windows (for example
«0. Ground Floor - Window IDs»). These views use that combination, so they show the IDs; place them on your layouts.
Your own views, like «0. Ground Floor», keep their own combination. That combination usually hides the IDs layer, so
to see the IDs there too, tick the layer in it or switch the view to **Window IDs - Floor Plans**.

After that, the combinations and views are yours to change. They are made only once, so a later run leaves them as
they are.

How windows are typed and numbered:
- **Type** = same library part + same width × height (to the mm) + same panes, transom, glazing bars and frame.
  The sill height is where a window sits, not what it is, so windows at different sills are one type. The
  worksheet and the table list the sills.
- **Opening side:** the same window opening to the other side shares the number with a prime, like the doors'
  Դ-01 / Դ-01'. Example: 3 × Պ-13 (L) and 1 × Պ-13' (R).
- **Numbers stay put:** a type whose windows already have Պ-04 keeps it on every later run, so drawings that already
  cite a number stay right. New types take the lowest free numbers, so the list has no holes.
- Only elements made with the **Window tool** are counted. Openings, and objects drawn to look like windows, are
  not; for a project without real windows, the tool says what it has instead.

## Install
Once per computer:
1. Close Archicad and double-click **`install.bat`** in the `archicad_window_ids` folder. It:
   - sets up the toolkit's Python, if it isn't there yet;
   - adds **Tapir** (the free add-on the tool talks to Archicad through) to Archicad 28 and 29, if it isn't there yet;
   - puts the **Window IDs** button into the Tapir palette.
2. In Archicad open **Window › Palettes › Tapir**. If the button is missing, click **Reload scripts**.

Tapir runs the button with its own `uv` and offers to install `uv` the first time. Run `install.bat` again after
moving the toolkit folder.

## Use
Open the project (a solo `.pln`) and click **Window IDs** in the Tapir palette. Choose one of two ways:

### In this project
Works in the open project. **Nothing is saved**: check the result, then save (or undo).
- The Պ IDs go into each window's **Element ID**.
- The two layers above are added and filled in (with the layer combinations, the first time).
- A report is written next to the project: `output\<project>_windows.html` (types with a 3D preview, the sheet, every
  changed ID) and `output\<project>_windows.csv` for Excel.

Run it again after changing windows: the IDs are brought up to date, and what is on the two layers is redrawn. It is
replaced, never duplicated. If you hid or locked the two layers, they stay that way. Windows on a hidden layer get
their IDs and labels too: the layer is shown for that moment and hidden again. Windows on a **locked** layer, or
locked themselves, keep their old ID and get no label; the tool names the layer, so you can unlock it and run
again.

### Output files
Leaves the open project as it is. The **saved** file is copied (save first), and 4 files are written to the `output`
folder next to it:

| file | what is in it |
|---|---|
| `<project>_window_ids.pln` | the project with the Պ IDs in its windows, the ID labels on its floor plans (layer **Window IDs - Floor Plans**, combination of the same name), and the worksheet (layer **Window Types - Measurements**) |
| `<project>_window_ids.pdf` | one A3 page per story with windows: walls, doors, columns, each window tagged with its ID |
| `<project>_window_types.pln` | only the window types: the worksheet on **Window Types - Measurements**. Every other element and layer is removed. |
| `<project>_window_types.pdf` | that sheet, printed at 1:50 |

A second Archicad of the same version opens and does the work in its own window. It stays open with the types file,
and the next click uses it again (that is quicker). Here windows on locked layers get their IDs too: in the copy every
window layer is opened for the work and put back after. Archicad's "Missing Add-Ons" note is confirmed with OK; any
other dialog stops the tool and is left for you to read. So does **Archicad Project Recovery** (unsaved work kept
after a crash): decide there what to do with it, then run again. If the new Archicad opens a recovered project
instead of the copy, the tool stops and says so. The log is `%TEMP%\archicad_window_ids.log`.

### From a terminal
| command | does |
|---|---|
| `window_ids.bat` | *In this project*, in the only open solo project (`--port N` picks the Archicad) |
| `window_ids.bat --dry-run` | shows what would change; changes nothing |
| `window_ids.bat --renumber` | numbers every type afresh from Պ-01 |
| `window_ids.bat --no-sheet` | IDs and ID labels only, no worksheet |
| `window_ids.bat --output --project X.pln` | *Output files* of `X.pln` (`--out folder`, `--archicad 28`, `--helper-port N` to use an Archicad that is already open) |
| `window_ids.bat addon install` / `addon remove` / `addon status` | what `install.bat` / `uninstall.bat` do, and a check |
| `window_ids.bat --help` | all options |

Windows inside hotlinked modules are numbered in the module's own file. Teamwork projects are not supported: use a
solo copy.

## Input
The project **open in Archicad** (a solo `.pln`); for *Output files*, its **saved** file. Only elements made with
the Window tool are counted. `input\` holds test projects for trying the tool from a terminal on a copy (see
`input\README.md`).

## Output
- *In this project*: the IDs, the two layers and their contents in the open project (not saved), and the report
  `output\<project>_windows.html` / `.csv` next to the project.
- *Output files*: the 4 files of the table above, in `output\` next to the project (or `--out`).

## The Interactive Schedule (once per template)
Archicad's API cannot create a schedule, so set this one up once (best in the office template). It then updates by
itself. **Document › Schedules and Lists › Schedules › Scheme Settings › New…**, name it `Պատուհանների մասնագիր`:
- Criteria: *Element Type* **is** *Window*.
- Fields: *Element ID*, *Front view* (the 2D preview with dimensions), *Width*, *Height*, *Sill Height*,
  *Home Story* (optional), and *Quantity*.
- Tick **Merge uniform items**. Sort by *Element ID*.

Field names differ a little between Archicad versions. Once the schedule exists, the tool stops warning about it.

## Settings
`config\default.json` holds:
- the ID letter, digits and prime mark;
- the order of new numbers (`floor`, `size` or `count`);
- which GDL parameters make a type;
- the names of the two layers, and in which layer combinations each is shown when it is made;
- the worksheet's name, scale (1:50) and pens.

Put your own values in `config\project.json`, which overrides the defaults and stays out of git.

## If something goes wrong
- The tool says what it did, and why it stopped, in its message; the full log is `%TEMP%\archicad_window_ids.log`.
- A window kept its old ID and has no label: it, or its layer, is **locked**. The tool names the layer; unlock it and
  run again (*Output files* opens locked window layers in its copy by itself).
- *Output files* stopped at a dialog of the helper Archicad, or at **Archicad Project Recovery**: decide there, then
  run again.
- The warning about the Interactive Schedule stays until the schedule is set up once (see above).
- The button says the tool is not found: the toolkit folder has moved. Run `install.bat` again.

## Uninstall
Double-click **`uninstall.bat`**: it takes the **Window IDs** button out of the Tapir palette. Tapir and the
toolkit's Python stay for the other tools; the toolkit's own `uninstall.bat` removes everything.

## Files
| path | what |
|---|---|
| `window_ids.bat` | the command |
| `install.bat`, `uninstall.bat` | install / uninstall (the toolkit's Python, Tapir, the palette button) |
| `addon\Window IDs.py` | the palette button (it only calls the tool) |
| `window_ids\` | the tool: `windows` (reading), `types` (numbering), `ids` (writing), `layers` (its two layers), `plans` (ID labels, plan PDF pages), `sheet` (the worksheet), `annotate` (both layers), `export` (output files), `session` (the helper Archicad), `archicad` (its Archicad client: the standard library only, so the button runs it in Tapir's own Python), `report`, `pdf`, `cli`. Installing uses the toolkit's library (`core\ing_core`) |
| `config\default.json` | the settings |
| `input\` (not in git) | `Hasratyan_plans.pln`: a cut-down copy of Հասրաթյան 34-5 (2 stories, 24 windows, no IDs), the one test project |
| `output\` (not in git) | the 4 files the tool made from it |
| `tests\` | `test.bat archicad_window_ids` in the toolkit's folder: the numbering rules, the sheet layout (alignment, no overlaps, table widths) and the layers and layer combinations, without Archicad |
