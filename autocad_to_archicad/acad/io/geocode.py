"""Where the site is, when nobody said: place names found in the inputs, looked up in OpenStreetMap's gazetteer
(Nominatim), grouped into candidate places. The georef stage tries them in order and keeps the first one where the
drawing's buildings clearly match OpenStreetMap, so a wrong name costs time but never a wrong placement.

Names come from the file names of the drawing, the point cloud and the project documents, and the drawing's texts;
words that describe the file rather than the place (site, plan, survey, cloud, rev ...) are left out.
The script of the drawing's texts and layer names narrows the country (Armenian letters -> Armenia).
Results are cached in the work folder (geocode.json); Nominatim is asked at most once a second.
"""
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from ..util import detail, load_json, save_json

GENERIC = {
    "site", "siteplan", "plan", "plans", "master", "masterplan", "general", "genplan", "layout", "drawing", "drawings",
    "dwg", "dxf", "pdf", "set", "sheet", "sheets", "survey", "surveys", "topo", "topographic", "topography", "ground",
    "points", "point", "cloud", "scan", "scans", "las", "laz", "e57", "final", "rev", "revision", "copy", "new", "old",
    "draft", "model", "project", "proj", "existing", "proposed", "area", "areas", "calculation", "calc", "base",
    "august", "september", "october", "november", "december", "january", "february", "march", "april", "may", "june",
    "july", "the", "and", "for", "with", "ver", "version", "issue", "export", "xref", "sample", "test",
    "district", "quarter", "zone", "block", "centre", "center", "city", "town", "street", "avenue", "park", "complex",
    "residential", "phase", "stage", "lot", "plot", "parcel",
}
# scripts used by one country's language: its letters in the drawing say where it is
SCRIPT_COUNTRY = ((0x0531, 0x058F, "am"), (0x10A0, 0x10FF, "ge"), (0x0590, 0x05FF, "il"), (0x0370, 0x03FF, "gr"))


def country_hint(texts):
    """ISO country code from the letters of the texts (Armenian -> 'am'), or None."""
    count = Counter()
    for t in texts:
        for ch in t:
            o = ord(ch)
            for lo, hi, cc in SCRIPT_COUNTRY:
                if lo <= o <= hi:
                    count[cc] += 1
    return count.most_common(1)[0][0] if count else None


def phrases(texts, max_phrases=8):
    """Place-name phrases from free texts / file names: generic words, numbers and codes left out, most frequent first."""
    out = Counter()
    for t in texts:
        words = [w for w in re.split(r"[^\w]+|_", t) if w]
        words = [w for w in words if len(w) >= 3 and not any(c.isdigit() for c in w) and w.lower() not in GENERIC]
        if not words or len(words) > 5:
            continue
        out[" ".join(words)] += 1
        if len(words) > 1:  # each longer word alone too: 'Cascade Arts District' -> 'Cascade'
            for w in words:
                if len(w) >= 5:
                    out[w] += 0.5
    return [p for p, _ in out.most_common(max_phrases)]


def _search(query, country, cfg, cache):
    key = f"{country or '*'}|{query}"
    if key in cache:
        return cache[key]
    params = {"q": query, "format": "jsonv2", "limit": 5}
    if country:
        params["countrycodes"] = country
    url = cfg["site"]["geocode_api"] + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": cfg["site"]["osm_user_agent"]})
    time.sleep(1.1)  # Nominatim usage policy: at most one request a second
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # no network: no candidates from this name
        detail(f"georef: place search for '{query}' failed ({e})")
        return []
    hits = [{"lon": float(x["lon"]), "lat": float(x["lat"]), "name": x.get("display_name", "")[:120],
             "type": f"{x.get('category', '')}/{x.get('type', '')}", "importance": float(x.get("importance") or 0.0)}
            for x in res]
    cache[key] = hits
    return hits


def _km(a, b):
    dx = (a[0] - b[0]) * 111.32 * math.cos(math.radians((a[1] + b[1]) / 2))
    dy = (a[1] - b[1]) * 110.57
    return math.hypot(dx, dy)


def candidates(letters, file_names, drawing_texts, cfg, cache_path, group_km=3.0):
    """Candidate places [{lonlat, score, from, hits}] for the site, best first. `letters` = drawing texts and layer
    names (their script gives the country); place names come from the file names first, then the drawing's texts."""
    country = country_hint(letters)
    queries = phrases(file_names, 6)
    queries += [q for q in phrases(drawing_texts, 4) if q not in queries]
    cache = load_json(cache_path) or {}
    groups = []
    for q in queries:
        for h in _search(q, country, cfg, cache):
            p = (h["lon"], h["lat"])
            for g in groups:
                if _km(g["lonlat"], p) <= group_km:
                    g["hits"].append(h)
                    g["from"].add(q)
                    break
            else:
                groups.append({"lonlat": p, "hits": [h], "from": {q}})
    save_json(cache_path, cache)
    for g in groups:
        # a place several names point to, and the names' importance in OSM
        g["score"] = len(g["from"]) + len(g["hits"]) * 0.2 + max(h["importance"] for h in g["hits"])
        lon = sum(h["lon"] for h in g["hits"]) / len(g["hits"])
        lat = sum(h["lat"] for h in g["hits"]) / len(g["hits"])
        g["lonlat"] = [round(lon, 6), round(lat, 6)]
        g["from"] = sorted(g["from"])
    groups.sort(key=lambda g: -g["score"])
    return groups, queries, country


def input_names(job):
    """File names of the inputs (without folders and extensions), project documents included. Sheet titles are
    headings ('AREA CALCULATION'), not places, so they are not used."""
    names = [Path(job.drawing).stem]
    if job.cloud:
        names.append(Path(job.cloud).stem)
    docs = load_json(job.w("documents.json")) or {}
    names += [Path(d.get("file", "")).stem for d in docs.get("documents", [])]
    return [n for n in names if n]
