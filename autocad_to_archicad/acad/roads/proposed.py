"""Proposed streets: carriageway, axes and sidewalks from the drawing; the longitudinal profile designed to the rules.

Geometry: the carriageway area comes from its hatches; the axis lines drawn by the architect become the centre lines
(ends within snap_m of another axis are joined to it, so junctions and the roundabout form one network); without axis
lines the centre lines are computed from the area (skeleton). Half widths are measured from the area.

Profile: ONE linear programme for the whole network (HiGHS). Unknowns: the axis height at every station; a junction
is one shared unknown, so streets meet at one height. Rules:
  |grade| <= max grade of the street class (tighter in serpentine bends: radius < serpentine_radius_m)
  grade change between stations <= station / crest radius (convex) and station / sag radius (concave)
  street ends that join an existing street take its height (within tie_in_tolerance_m)
  where two streets share one paved area (a fork, a junction, the legs of a hairpin drawn as one carriageway), the
  slope across it between their stations is no steeper than the grade limit either (else the paving between them
  would be a step)
Objective: the smallest height difference to the ground along the axis (least cut and fill). If the ground or the
tie-ins make the rules impossible, the grade limit is raised by the least amount that works, and that is reported.
The drainage minimum grade is checked afterwards and reported (it cannot be a linear rule)."""
import math

import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, nearest_points, unary_union

from shapely import contains_xy

from ..geometry.raster import sample_raster
from ..site import on_layers, polylines
from . import checks as C
from . import standards as S
from .geometry import area_of, as_polygons, bend_radius, boundary_tree, normals, resample, skeleton


# --------------------------------------------------------------------------- geometry
def axis_network(lines, area, snap):
    """Axis lines -> merged centre lines between ends and junctions (shapely LineStrings)."""
    geoms = [LineString(xy) for xy in lines if len(xy) >= 2 and LineString(xy).length > 1.0]
    geoms = [g for g in geoms if g.intersects(area.buffer(2.0))]
    if not geoms:
        return []
    # join loose ends to the nearest other axis within snap
    extended = []
    for i, g in enumerate(geoms):
        coords = list(g.coords)
        others = unary_union([h for j, h in enumerate(geoms) if j != i]) if len(geoms) > 1 else None
        for end in (0, -1):
            p = Point(coords[end])
            if others is None or others.is_empty:
                continue
            q = nearest_points(p, others)[1]
            d = p.distance(q)
            if 1e-6 < d <= snap:
                if end == 0:
                    coords.insert(0, (q.x, q.y))
                else:
                    coords.append((q.x, q.y))
        extended.append(LineString(coords))
    noded = unary_union(extended)
    merged = linemerge(noded)
    out = list(merged.geoms) if isinstance(merged, MultiLineString) else [merged]
    return [g for g in out if g.length > 2.0]


def graph_of(lines, tol=0.5):
    """Nodes shared by line ends: (node coordinates, [(start node, end node)] per line)."""
    nodes, ends = [], []
    for g in lines:
        c = np.asarray(g.coords)
        ids = []
        for p in (c[0], c[-1]):
            for k, q in enumerate(nodes):
                if np.hypot(*(p - q)) <= tol:
                    ids.append(k)
                    break
            else:
                nodes.append(p)
                ids.append(len(nodes) - 1)
        ends.append(tuple(ids))
    return np.array(nodes), ends


# --------------------------------------------------------------------------- profile
def side_by_side(edges, car):
    """Station pairs of different streets (or of one street far apart along it: a hairpin) whose carriageways meet,
    joined by paving: [(edge a, station i, edge b, station j, distance)]."""
    from scipy.spatial import cKDTree
    from shapely import contains, linestrings
    P = np.vstack([e["xy"] for e in edges])
    E = np.concatenate([np.full(len(e["xy"]), k) for k, e in enumerate(edges)])
    I = np.concatenate([np.arange(len(e["xy"])) for e in edges])
    S = np.concatenate([e["s"] for e in edges])
    HW = np.concatenate([e["half_w"] for e in edges])
    pairs = np.array(sorted(cKDTree(P).query_pairs(r=2.0 * float(HW.max()) + 1.0)), dtype=np.int64).reshape(-1, 2)
    if not len(pairs):
        return []
    a, b = pairs[:, 0], pairs[:, 1]
    d = np.hypot(*(P[a] - P[b]).T)
    keep = (d > 0.5) & (d <= HW[a] + HW[b] + 1.0) & ((E[a] != E[b]) | (np.abs(S[a] - S[b]) > 3.0 * d + 1.0))
    a, b, d = a[keep], b[keep], d[keep]
    if not len(a):
        return []
    inside = contains(car.buffer(0.3), linestrings(np.stack([P[a], P[b]], axis=1)))
    return [(int(E[i]), int(I[i]), int(E[j]), int(I[j]), float(dd)) for i, j, dd in zip(a[inside], b[inside], d[inside])]


def design_profile(edges, fixed, cfg, std, car=None):
    """Solve the network profile; fills e['z'], e['grade'], e['limit'] and returns a summary. car: the carriageway
    area (streets sharing it are kept at heights its paving can join)."""
    prof = cfg["roads"]["profile"]
    g_max = float(std["max_grade_permille"]) / 1000.0
    g_exc = float(std.get("exceptional_grade_permille") or 0.0) / 1000.0
    exc_cost = prof.get("exceptional_grade_cost")
    if exc_cost is None or g_exc <= g_max:
        g_exc = g_max
    g_serp = float(prof["serpentine_max_grade_permille"]) / 1000.0
    r_serp = float(prof["serpentine_radius_m"])
    r_crest, r_sag = float(std["crest_radius_m"]), float(std["sag_radius_m"])
    tol = float(prof["tie_in_tolerance_m"])
    node_var = {}
    var_of = []  # per edge: variable index of each station
    n = 0
    for e in edges:
        idx = []
        m = len(e["xy"])
        for i in range(m):
            if i == 0 or i == m - 1:
                key = ("n", e["nodes"][0 if i == 0 else 1])
                if key not in node_var:
                    node_var[key] = n
                    n += 1
                idx.append(node_var[key])
            else:
                idx.append(n)
                n += 1
        var_of.append(np.array(idx))
    nz = n
    # ground and weights per variable
    g = np.zeros(nz)
    w = np.zeros(nz)
    for e, idx in zip(edges, var_of):
        ds = np.gradient(e["s"]) if len(e["s"]) > 1 else np.ones(1)
        ok = np.isfinite(e["ground"])
        g[idx[ok]] = e["ground"][ok]
        w[idx[ok]] += ds[ok]
    ne = nz  # deviation variables e_k
    tie_nodes = [(node_var[("n", k)], z) for k, z in fixed.items() if ("n", k) in node_var]
    nt = len(tie_nodes)  # tie-in deviation variables
    segs = [(ei, i) for ei, e in enumerate(edges) for i in range(len(e["s"]) - 1)]
    t0 = nz + ne + nt  # one grade slack per segment: used only where the rules cannot be met at all
    x0 = t0 + len(segs)  # one exceptional-grade allowance per segment (up to the exceptional grade, at a cost)
    across = side_by_side(edges, car) if car is not None else []
    y0 = x0 + len(segs)  # one slack per pair of streets side by side: used only where they cannot be joined at all
    N = y0 + len(across)
    rows, cols, vals, b = [], [], [], []

    def add(coefs, rhs):
        r = len(b)
        for c, v in coefs:
            rows.append(r)
            cols.append(c)
            vals.append(v)
        b.append(rhs)

    seg_ds = np.zeros(len(segs))
    exc_room = np.zeros(len(segs))
    k_seg = 0
    for e, idx in zip(edges, var_of):
        s = e["s"]
        serp = e["radius"] < r_serp
        lim = np.where(serp, min(g_max, g_serp), g_max)
        e["limit"] = lim
        for i in range(len(s) - 1):
            ds = max(float(s[i + 1] - s[i]), 1e-6)
            seg_ds[k_seg] = ds
            gl = float(min(lim[i], lim[i + 1]))
            if not (serp[i] or serp[i + 1]):
                exc_room[k_seg] = g_exc - g_max
            add([(idx[i + 1], 1.0), (idx[i], -1.0), (t0 + k_seg, -ds), (x0 + k_seg, -ds)], gl * ds)
            add([(idx[i + 1], -1.0), (idx[i], 1.0), (t0 + k_seg, -ds), (x0 + k_seg, -ds)], gl * ds)
            k_seg += 1
        for i in range(1, len(s) - 1):
            d1, d2 = float(s[i] - s[i - 1]), float(s[i + 1] - s[i])
            if d1 <= 1e-6 or d2 <= 1e-6:
                continue
            # grade change (z[i+1]-z[i])/d2 - (z[i]-z[i-1])/d1 bounded by the mean spacing / radius
            dm = 0.5 * (d1 + d2)
            c = [(idx[i + 1], 1.0 / d2), (idx[i], -1.0 / d2 - 1.0 / d1), (idx[i - 1], 1.0 / d1)]
            add(c, dm / r_sag)
            add([(k, -v) for k, v in c], dm / r_crest)
    for j, (ea, ia, eb, ib, dd) in enumerate(across):
        ka, kb = var_of[ea][ia], var_of[eb][ib]
        if ka != kb:
            add([(ka, 1.0), (kb, -1.0), (y0 + j, -1.0)], g_max * dd)
            add([(ka, -1.0), (kb, 1.0), (y0 + j, -1.0)], g_max * dd)
    for k in range(nz):
        add([(k, 1.0), (nz + k, -1.0)], g[k])
        add([(k, -1.0), (nz + k, -1.0)], -g[k])
    # tie-ins: a strong pull to the existing street's height (beyond the tolerance), never stronger than the rules
    for j, (k, z) in enumerate(tie_nodes):
        add([(k, 1.0), (nz + ne + j, -1.0)], z + tol)
        add([(k, -1.0), (nz + ne + j, -1.0)], -(z - tol))
    A = sparse.csr_matrix((vals, (rows, cols)), shape=(len(b), N))
    cost = np.zeros(N)
    cost[nz:nz + ne] = w
    cost[nz + ne:t0] = float(prof["tie_in_weight"])
    cost[t0:x0] = 1e6 * seg_ds
    cost[x0:y0] = (float(exc_cost) * 1000.0 if exc_cost is not None else 1e6) * seg_ds
    cost[y0:] = 1e5
    bounds = [(None, None)] * nz + [(0, None)] * (x0 - nz) + [(0, float(r)) for r in exc_room] + [(0, None)] * len(across)
    res = linprog(cost, A_ub=A, b_ub=np.array(b), bounds=bounds, method="highs")
    if res.status != 0:
        raise RuntimeError(f"roads: the profile could not be solved ({res.message})")
    x = res.x
    slack = x[t0:x0]
    exc = x[x0:y0]
    steps = [{"at": ((edges[ea]["xy"][ia] + edges[eb]["xy"][ib]) / 2).round(1).tolist(), "streets": [
        edges[ea].get("name"), edges[eb].get("name")], "step_m": round(float(x[y0 + j]), 2)}
        for j, (ea, ia, eb, ib, dd) in enumerate(across) if x[y0 + j] > 0.05]
    k_seg = 0
    exceptional = []
    for e, idx in zip(edges, var_of):
        e["z"] = x[idx]
        ds = np.diff(e["s"])
        e["grade"] = np.r_[np.diff(e["z"]) / np.where(ds > 0, ds, 1), np.nan]
        used = np.r_[exc[k_seg:k_seg + len(ds)] > 1e-5, False]
        e["exceptional"] = used
        # stretches using the exceptional grade, with their lengths
        run = None
        for i in range(len(ds) + 1):
            if used[i] and run is None:
                run = i
            if (not used[i]) and run is not None:
                exceptional.append({"street": e.get("name"), "from_m": round(float(e["s"][run]), 1),
                                    "to_m": round(float(e["s"][i]), 1), "length_m": round(float(e["s"][i] - e["s"][run]), 1)})
                run = None
        k_seg += len(ds)
    tie_dev = [round(float(x[k] - z), 3) for k, z in tie_nodes]
    return {"stations": int(nz), "grade_limit_raised_by_permille": round(float(slack.max()) * 1000, 2) if len(slack) else 0.0,
            "raised_length_m": round(float(seg_ds[slack > 1e-5].sum()), 1),
            "exceptional_stretches": exceptional,
            "side_by_side_pairs": len(across), "side_by_side_steps": steps,
            "tie_in_mismatch_m": dict(zip([int(k) for k in fixed], tie_dev)),
            "objective_m2": round(float(np.dot(w, np.abs(x[:nz] - g))), 1)}


# --------------------------------------------------------------------------- building
def build(site, roles, cfg, terrain, existing, clip_area, buildings=None):
    """Proposed streets: (edges, carriageway area, sidewalk area, summary, warnings). roles: the layers stage's
    {role: [layer]}; buildings: the footprints the added sidewalks must not run into."""
    pr, prof = cfg["roads"]["proposed"], cfg["roads"]["profile"]
    step = float(prof["station_m"])
    z_arr, gt = terrain
    warnings = []
    car = area_of(on_layers(site, roles["carriageway"]))
    if car is None or car.is_empty:
        return [], None, None, {"note": "the drawing has no carriageway layer (layers.carriageway)"}, warnings
    # the class's rules on this terrain (the design speed depends on it)
    H, W = z_arr.shape
    X, Y = np.meshgrid(gt[0] + (np.arange(W) + 0.5) * gt[1], gt[3] + (np.arange(H) + 0.5) * gt[5])
    slope = S.ground_slope(z_arr, gt, contains_xy(car, X, Y))
    terrain_cat, terrain_src = S.terrain_category(cfg, slope)
    std = S.resolve(cfg, pr["class"], terrain_cat)
    std["terrain_source"], std["ground_slope_permille"] = terrain_src, round(slope, 1)
    axes = polylines(on_layers(site, roles["axes"]))
    lines = axis_network(axes, car, float(pr["snap_m"])) if axes else []
    source = "axis lines"
    if not lines:
        v, chains = skeleton(car, 1.0, float(pr["prune_m"]))
        lines = [LineString(v[ch]) for ch in chains if len(ch) >= 2]
        source = "computed centre lines (no axis lines found)"
    # carriageway parts no axis runs through get their own computed centre lines
    covered = unary_union(lines).buffer(1.0)
    for part in as_polygons(car):
        if not part.intersects(covered) and part.area > 200:
            v, chains = skeleton(part, 1.0, float(pr["prune_m"]))
            lines += [LineString(v[ch]) for ch in chains if len(ch) >= 2]
    nodes, ends = graph_of(lines)
    btree = boundary_tree(car)
    cap = 0.75 * float(std["lane_m"]) * float(std["lanes"]) + 3.0
    edges = []
    for g, (a, b) in zip(lines, ends):
        xy, s = resample(np.asarray(g.coords), step)
        if len(xy) < 2:
            continue
        xy[0], xy[-1] = nodes[a], nodes[b]
        hw = np.clip(btree.query(xy)[0], 1.0, cap)
        n = normals(xy)
        across = np.stack([sample_raster(z_arr, gt, xy + n * (f * hw)[:, None]) for f in (-0.6, -0.3, 0.0, 0.3, 0.6)])
        ground = np.nanmedian(np.where(np.isfinite(across), across, np.nan), axis=0) if np.isfinite(across).any() \
            else np.full(len(xy), np.nan)
        edges.append({"xy": xy, "s": s, "half_w": hw, "ground": ground, "radius": bend_radius(xy, s),
                      "nodes": (a, b), "kind": "proposed", "cls": pr["class"], "name": f"street {len(edges) + 1}"})
    # tie-ins: street ends on or next to an existing street take its height
    degree = np.zeros(len(nodes), int)
    for a, b in ends:
        degree[a] += 1
        degree[b] += 1
    fixed, ties = {}, []
    if existing is not None and existing.edges:
        reach = float(pr["ends_join_existing_m"])
        for k in np.nonzero(degree == 1)[0]:
            p = Point(nodes[k])
            if existing.area is not None and existing.area.distance(p) <= reach:
                z = float(existing.surface_z(nodes[k])[0])
                e = existing.edges[int(existing.project(nodes[k])["edge"][0])]
                fixed[int(k)] = z
                ties.append({"node": int(k), "xy": nodes[k].tolist(), "z": round(z, 3), "existing": e["name"] or e["cls"]})
    summary = design_profile(edges, fixed, cfg, std, car)
    for t in ties:
        t["mismatch_m"] = summary["tie_in_mismatch_m"].get(t["node"], 0.0)
        if abs(t["mismatch_m"]) > 0.1:
            warnings.append(f"the street end at ({t['xy'][0]:.0f}, {t['xy'][1]:.0f}) meets {t['existing']} "
                            f"{t['mismatch_m']:+.2f} m off its height: the rules do not allow a smooth join there "
                            "(regrade the existing street locally, or a ramp / steps)")
    if summary["side_by_side_steps"]:
        warnings.append(f"{len(summary['side_by_side_steps'])} places where streets share one carriageway but cannot be "
                        "brought to heights its paving can join within the grade limit (a step / wall between them "
                        "is needed): " + ", ".join(f"({x['at'][0]:.0f}, {x['at'][1]:.0f}) {x['step_m']:.1f} m"
                                                    for x in summary["side_by_side_steps"][:8]))
    if summary["grade_limit_raised_by_permille"] > 0.05:
        warnings.append(f"on {summary['raised_length_m']} m the rules cannot be met at all (grade up to "
                        f"{summary['grade_limit_raised_by_permille']:.1f} per mille over the limit)")
    long_exc = [x for x in summary["exceptional_stretches"] if std.get("exceptional_max_length_m") and
                x["length_m"] > float(std["exceptional_max_length_m"])]
    if long_exc:
        warnings.append(f"the exceptional grade ({std['exceptional_grade_permille']} per mille) is used over more than "
                        f"{std['exceptional_max_length_m']} m on " + ", ".join(
                            f"{x['street']} {x['from_m']:.0f}-{x['to_m']:.0f} m" for x in long_exc))
    for e in edges:
        e["cut_fill"] = e["z"] - e["ground"]
    # sidewalks: the drawing's, else a band along the carriageway
    sw = area_of(on_layers(site, roles["sidewalks"]))
    if sw is not None and not sw.is_empty:
        # only the band along the kerb is sidewalk; wider paved areas (plazas, terraces) belong to the buildings
        sw = sw.difference(car).intersection(car.buffer(float(pr["sidewalk_band_m"])))
        sw_source = "drawing"
    elif pr["sidewalks"]:
        sw = car.buffer(float(std["sidewalk_m"]), join_style=2).difference(car)
        if existing is not None and existing.area is not None:
            sw = sw.difference(existing.area)
        if buildings is not None:
            sw = sw.difference(buildings)
        sw_source = "added (class width)"
    else:
        sw, sw_source = None, "none"
    if sw is not None:
        sw = sw.intersection(clip_area)
    # ---- further checks of ՀՀՇՆ 30-01-2023 (reported)
    ck = cfg["roads"]["checks"]
    kerbs = C.kerb_radii(car, nodes, degree)
    # where the new carriageway meets an existing street its outline is cut off there, not rounded: not a kerb corner
    if existing is not None and existing.area is not None:
        kerbs = [(j, xy, r if existing.area.distance(Point(xy)) > 12.0 else "at an existing street")
                 for j, xy, r in kerbs]
    ends = C.dead_ends(car, nodes, degree, set(fixed), btree)
    r_serp_min = float(prof["serpentine_min_radius_m"])
    for e in edges:
        e["sidewalk_widths_m"] = C.sidewalk_widths(e, sw)
        over, steep, landings = C.accessibility(e, float(ck["accessible_grade_permille"]) / 1000.0,
                                                float(ck["landing_above_permille"]) / 1000.0)
        e["accessibility"] = {"over_limit_m": over, "steep_m": steep, "landings": landings}
        rmin = float(np.min(e["radius"])) if len(e["radius"]) else math.inf
        e["serpentine_too_tight"] = bool(rmin < r_serp_min and e["s"][-1] > 10)
    too_tight_kerbs = [k for k in kerbs if isinstance(k[2], float) and k[2] < float(ck["kerb_radius_m"])]
    if too_tight_kerbs:
        checked = sum(1 for k in kerbs if not isinstance(k[2], str))
        warnings.append(f"{len(too_tight_kerbs)} of {checked} junctions between new streets have a kerb corner tighter than "
                        f"{ck['kerb_radius_m']} m (ՀՀՇՆ 30-01-2023; {ck['kerb_radius_constrained_m']} m where constrained): "
                        + ", ".join(f"({k[1][0]:.0f}, {k[1][1]:.0f}) {k[2]:.0f} m" for k in too_tight_kerbs[:8]))
    small_turn = [x for x in ends if x[2] < float(ck["dead_end_turning_m"])]
    if small_turn:
        warnings.append(f"{len(small_turn)} dead ends without a turning place {ck['dead_end_turning_m']} m across: "
                        + ", ".join(f"({x[1][0]:.0f}, {x[1][1]:.0f}) {x[2]:.0f} m" for x in small_turn))
    narrow = [f"{e['name']} ({min(w for w in e['sidewalk_widths_m'] if w is not None):.1f} m)" for e in edges
              if e["s"][-1] >= 20 and any(w is not None and w < float(std["sidewalk_m"]) - 0.05
                                            for w in e["sidewalk_widths_m"] or ())]
    if narrow:
        warnings.append(f"sidewalks narrower than {std['sidewalk_m']} m (class '{pr['class']}'): " + ", ".join(narrow))
    inaccessible = [f"{e['name']} ({e['accessibility']['over_limit_m']:.0f} m)" for e in edges
                    if e["accessibility"]["over_limit_m"] >= 10]
    if inaccessible:
        warnings.append(f"sidewalks steeper than {ck['accessible_grade_permille']} per mille (1:12, the limit for "
                        "wheelchairs) - an accessible route needs another way (ramps, lifts): " + ", ".join(inaccessible))
    serp = [e["name"] for e in edges if e["serpentine_too_tight"]]
    if serp:
        warnings.append(f"bends tighter than {r_serp_min:.0f} m, the smallest serpentine radius: {', '.join(serp)}")
    summary["checks"] = {"kerb_radii": kerbs, "dead_ends": ends}
    summary.update({"centre_lines": source, "streets": len(edges), "junctions": int((degree >= 3).sum()),
                    "ends": int((degree == 1).sum()), "tie_ins": ties, "sidewalks": sw_source, "class": pr["class"],
                    "standard": std, "length_m": round(sum(float(e["s"][-1]) for e in edges), 1)})
    return edges, car.intersection(clip_area), sw, summary, warnings
