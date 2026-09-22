"""PDAL command line: pipelines, info, class counts."""
import json

from ..util import load_json, run, save_json, tool


def pdal_pipeline(job, stages, name, metadata=False):
    """Write a PDAL pipeline JSON into the cloud work folder and run it; with metadata=True return its metadata."""
    pipe_path = job.c(f"pdal_{name}.json")
    save_json(pipe_path, stages)
    cmd = [tool(job.cfg, "pdal_exe"), "pipeline", str(pipe_path)]
    meta_path = job.c(f"pdal_{name}_metadata.json")
    if metadata:
        cmd += ["--metadata", str(meta_path)]
    run(cmd)
    return load_json(meta_path) if metadata else pipe_path


def pdal_json(job, args):
    _, out, _ = run([tool(job.cfg, "pdal_exe")] + args)
    return json.loads(out)


def class_counts(job, laz, name):
    """Point count per LAS classification value."""
    meta = pdal_pipeline(job, [{"type": "readers.las", "filename": str(laz)},
                               {"type": "filters.stats", "dimensions": "Classification", "count": "Classification"}],
                         name, metadata=True)
    stats = meta["stages"]["filters.stats"]["statistic"]
    counts = {}
    for st in (stats if isinstance(stats, list) else [stats]):
        if st.get("name") == "Classification":
            for item in st.get("counts", []):
                val, cnt = item.split("/")
                counts[str(int(float(val)))] = int(cnt)
    return counts
