"""OpenStreetMap buildings and streets around the site, from the main OSM API (tiled: it limits nodes per request),
cached in the work folder. Data (c) OpenStreetMap contributors, ODbL."""
import json
import math
import time
import urllib.request

from ..util import detail, load_json, log, save_json


def _get(url, agent, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": agent})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt + 1 == tries:
                raise RuntimeError(f"OpenStreetMap request failed ({e}): {url}")
            time.sleep(5 * (attempt + 1))


def fetch(cfg, bbox, cache_path, tile_deg=0.007):
    """Buildings and streets (ways with full geometry) in bbox = (west, south, east, north) degrees.
    Returns a list of {"id", "tags", "lonlat": [[lon, lat], ...]}."""
    bbox = [round(v, 5) for v in bbox]
    cached = load_json(cache_path)
    if cached and cached.get("bbox") == bbox:
        detail(f"georef: OpenStreetMap data from the cache ({len(cached['ways']):,} ways)")
        return cached["ways"]
    w, s, e, n = bbox
    nx, ny = max(1, math.ceil((e - w) / tile_deg)), max(1, math.ceil((n - s) / tile_deg))
    log(f"georef: downloading OpenStreetMap data ({nx * ny} tiles) ...")
    nodes, ways = {}, {}
    site = cfg["site"]
    agent = site["osm_user_agent"]
    for i in range(nx):
        for j in range(ny):
            tb = (w + (e - w) * i / nx, s + (n - s) * j / ny, w + (e - w) * (i + 1) / nx, s + (n - s) * (j + 1) / ny)
            data = _get(f"{site['osm_api']}?bbox={tb[0]:.6f},{tb[1]:.6f},{tb[2]:.6f},{tb[3]:.6f}", agent)
            for el in data.get("elements", []):
                if el["type"] == "node":
                    nodes[el["id"]] = (el["lon"], el["lat"])
                elif el["type"] == "way":
                    ways[el["id"]] = el
    out = []
    for way in ways.values():
        tags = way.get("tags", {})
        if not ("highway" in tags or "building" in tags or "building:part" in tags):
            continue
        coords = [nodes.get(nid) for nid in way["nodes"]]
        if all(coords):
            out.append({"id": way["id"], "tags": tags, "lonlat": coords})
    save_json(cache_path, {"bbox": bbox, "source": site["osm_api"], "licence": "(c) OpenStreetMap contributors, ODbL",
                           "fetched": time.strftime("%Y-%m-%d %H:%M"), "ways": out})
    log(f"georef: OpenStreetMap: {sum(1 for x in out if 'highway' in x['tags']):,} street ways, "
        f"{sum(1 for x in out if 'highway' not in x['tags']):,} buildings")
    return out
