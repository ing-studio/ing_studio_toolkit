"""The command  corona_materials.bat sandstone SCENE.max ...  : scenes re-finished in the Sand Stone materials.

Steps (3ds Max works without its window; the scenes run side by side):
  maps       the Sand Stone texture maps (corona_materials.maps) into <out>\\maps
  survey     each scene: its equipment and materials (scripts/survey_scene.ms)
  decide     black twins, black-only equipment, swatches, the material of every material (sandstone.py), on the
             equipment's real size; <out>\\sandstone_equipment.csv and <out>\\sandstone_materials.csv say what was
             decided and why
  refinish   each scene (scripts/refinish_sandstone.ms): brought to its real size, arranged in rows under a dummy
             named after it, surfaces lying on each other cleaned (scripts/clean_scene.ms), its round parts made
             smoother (scripts/smooth_rounds.ms: welded, smoothed by angle, round objects subdivided, flat ones'
             normals weighted), sharp edges rounded (scripts/chamfer_edges.ms)
  combine    the scenes put together in one file, side by side: <out>\\<name> - Sand Stone.max
             (scripts/combine_sandstone.ms); with sandstone.combine false, or one scene, each scene is its own file
  preview    a material board and Corona renders of the result (scripts/preview_sandstone.ms) in <out>\\previews
"""
import csv
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ing_core.util import log, ok, skip, slug, warn

from . import maps, sandstone
from .maxbatch import SCRIPTS, run_step

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def read_survey(path):
    eqs, mats = [], {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith('{"eq"'):
                eqs.append(json.loads(line))
            elif line.startswith('{"material"'):
                r = json.loads(line)
                mats[r["material"]] = r["rgb"]
    return eqs, mats


def read_sizes(path):
    """{equipment: (width, depth, height)} in mm, as the refinish step saved it."""
    out = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            f = line.split("\t")
            if len(f) == 4:
                out[f[0]] = tuple(int(v) for v in f[1:])
    return out


def common_name(stems):
    """The name of the scenes together: the words their names begin with, without a last word that only numbers them
    ("Technogym Equipment Part 1" ... "Part 4" -> "Technogym Equipment")."""
    if len(stems) == 1:
        return stems[0]
    words = []
    for ws in zip(*(s.split() for s in stems)):
        if any(w != ws[0] for w in ws):
            break
        words.append(ws[0])
    while words and re.fullmatch(r"(?i)part|parts|no\.?|nr\.?|#|-|_", words[-1]):
        words.pop()
    return " ".join(words) or "Scenes"


def closeups(eqs, actions, count):
    """The equipment to render close up: the biggest of each kind kept, and one recoloured."""
    act = {name: a for name, a, _ in actions}
    seen, out = set(), []
    for eq in sorted(eqs, key=lambda e: -e["faces"]):
        kind = tuple(round(d / 5) for d in sandstone.dims_cm(eq))
        if act.get(eq["eq"]) == "keep" and kind not in seen and eq["faces"] > 3000:
            seen.add(kind)
            out.append(eq["eq"])
        if len(out) >= count:
            break
    rec = [eq["eq"] for eq in sorted(eqs, key=lambda e: -e["faces"]) if act.get(eq["eq"]) == "recolour"]
    return out + rec[:1]


def run(cfg, scenes, out_dir, batch, tool_dir, preview=True, force=False):
    s = cfg["sandstone"]
    out_dir = Path(out_dir)
    work = cfg["_work"] / "sandstone"
    work.mkdir(parents=True, exist_ok=True)
    maps_dir = out_dir / "maps"
    previews = out_dir / "previews"
    scenes = [Path(p) for p in scenes]
    names = {p: slug(p.stem) for p in scenes}
    combine = bool(s["combine"]) and len(scenes) > 1
    root = cfg["max"]["model_root"] or ""
    gap = float(s["gap_mm"])

    # ---------------------------------------------------------------- maps
    made = maps.make_all(maps_dir, size=s["map_size"])
    images = Path(s["images_dir"]) if s["images_dir"] else None
    if images and images.is_dir():
        for p in images.iterdir():
            if p.suffix.lower() in IMAGE_TYPES and not (maps_dir / p.name).exists():
                shutil.copy2(p, maps_dir / p.name)
    ok(f"maps: {len(made)} Sand Stone maps ({s['map_size']} px) in {maps_dir}")

    def parallel(fn, items, workers=None):
        with ThreadPoolExecutor(max_workers=max(1, int(workers or s["parallel"]))) as ex:
            return list(ex.map(fn, items))

    # ---------------------------------------------------------------- survey
    script_time = (SCRIPTS / "survey_scene.ms").stat().st_mtime

    def survey(p):
        out = work / f"{names[p]}_survey.jsonl"
        if not force and out.exists() and out.stat().st_mtime >= max(p.stat().st_mtime, script_time):
            skip(f"survey: {p.name} (done before; --force redoes it)")
            return out
        step_log = work / f"{names[p]}_survey.log"
        run_step(batch, f"survey_{names[p]}", "survey_scene.ms",
                 {"ING_WORK": str(work) + "\\", "ING_SCENE": str(p), "ING_SURVEY": str(out), "ING_ROOT": root,
                  "ING_LOG": str(step_log)}, step_log)
        ok(f"survey: {p.name}")
        return out
    surveys = dict(zip(scenes, parallel(survey, scenes)))

    # ---------------------------------------------------------------- decide
    known = sandstone.known_colours(tool_dir)
    data = {names[p]: read_survey(surveys[p]) for p in scenes}
    for eqs, _ in data.values():
        sandstone.to_real_size(eqs, float(s["import_unit_mm"]))
    actions = sandstone.decide({k: v[0] for k, v in data.items()}, known)
    materials = {}
    for _, mats in data.values():
        materials.update(mats)
    mrows = sandstone.material_rows(materials, known)
    swatches = [n for n, c in materials.items() if sandstone.is_swatch_material(n, sandstone.colour_of(n, c, known))]
    zones = [n for n, c in materials.items() if sandstone.is_zone_material(n, sandstone.colour_of(n, c, known))]
    sandstone.write(work, actions, mrows, swatches, zones)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "sandstone_materials.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scene_material", "colour", "sand_stone_material", "why"])
        for name, target, c, why in mrows:
            w.writerow([name, "%d,%d,%d" % tuple(c), target, why])
    for p in scenes:
        a = [x[1] for x in actions[names[p]]]
        log(f"decide: {p.name}: {a.count('keep')} kept, {a.count('remove')} removed (hidden, or black with a Sand Stone twin), "
            f"{a.count('recolour')} recoloured (black only)")
    ok(f"decide: {len(mrows)} materials -> {len({r[1] for r in mrows})} Sand Stone materials; "
       f"{out_dir / 'sandstone_materials.csv'}")

    # ---------------------------------------------------------------- refinish
    parts_dir = work / "parts"
    if combine:
        parts_dir.mkdir(exist_ok=True)

    def refinish(p):
        out = (parts_dir if combine else out_dir) / f"{p.stem} - Sand Stone.max"
        step_log = work / f"{names[p]}_refinish.log"
        run_step(batch, f"refinish_{names[p]}", "refinish_sandstone.ms",
                 {"ING_WORK": str(work) + "\\", "ING_SCENE": str(p), "ING_OUT": str(out),
                  "ING_ACTIONS": str(work / f"{names[p]}_actions.tsv"), "ING_MAPS": str(maps_dir) + "\\",
                  "ING_LAYER": sandstone.RECOLOURED_LAYER, "ING_FALLBACK": s["fallback"], "ING_LOG": str(step_log),
                  "ING_ROOT": root, "ING_UNIT": float(s["import_unit_mm"]), "ING_PART": p.stem, "ING_GAP": gap,
                  "ING_SIZES": str(work / f"{names[p]}_sizes.tsv"),
                  "ING_SMOOTH": bool(s["smooth"]), "ING_SMOOTH_ANGLE": float(s["smooth_angle"]),
                  "ING_SMOOTH_ITERS": int(s["smooth_iterations"]),
                  "ING_SMOOTH_RENDER_ITERS": int(s["smooth_render_iterations"]),
                  "ING_CHAMFER": bool(s["chamfer"]), "ING_CHAMFER_ANGLE": float(s["chamfer_angle"]),
                  "ING_CHAMFER_RATIO": float(s["chamfer_ratio"]), "ING_CHAMFER_MIN": float(s["chamfer_min_mm"])},
                 step_log)
        for line in step_log.read_text(encoding="utf-8", errors="replace").splitlines():
            if any(k in line for k in ("removed", "re-finished", "not in the map", "materials in the scene", "round parts",
                                       "rounded edges", "real size", "arranged", "saved")):
                log(f"refinish: {p.name}: " + line.split(" ", 2)[-1])
        ok(f"refinish: {out}")
        return out
    parts = parallel(refinish, scenes)

    # what became of every equipment, and its real size as saved
    with open(out_dir / "sandstone_equipment.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scene", "equipment", "action", "why", "width_mm", "depth_mm", "height_mm"])
        for p in scenes:
            sizes = read_sizes(work / f"{names[p]}_sizes.tsv")
            for eq, a, why in actions[names[p]]:
                w.writerow([p.name, eq, a, why, *sizes.get(eq, ("", "", ""))])
    ok(f"sizes: {out_dir / 'sandstone_equipment.csv'}")

    # ---------------------------------------------------------------- combine
    if combine:
        result = out_dir / f"{common_name([p.stem for p in scenes])} - Sand Stone.max"
        list_file = work / "combine_parts.tsv"
        list_file.write_text("".join(f"{part}\t{p.stem}\n" for p, part in zip(scenes, parts)), encoding="utf-8")
        step_log = work / "combine.log"
        run_step(batch, "combine", "combine_sandstone.ms",
                 {"ING_WORK": str(work) + "\\", "ING_PARTS": str(list_file), "ING_OUT": str(result),
                  "ING_GAP": gap, "ING_LOG": str(step_log)}, step_log)
        for line in step_log.read_text(encoding="utf-8", errors="replace").splitlines():
            if any(k in line for k in ("merged", "materials", "saved")):
                log("combine: " + line.split(" ", 2)[-1])
        ok(f"combine: {result}")
        for part in parts:                      # (the scenes' own files were only a step on the way)
            Path(part).unlink(missing_ok=True)
        results = [result]
    else:
        results = parts

    # ---------------------------------------------------------------- preview
    if preview:
        previews.mkdir(parents=True, exist_ok=True)
        board_log = work / "board.log"
        run_step(batch, "material_board", "material_board.ms",
                 {"ING_WORK": str(work) + "\\", "ING_MAPS": str(maps_dir) + "\\",
                  "ING_BOARD": str(previews / "material_board.png"), "ING_PASSES": int(s["preview_passes"]),
                  "ING_WIDTH": int(s["preview_width"])}, board_log)
        ok(f"preview: {previews / 'material_board.png'}")

        def views(p):
            """(image, node) lines: the scene's equipment all together, then a few close up."""
            eqs = data[names[p]][0]
            out = [(f"{names[p]}_overview", p.stem)]
            out += [(f"{names[p]}_{slug(e)}", e) for e in closeups(eqs, actions[names[p]], int(s["closeups"]))]
            return out

        def render(job):
            res, scene_list, tag = job
            views_file = work / f"{tag}_views.tsv"
            views_file.write_text("".join(f"{img}\t{node}\n" for p in scene_list for img, node in views(p)),
                                  encoding="utf-8")
            step_log = work / f"{tag}_preview.log"
            run_step(batch, f"preview_{tag}", "preview_sandstone.ms",
                     {"ING_WORK": str(work) + "\\", "ING_SCENE": str(res), "ING_PREVIEW": str(previews) + "\\",
                      "ING_VIEWS": str(views_file), "ING_PASSES": int(s["preview_passes"]),
                      "ING_WIDTH": int(s["preview_width"]), "ING_LOG": str(step_log)}, step_log)
            ok(f"preview: {res.name} -> {previews}")
        jobs = [(results[0], scenes, "combined")] if combine else \
            [(res, [p], names[p]) for p, res in zip(scenes, results)]
        try:
            parallel(render, jobs, s["preview_parallel"])   # renders need much more memory
        except Exception as e:  # a preview is a check, not a result: the scenes are saved
            warn(f"preview: {e}")
    return results
