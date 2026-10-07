# output

Results of runs that took their files from `input\`:

- `<model>_corona.max`: one group per equipment, one mesh and one Corona material per part type, a layer per part;
- `<model>_part_map.csv`: which part every material of the model became, and why;
- `<model>_part_materials.csv`: the part materials and the templates they are based on.

`corona_materials.bat sandstone` writes to `sandstone\` (or `--out`): `<scene> - Sand Stone.max`, `maps\`,
`previews\`, `sandstone_equipment.csv` and `sandstone_materials.csv`.

Runs given `--reference` / `--model` write to an `output` folder where the command is run (or `--out`).

Only this README is kept in git; everything else in this folder stays on your computer.
