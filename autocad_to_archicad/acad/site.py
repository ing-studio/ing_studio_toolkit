"""The site plan as found by the inventory stage (site.pkl), and picking its primitives by layer: by name patterns,
or by the role the layers stage found for them (layers.json)."""
import fnmatch
import math
import pickle

import numpy as np

_cache = {}


def load_site(job):
    """dict(prims, layers, bbox): the site plan's primitives in drawing metres."""
    key = str(job.w("site.pkl"))
    if key not in _cache:
        with open(key, "rb") as f:
            _cache[key] = pickle.load(f)
    return _cache[key]


def layer_names(raw, layers):
    """Every name a layer answers to: as stored, as shown (Armenian decoded), and without XREF prefixes
    ('2918_R_SITE$0$MP_ROADS' -> 'MP_ROADS', 'X|WALLS' -> 'WALLS')."""
    names = {raw}
    shown = layers.get(raw, {}).get("name", raw)
    names.add(shown)
    for n in (raw, shown):
        names.add(n.split("$0$")[-1].split("|")[-1])
    return names


def matcher(patterns, layers):
    pats = [p.lower() for p in patterns]
    memo = {}

    def match(raw):
        if raw not in memo:
            memo[raw] = any(fnmatch.fnmatchcase(n.lower(), p) for n in layer_names(raw, layers) for p in pats)
        return memo[raw]
    return match


def on_layers(site, names):
    """The primitives on the given layers (raw names)."""
    names = set(names or ())
    return [p for p in site["prims"] if p["layer"] in names]


def arc_points(c, r, a0, a1, step=0.5):
    if a1 <= a0:
        a1 += 2 * math.pi
    n = max(2, int(r * (a1 - a0) / step) + 1)
    t = np.linspace(a0, a1, n)
    return np.column_stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t)])


def polylines(prims, closed_rings=True):
    """Every primitive's outline as (N, 2) polylines (closed ones repeat the first point)."""
    out = []
    for p in prims:
        k = p["kind"]
        if k == "poly":
            xy = p["xy"]
            out.append(np.vstack([xy, xy[:1]]) if p["closed"] and closed_rings else xy)
        elif k == "fill":
            out += [np.vstack([r, r[:1]]) for r in p["rings"]]
        elif k == "arc":
            out.append(arc_points(p["c"], p["r"], p["a0"], p["a1"]))
        elif k == "circle":
            out.append(arc_points(p["c"], p["r"], 0.0, 2 * math.pi))
    return out
