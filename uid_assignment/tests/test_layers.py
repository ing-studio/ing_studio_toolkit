"""The tool's layers, against a stand-in for Archicad:  python -m unittest discover tests  (from the tool folder)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uids import layers  # noqa: E402
from uids.util import load_config  # noqa: E402


class FakeArchicad:
    """Layers and layer combinations: GetAttributesByType, GetLayers, CreateLayers, GetLayerCombinations,
    CreateLayerCombinations, API.DeleteAttributes. Like Archicad, it adds a new layer hidden to every combination."""

    def __init__(self, *names_states, combos=()):
        self.layers = {}  # guid: {name, index, isHidden, isLocked}
        self.combos = {}  # guid: {name, layers: {layer guid: hidden}}
        for name, hidden, locked in names_states:
            self._add(name, hidden, locked)
        for name in combos:
            self.combos[f"c{len(self.combos) + 1}"] = {"name": name, "layers": {g: False for g in self.layers}}

    def _add(self, name, hidden=False, locked=False):
        i = len(self.layers) + 1
        self.layers[f"g{i}"] = {"name": name, "index": i, "isHidden": hidden, "isLocked": locked}
        for c in self.combos.values():
            c["layers"][f"g{i}"] = True

    def shown_in(self, layer_name):
        g = next(g for g, la in self.layers.items() if la["name"] == layer_name)
        return sorted(c["name"] for c in self.combos.values() if c["layers"].get(g) is False)

    def by_name(self, name):
        return next(la for la in self.layers.values() if la["name"] == name)

    def tapir(self, name, params=None, timeout=None):
        if name == "GetAttributesByType" and params["attributeType"] == "LayerCombination":
            return {"attributes": [{"attributeId": {"guid": g}, "name": c["name"]} for g, c in self.combos.items()]}
        if name == "GetAttributesByType":
            return {"attributes": [{"attributeId": {"guid": g}, "index": la["index"], "name": la["name"]}
                                   for g, la in self.layers.items()]}
        if name == "GetLayerCombinations":
            return {"layerCombinations": [{"layerCombination": {
                "attributeId": a["attributeId"], "name": self.combos[a["attributeId"]["guid"]]["name"],
                "layers": [{"attributeId": {"guid": g}, "isHidden": h, "isLocked": False, "isWireframe": False,
                            "intersectionGroupNr": 1}
                           for g, h in self.combos[a["attributeId"]["guid"]]["layers"].items()]}}
                for a in params["attributes"]]}
        if name == "CreateLayerCombinations":
            for d in params["layerCombinationDataArray"]:
                rows = {r["attributeId"]["guid"]: r["isHidden"] for r in d["layers"]}
                if params.get("overwriteExisting"):
                    self.combos[d["attributeId"]["guid"]]["layers"] = rows
                else:
                    self.combos[f"c{len(self.combos) + 1}"] = {"name": d["name"], "layers": rows}
            return {}
        if name == "GetLayers":
            return {"layers": [dict(self.layers[a["attributeId"]["guid"]]) for a in params["attributeIds"]]}
        if name == "CreateLayers":
            for d in params["layerDataArray"]:
                if params.get("overwriteExisting"):
                    la = self.layers[d["attributeId"]["guid"]]
                    la.update(isHidden=d["isHidden"], isLocked=d["isLocked"])
                elif all(la["name"] != d["name"] for la in self.layers.values()):
                    self._add(d["name"], d.get("isHidden", False), d.get("isLocked", False))
            return {}
        raise AssertionError(name)

    def api(self, name, params=None, timeout=None):
        assert name == "API.DeleteAttributes"
        for a in params["attributeIds"]:
            del self.layers[a["attributeId"]["guid"]]
        return {}


class Layers(unittest.TestCase):
    def test_names_are_english_and_from_the_config(self):
        cfg = load_config()
        self.assertEqual(layers.name(cfg, "ids"), "Window IDs - Floor Plans")
        self.assertEqual(layers.name(cfg, "types"), "Window Types - Measurements")
        self.assertEqual(layers.name({"layers": {"ids": "My IDs"}}, "ids"), "My IDs")
        self.assertTrue(all(ch.isascii() for ch in layers.name(cfg, "ids") + layers.name(cfg, "types")))

    def test_ensure_makes_a_missing_layer_once(self):
        ac = FakeArchicad(("Archicad Layer", False, False))
        a = layers.ensure(ac, "Window IDs - Floor Plans")
        b = layers.ensure(ac, "Window IDs - Floor Plans")
        self.assertEqual(a["index"], b["index"])
        self.assertEqual(len(ac.layers), 2)

    def test_opened_restores_hidden_and_locked_even_on_an_error(self):
        ac = FakeArchicad(("Archicad Layer", False, False), ("Window IDs - Floor Plans", True, True))
        with self.assertRaises(RuntimeError):
            with layers.opened(ac, ["Window IDs - Floor Plans"]):
                la = ac.by_name("Window IDs - Floor Plans")
                self.assertFalse(la["isHidden"] or la["isLocked"])
                raise RuntimeError("stop")
        la = ac.by_name("Window IDs - Floor Plans")
        self.assertTrue(la["isHidden"] and la["isLocked"])

    def test_delete_all_but_keeps_the_archicad_layer_and_the_kept_one(self):
        ac = FakeArchicad(("Archicad Layer", False, False), ("Walls", False, False),
                          ("Window Types - Measurements", False, False), ("Window IDs - Floor Plans", False, False))
        keep = ac.by_name("Window Types - Measurements")["index"]
        removed = layers.delete_all_but(ac, {keep})
        self.assertEqual(sorted(removed), ["Walls", "Window IDs - Floor Plans"])
        self.assertEqual(sorted(la["name"] for la in ac.layers.values()),
                         ["Archicad Layer", "Window Types - Measurements"])


COMBOS = ("14_Ջեռ․ և հով․ սարքերի տեղ․ հատակագիծ", "Դռների և պատուհանների մակնիշավորում", "Windows plan",
          "23_Հիմնական հատակագիծ")


class Combinations(unittest.TestCase):
    def test_a_new_ids_layer_shows_only_in_the_window_marking_combinations(self):
        cfg = load_config()
        ac = FakeArchicad(("Archicad Layer", False, False), ("Walls", False, False), combos=COMBOS)
        layers.ensure(ac, "Window IDs - Floor Plans", layers.picker(cfg, "ids"), ["Walls"])
        self.assertEqual(ac.shown_in("Window IDs - Floor Plans"),
                         sorted(["Windows plan", "Դռների և պատուհանների մակնիշավորում"]))

    def test_not_where_the_windows_are_hidden(self):
        cfg = load_config()
        ac = FakeArchicad(("Archicad Layer", False, False), ("Walls", False, False), combos=COMBOS)
        ac.combos["c2"]["layers"]["g2"] = True  # the marking combination hides the windows' layer
        layers.ensure(ac, "Window IDs - Floor Plans", layers.picker(cfg, "ids"), ["Walls"])
        self.assertEqual(ac.shown_in("Window IDs - Floor Plans"), ["Windows plan"])

    def test_a_new_types_layer_shows_in_every_combination(self):
        cfg = load_config()
        ac = FakeArchicad(("Archicad Layer", False, False), combos=COMBOS)
        layers.ensure(ac, "Window Types - Measurements", layers.picker(cfg, "types"))
        self.assertEqual(ac.shown_in("Window Types - Measurements"), sorted(COMBOS))

    def test_an_existing_layer_leaves_the_combinations_to_the_designer(self):
        cfg = load_config()
        ac = FakeArchicad(("Archicad Layer", False, False), ("Window IDs - Floor Plans", False, False))
        ac.combos["c1"] = {"name": "Windows plan", "layers": {"g1": False, "g2": True}}  # hidden there on purpose
        layers.ensure(ac, "Window IDs - Floor Plans", layers.picker(cfg, "ids"))
        self.assertEqual(ac.shown_in("Window IDs - Floor Plans"), [])

    def test_own_combination_is_made_once_with_the_ids_and_windows_shown(self):
        ac = FakeArchicad(("Archicad Layer", False, False), ("Walls", True, False), ("Pavilion", True, False),
                          ("Window IDs - Floor Plans", True, False))
        shown = {"Window IDs - Floor Plans", "Pavilion"}
        self.assertTrue(layers.own_combination(ac, "Window IDs - Floor Plans", shown))
        self.assertFalse(layers.own_combination(ac, "Window IDs - Floor Plans", {"Walls"}))
        self.assertEqual(len(ac.combos), 1)
        self.assertEqual(ac.shown_in("Pavilion"), ["Window IDs - Floor Plans"])
        self.assertEqual(ac.shown_in("Walls"), [])  # hidden now, so hidden in it


if __name__ == "__main__":
    unittest.main()
