"""The tool's own layers, named in English so they are easy to find in the Layer Settings:

  Window IDs - Floor Plans       the ID label of every window on the floor plans
  Window Types - Measurements    the worksheet: every type's front view, its dimensions and the table

(names from config "layers"). A layer is made when the project does not have it yet. While the tool works on its
layers they are shown and unlocked - Archicad neither changes nor deletes what is on a hidden or locked layer - and
afterwards they are put back as the designer had them.

Archicad adds a new layer to every layer combination as hidden, so a view of the View Map would not show it. When a
layer is made, it is shown where it belongs (config "layer_combinations"): the measurements layer in every
combination (it only has the worksheet, so no plan changes), the IDs layer in the combinations meant for window
marks (their name has 'պատուհան' or 'window') that show the windows - not on the heating or lighting plans, and
not where the marks would stand without their windows. The combination
'Window IDs - Floor Plans' is made once too: the layers as they are at that moment, with the IDs and the layers of
the windows shown (Archicad's labels do not hide with their window here, so no mark is left without its window).
Later runs leave the combinations to the designer.
"""
from contextlib import contextmanager

from .archicad import ArchicadError
from .util import log, warn

DEFAULTS = {"ids": "Window IDs - Floor Plans", "types": "Window Types - Measurements"}
DEFAULT_SHOW = {"ids": ["պատուհան", "window"], "types": "all"}
ARCHICAD_LAYER = 1  # the layer every project has, which can be neither hidden, locked nor deleted


def name(cfg, which):
    return str(cfg.get("layers", {}).get(which) or DEFAULTS[which]).strip()


def all_layers(ac):
    """{name: {'attributeId', 'index', 'isHidden', 'isLocked', ...}} of every layer of the project."""
    atts = ac.tapir("GetAttributesByType", {"attributeType": "Layer"}).get("attributes", [])
    if not atts:
        return {}
    states = ac.tapir("GetLayers", {"attributeIds": [{"attributeId": a["attributeId"]} for a in atts]})["layers"]
    return {a.get("name", ""): {**st, "attributeId": a["attributeId"], "index": a["index"]}
            for a, st in zip(atts, states)}


def ensure(ac, layer_name, show_in=None, with_layers=()):
    """The layer of that name (made, shown and unlocked, when the project does not have it). A layer just made is
    also shown in the layer combinations whose name show_in(name) accepts and that show one of `with_layers` (names;
    empty: no such condition)."""
    have = all_layers(ac)
    if layer_name not in have:
        ac.tapir("CreateLayers", {"layerDataArray": [{"name": layer_name, "isHidden": False, "isLocked": False}]})
        have = all_layers(ac)
        if layer_name not in have:
            raise ArchicadError(f"the layer '{layer_name}' could not be made")
        log(f"layers: '{layer_name}' made")
        if show_in:
            try:
                need = {have[n]['attributeId']['guid'] for n in with_layers if n in have}
                shown = show_in_combinations(ac, have[layer_name], show_in, need)
            except ArchicadError as e:
                warn(f"layers: '{layer_name}' not shown in the layer combinations ({e}) - tick it there by hand")
            else:
                log(f"layers: '{layer_name}' shown in {len(shown)} layer combination(s)"
                    + (f": {', '.join(shown[:4])}{' ...' if len(shown) > 4 else ''}" if shown else
                       " (none fits" + (", or none of those shows the windows" if with_layers else "") + ")"))
    return have[layer_name]


def picker(cfg, which):
    """show_in for ensure(): which layer combinations show the layer `which` when it is made (config
    layer_combinations: 'all', or words of which one is in the name)."""
    rule = cfg.get("layer_combinations", {}).get(which, DEFAULT_SHOW[which])
    if rule == "all":
        return lambda _name: True
    words = [w.lower() for w in (rule or [])]
    return lambda name: any(w in name.lower() for w in words)


def combinations(ac):
    """Every layer combination: [{'attributeId', 'name', 'layers': [{'attributeId', 'isHidden', ...}]}]."""
    atts = ac.tapir("GetAttributesByType", {"attributeType": "LayerCombination"}).get("attributes", [])
    if not atts:
        return []
    got = ac.tapir("GetLayerCombinations", {"attributes": [{"attributeId": a["attributeId"]} for a in atts]})
    return [c["layerCombination"] for c in got.get("layerCombinations", []) if "layerCombination" in c]


def _row(attribute_id, hidden=False, locked=False, wireframe=False, group=1):
    return {"attributeId": attribute_id, "isHidden": bool(hidden), "isLocked": bool(locked),
            "isWireframe": bool(wireframe), "intersectionGroupNr": int(group)}


def show_in_combinations(ac, layer, pick, need=()):
    """Shows `layer` in the layer combinations whose name pick(name) accepts and that show one of the layers whose
    guids are in `need` (when given); returns their names."""
    done = []
    for c in combinations(ac):
        if not pick(c.get("name", "")):
            continue
        rows = [dict(r) for r in c.get("layers", [])]
        if need and not any(r["attributeId"]["guid"] in need and not r.get("isHidden") for r in rows):
            continue  # the windows are not shown there: their marks would stand alone
        mine = [r for r in rows if r["attributeId"]["guid"] == layer["attributeId"]["guid"]]
        if mine and not mine[0].get("isHidden"):
            continue
        if mine:
            mine[0]["isHidden"] = False
        else:
            rows.append(_row(layer["attributeId"]))
        ac.tapir("CreateLayerCombinations", {"overwriteExisting": True, "layerCombinationDataArray": [
            {"attributeId": c["attributeId"], "name": c["name"], "layers": rows}]})
        done.append(c["name"])
    return done


def own_combination(ac, combination_name, shown):
    """The layer combination `combination_name`: every layer as it is now, with the layers named in `shown` shown.
    Made once - an existing one is the designer's. Returns True when made."""
    if any(c.get("name") == combination_name for c in combinations(ac)):
        return False
    rows = [_row(la["attributeId"], la.get("isHidden") and n not in shown, la.get("isLocked"),
                 la.get("isWireframe"), la.get("intersectionGroupNr", 1)) for n, la in all_layers(ac).items()]
    ac.tapir("CreateLayerCombinations", {"layerCombinationDataArray": [{"name": combination_name, "layers": rows}]})
    log(f"layers: layer combination '{combination_name}' made (the layers as they are now, the windows and their IDs "
        "shown)")
    return True


def _set(ac, layer_name, layer, hidden, locked):
    ac.tapir("CreateLayers", {"overwriteExisting": True, "layerDataArray": [
        {"attributeId": layer["attributeId"], "name": layer_name, "isHidden": bool(hidden), "isLocked": bool(locked)}]})


@contextmanager
def opened(ac, names):
    """The layers of these names shown and unlocked inside the block; as they were after it (also on an error).
    Archicad keeps the layers' visibility per open tab: bring the view to work in to the front before this."""
    have = all_layers(ac)
    states = {n: have[n] for n in names if n in have}
    changed = {n: la for n, la in states.items() if la.get("isHidden") or la.get("isLocked")}
    for n, la in changed.items():
        _set(ac, n, la, False, False)
    try:
        yield states
    finally:
        for n, la in changed.items():
            _set(ac, n, la, la.get("isHidden"), la.get("isLocked"))


def delete_all_but(ac, keep_indices):
    """Deletes every layer except the Archicad layer and the given ones; returns the names deleted."""
    extra = [(n, la) for n, la in all_layers(ac).items()
             if la["index"] != ARCHICAD_LAYER and la["index"] not in keep_indices]
    if extra:
        ac.api("API.DeleteAttributes", {"attributeIds": [{"attributeId": la["attributeId"]} for _, la in extra]})
    return [n for n, _ in extra]
