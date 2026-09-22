"""Stage cloud: point cloud file(s) -> one LAZ (cloud_raw.laz) + its extent."""
from ..io import cloud_formats
from ..io.pdal import pdal_json
from ..util import all_exist, log, save_json, skip


def run(job, force=False):
    out = job.c("cloud_raw.laz")
    if not force and all_exist([out, job.c("cloud_summary.json")]):
        skip("cloud: already converted")
        return
    if force or not out.exists():
        out.unlink(missing_ok=True)
        cloud_formats.convert_all(job, out)
    info = pdal_json(job, ["info", "--summary", str(out)])["summary"]
    save_json(job.c("cloud_summary.json"), {"num_points": info["num_points"], "bounds": info["bounds"],
                                            "inputs": cloud_formats.signature(job)})
    b = info["bounds"]
    log(f"cloud: {info['num_points']:,} points; X {b['minx']:.1f} .. {b['maxx']:.1f}, "
        f"Y {b['miny']:.1f} .. {b['maxy']:.1f}, Z {b['minz']:.1f} .. {b['maxz']:.1f}")
