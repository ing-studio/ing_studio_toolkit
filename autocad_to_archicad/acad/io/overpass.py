"""OpenStreetMap buildings of an area through the Overpass API (buildings, building:parts and multipolygon buildings
with their geometry, which the main API's map call gives only as bare node lists), cached in the work folder.
Data (c) OpenStreetMap contributors, ODbL."""
import json
import time
import urllib.parse
import urllib.request

from ..util import detail, load_json, log, save_json, warn


def _query(urls, q, agent):
    last = None
    for url in urls:
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": agent})
                with urllib.request.urlopen(req, timeout=300) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:  # busy server (429 / 504): wait, then the next mirror
                last = e
                time.sleep(5 * (attempt + 1))
        warn(f"context: Overpass server {url} did not answer ({last}) - trying the next one")
    raise RuntimeError(f"no Overpass server answered ({last})")


def _rings(geometry):
    return [[(p["lon"], p["lat"]) for p in geometry]] if geometry else []


def buildings(bbox, urls, agent, cache_path):
    """Buildings and building parts in bbox = (west, south, east, north) degrees:
    [{"id", "kind": "building" | "part", "tags", "outer": [[(lon, lat), ...]], "inner": [...]}]."""
    bbox = [round(v, 5) for v in bbox]
    cached = load_json(cache_path)
    if cached and cached.get("bbox") == bbox:
        detail(f"context: OpenStreetMap buildings from the cache ({len(cached['items']):,})")
        return cached["items"]
    w, s, e, n = bbox
    box = f"{s},{w},{n},{e}"
    q = (f'[out:json][timeout:240];(way["building"]({box});way["building:part"]({box});'
         f'relation["building"]["type"="multipolygon"]({box});relation["building:part"]["type"="multipolygon"]({box}););'
         'out tags geom;')
    log("context: downloading the OpenStreetMap buildings around the site (Overpass) ...")
    data = _query(urls, q, agent)
    items = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        kind = "part" if "building:part" in tags and "building" not in tags else "building"
        if el["type"] == "way":
            outer, inner = _rings(el.get("geometry")), []
        elif el["type"] == "relation":
            outer = [r for m in el.get("members", []) if m.get("role") == "outer" for r in _rings(m.get("geometry"))]
            inner = [r for m in el.get("members", []) if m.get("role") == "inner" for r in _rings(m.get("geometry"))]
        else:
            continue
        outer = [r for r in outer if len(r) >= 4]
        if outer:
            items.append({"id": f"{el['type'][0]}{el['id']}", "kind": kind, "tags": tags, "outer": outer, "inner": inner})
    save_json(cache_path, {"bbox": bbox, "licence": "(c) OpenStreetMap contributors, ODbL",
                           "fetched": time.strftime("%Y-%m-%d %H:%M"), "items": items})
    return items
