"""Stage cloud: point cloud file(s) -> one LAZ (cloud_raw.laz) + its extent."""
from ..io import cloud_formats
from ..io.pdal import pdal_json
from ..util import all_exist, log, save_json


def run(job, force=False):
    out = job.c("cloud_raw.laz")
    if not force and all_exist([out, job.c("cloud_summary.json")]):
        log(f"cloud: skip, {out.name} exists")
        return
    if force or not out.exists():
        out.unlink(missing_ok=True)
        cloud_formats.convert_all(job, out)
    info = pdal_json(job, ["info", "--summary", str(out)])["summary"]
    save_json(job.c("cloud_summary.json"), {"num_points": info["num_points"], "bounds": info["bounds"],
                                            "inputs": cloud_formats.signature(job)})
    log(f"cloud: {info['num_points']:,} points, bounds {info['bounds']}")
