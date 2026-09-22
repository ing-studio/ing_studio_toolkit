"""Stage ground: denoise + bare-earth classification of the cloud (PDAL CSF or SMRF)."""
from ..io.pdal import class_counts, pdal_pipeline
from ..util import all_exist, load_json, log, save_json, skip


def run(job, force=False):
    classified, ground = job.c("classified.laz"), job.c("ground.laz")
    if not force and all_exist([classified, ground]):
        skip("ground: already classified")
        if not (load_json(job.c("ground_summary.json")) or {}).get("classes"):
            write_ground_summary(job)
        return
    g = job.cfg["ground"]
    stages = [{"type": "readers.las", "filename": str(job.c("cloud_raw.laz"))}]
    clip = job.cfg["cloud"].get("clip_source")
    if clip:
        xmin, ymin, xmax, ymax = clip
        stages.append({"type": "filters.crop", "bounds": f"([{xmin},{xmax}],[{ymin},{ymax}])"})
    stages += [
        # CloudCompare exports no return info; CSF/SMRF only use last/only returns.
        {"type": "filters.assign", "value": ["Classification = 0", "ReturnNumber = 1", "NumberOfReturns = 1"]},
        {"type": "filters.voxelcenternearestneighbor", "cell": g["voxel_size"]},
        {"type": "filters.outlier", "method": "statistical", "mean_k": g["outlier_mean_k"],
         "multiplier": g["outlier_multiplier"]},
        {"type": "filters.elm", "cell": g["elm_cell"], "threshold": g["elm_threshold"]},
    ]
    method = g["method"]
    stages.append(dict({"type": f"filters.{method}", "ignore": "Classification[7:7]"}, **g[method]))
    stages += [
        {"type": "writers.las", "filename": str(classified), "compression": True, "forward": "all"},
        {"type": "filters.range", "limits": "Classification[2:2]"},
        {"type": "writers.las", "filename": str(ground), "compression": True, "forward": "all"},
    ]
    log(f"ground: running PDAL ({method}) ...")
    pdal_pipeline(job, stages, "ground")
    write_ground_summary(job)


def write_ground_summary(job):
    counts = class_counts(job, job.c("classified.laz"), "class_counts")
    total = sum(counts.values())
    names = {"0": "unclassified", "1": "non-ground", "2": "ground", "7": "noise"}
    summary = {"total_after_voxel": total,
               "classes": {names.get(k, k): {"count": v, "pct": round(100.0 * v / total, 2)} for k, v in counts.items()}}
    save_json(job.c("ground_summary.json"), summary)
    for k, v in summary["classes"].items():
        log(f"ground: {k:13s} {v['count']:>12,}  ({v['pct']}%)")
