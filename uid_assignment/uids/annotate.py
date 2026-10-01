"""What the tool adds to a project once the IDs are in the windows - the same in the open project and in the output
copy:

  layer 'Window IDs - Floor Plans'       an ID label on every window that carries its ID (Archicad's associative
                                         label: it shows the window's own Element ID and moves with it)
  layer 'Window Types - Measurements'    the worksheet «Պ Պատուհանների տեսքեր»: every type's front view with its
                                         width and height dimensions, sills, quantity, opening, and the table of
                                         the types
  layer combination 'Window IDs - Floor Plans'   (made once) the layers as they are, with the IDs and every
                                                 window shown
"""
from . import layers, plans, sheet
from .archicad import ArchicadError
from .util import warn


def annotate(ac, types, stories, cfg, draw=True):
    """Returns {'geometry', 'tags', 'id_layer', 'rotation', 'drawing', 'sheet', 'types_layer'}."""
    windows = [w for t in types for w in t.windows]
    geometry = plans.outlines(ac, sorted({w.floor for w in windows}))
    tag_list = plans.tags(ac, types, geometry)
    labelled = {w.guid for t in types for w in t.windows if w.id == t.label}  # a window that kept an old ID: no tag
    out = {"geometry": geometry, "tags": tag_list,
           "id_layer": plans.place_ids(ac, [tg for tg in tag_list if tg.guid in labelled], cfg,
                                       window_layers={w.layer for w in windows if w.guid in labelled}),
           "rotation": ac.view_rotation(),  # of the floor plan, which is in front after the labels
           "drawing": sheet.layout(types, stories, cfg), "sheet": None, "types_layer": None}
    own = cfg.get("layer_combinations", {}).get("own", layers.DEFAULTS["ids"])
    if own:  # made once, from the floor plan's layers while it is in front: every window with its mark shown
        try:  # (the measurements layer, made after it, is shown in every combination, this one too)
            layers.own_combination(ac, own, {out["id_layer"], layers.name(cfg, "types")} | {w.layer for w in windows})
        except ArchicadError as e:
            warn(f"layers: the layer combination '{own}' could not be made ({e})")
    if draw:
        out["sheet"], out["types_layer"] = sheet.place(ac, out["drawing"], cfg)
    return out
