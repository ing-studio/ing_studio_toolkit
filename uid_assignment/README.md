# uid_assignment — window types and IDs

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

After that, the combinations are yours to change.

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

## Install (once per computer)
1. In the `uid_assignment` folder, double-click **`addon\install.bat`**, or from PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File addon\install.ps1
   ```
   Either one:
   - adds **Tapir** (the free add-on the tool talks to Archicad through) to Archicad 28 and 29, if it isn't there yet;
   - puts the **Window IDs** button into the Tapir palette.
2. If Tapir was just added, restart Archicad.
3. In Archicad open **Window › Palettes › Tapir**. If the button is missing, click **Reload scripts**.

Only Python 3.10+ is needed (no packages). Tapir runs the button with its own `uv` and offers to install `uv` the
first time. To take the button away: `addon\install.bat remove` or `addon\install.ps1 -Remove` (Tapir stays; other
tools use it).

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
instead of the copy, the tool stops and says so. The log is `%TEMP%\uid_assignment.log`.

### From a terminal
| command | does |
|---|---|
| `uid.bat` | *In this project*, in the only open solo project (`--port N` picks the Archicad) |
| `uid.bat --dry-run` | shows what would change; changes nothing |
| `uid.bat --renumber` | numbers every type afresh from Պ-01 |
| `uid.bat --no-sheet` | IDs and ID labels only, no worksheet |
| `uid.bat --output --project X.pln` | *Output files* of `X.pln` (`--out folder`, `--archicad 28`, `--helper-port N` to use an Archicad that is already open) |
| `uid.bat addon install` / `addon remove` | what `addon\install.bat` does |
| `uid.bat --help` | all options |

Windows inside hotlinked modules are numbered in the module's own file. Teamwork projects are not supported: use a
solo copy.

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

## Files
| path | what |
|---|---|
| `addon\install.bat`, `addon\install.ps1` | the installers |
| `addon\palette\Window IDs.py` | the palette button (it only calls the tool) |
| `uid.bat` | the terminal entry |
| `uids\` | the tool: `windows` (reading), `types` (numbering), `ids` (writing), `layers` (its two layers), `plans` (ID labels, plan PDF pages), `sheet` (the worksheet), `annotate` (both layers), `export` (output files), `session` (the helper Archicad), `report`, `pdf`, `addon` (install), `cli` |
| `config\default.json` | the settings |
| `tests\` | `python -m unittest discover tests`: the numbering rules, the sheet layout (alignment, no overlaps, table widths) and the layers and layer combinations, without Archicad |
| `test_data\` (not in git) | `Hasratyan_plans.pln`: a cut-down copy of Հասրաթյան 34-5 (2 stories, 24 windows, no IDs), the one test project; `output\` holds the 4 files the tool made from it |
