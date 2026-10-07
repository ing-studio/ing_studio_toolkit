# input

Put the files of one conversion here, then double-click `corona_materials.bat`:

- the **reference scene**: one `.max` whose Corona materials are the templates of the part materials;
- the **model**: one `.fbx` to convert;
- optionally `model_materials.json`: the model's materials with their mesh counts and colours (`[{"name": ..., "meshes": ..., "rgb": [r, g, b]}]`); without it they are read from the imported model.

Files given with `--reference` and `--model` are used instead, wherever they are.

For `corona_materials.bat sandstone`: put the scenes to re-finish in `sandstone\` (they are only read).

Only this README is kept in git; everything else in this folder stays on your computer.
