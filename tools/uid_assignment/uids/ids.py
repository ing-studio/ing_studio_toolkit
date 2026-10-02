"""Writing the type label (Պ-01 ...) into the Element ID of every window.

The Element ID is Archicad's built-in property General_ElementID; Tapir's SetDetailsOfElements cannot change it,
the built-in SetPropertyValuesOfElements can.
"""
from collections import Counter

from .archicad import ArchicadError
from .util import log, warn

BATCH = 500


def write_ids(ac, types, dry_run=False):
    """Sets the ID of the windows whose ID differs from their type's label; returns how many changed."""
    changes = [(w, t.label) for t in types for w in t.windows if w.id != t.label]
    locked = [(w, new) for w, new in changes if not w.editable]
    if locked:
        by_layer = Counter(w.layer for w, _ in locked)
        warn(f"ids: {len(locked)} window(s) keep their old ID: they are locked, or on locked layers ("
             + ", ".join(f"«{name}» {n}" for name, n in by_layer.items())
             + ") - unlock them and run again")
        changes = [(w, new) for w, new in changes if w.editable]
    if dry_run or not changes:
        log(f"ids: {len(changes)} window ID(s) {'would change' if dry_run else 'to change'}")
        return len(changes)
    prop = ac.api("API.GetPropertyIds", {"properties": [{"type": "BuiltIn", "nonLocalizedName":
                                                         "General_ElementID"}]})["properties"][0]
    if "propertyId" not in prop:
        raise ArchicadError(f"the Element ID property is not available: {prop}")
    failed = []
    for i in range(0, len(changes), BATCH):
        part = changes[i:i + BATCH]
        res = ac.api("API.SetPropertyValuesOfElements", {"elementPropertyValues": [
            {"elementId": {"guid": w.guid}, "propertyId": prop["propertyId"],
             "propertyValue": {"type": "string", "status": "normal", "value": new}} for w, new in part]})
        for (w, new), r in zip(part, res.get("executionResults", [])):
            if r.get("success"):
                w.id = new
            else:
                failed.append((w, new, r.get("error", {}).get("message", r)))
    for w, new, why in failed:
        warn(f"ids: {w.guid} ({w.id}) could not be set to {new}: {why}")
    log(f"ids: {len(changes) - len(failed)} window ID(s) changed")
    return len(changes) - len(failed)
