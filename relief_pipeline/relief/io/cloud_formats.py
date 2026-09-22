"""Point cloud file(s) -> one LAZ (cloud_raw.laz).

  .laz                              used as is (copied)
  .las .copc.laz                    PDAL readers.las -> LAZ
  .ply .pcd .pts .ptx               PDAL readers.ply / pcd / pts / ptx
  .xyz .txt .csv .asc .neu          PDAL readers.text; delimiter, header line and columns are sniffed
  .e57 and anything else            CloudCompare CLI
  .lcf                              rejected: Archicad's internal cache, use the file it was imported from

Several files are converted one by one and merged (same coordinate system assumed).
"""
import re
import shutil
from pathlib import Path

from ..util import file_signature, log, run, tool
from .pdal import pdal_pipeline

TEXT_EXT = {".xyz", ".txt", ".csv", ".asc", ".neu", ".xyzrgb", ".xyzn"}
PDAL_EXT = {".ply": "readers.ply", ".pcd": "readers.pcd", ".pts": "readers.pts", ".ptx": "readers.ptx"}
LAS_WRITER = {"type": "writers.las", "compression": True, "minor_version": 4, "forward": "all",
              "scale_x": 0.001, "scale_y": 0.001, "scale_z": 0.001,
              "offset_x": "auto", "offset_y": "auto", "offset_z": "auto"}


def signature(job):
    """Identifies the input (file name, size, date) so results from another cloud are never reused."""
    return {"files": [file_signature(s) for s in job.clouds], "clip_source": job.cfg["cloud"].get("clip_source")}


def same_signature(a, b):
    def norm(sig):
        files = [(Path(f.get("name") or f.get("path", "")).name.lower(), f["size"], f["mtime"])
                 for f in sig.get("files", [])]
        return files, sig.get("clip_source")
    return norm(a) == norm(b)


def convert_all(job, out):
    if len(job.clouds) == 1:
        convert_one(job, job.clouds[0], out)
        return
    parts = []
    for i, s in enumerate(job.clouds):
        part = job.c(f"cloud_part_{i:02d}.laz")
        convert_one(job, s, part)
        parts.append(part)
    log(f"cloud: merging {len(parts)} files")
    pdal_pipeline(job, [{"type": "readers.las", "filename": str(p)} for p in parts]
                  + [{"type": "filters.merge"}, dict(LAS_WRITER, filename=str(out), forward="header")], "merge")
    for p in parts:
        p.unlink()


def convert_one(job, src, out):
    ext = ".copc.laz" if src.lower().endswith(".copc.laz") else Path(src).suffix.lower()
    log(f"cloud: input {src} ({ext or 'no extension'})")
    if ext == ".lcf":
        raise RuntimeError("LCF is Archicad's internal point cloud cache and cannot be read. "
                           "Use the file it was imported from (E57 / LAS / LAZ / PLY / XYZ ...).")
    if ext == ".laz":
        shutil.copyfile(src, out)
    elif ext in (".las", ".copc.laz"):
        pdal_pipeline(job, [{"type": "readers.las", "filename": src}, dict(LAS_WRITER, filename=str(out))], "convert")
    elif ext in PDAL_EXT and not (ext == ".pts" and _pts_without_count(src)):
        pdal_pipeline(job, [{"type": PDAL_EXT[ext], "filename": src}, dict(LAS_WRITER, filename=str(out))], "convert")
    elif ext in TEXT_EXT or ext == ".pts":
        reader = text_reader(src)
        log(f"cloud: text columns {reader['header']!r}, skip {reader['skip']} line(s)")
        pdal_pipeline(job, [reader, dict(LAS_WRITER, filename=str(out))], "convert")
    else:
        _cloudcompare_to_laz(job, src, out)
    if not out.exists():
        raise RuntimeError(f"Conversion produced no output for {src}")


def _cloudcompare_to_laz(job, src, out):
    # CloudCompare's "-SAVE_CLOUDS FILE <name>" splits names on spaces, so let it write
    # "<input>.laz" next to a local copy of the input and rename afterwards.
    local = job.c("source_cloud" + Path(src).suffix.lower())
    log(f"cloud: copying {src}")
    shutil.copyfile(src, local)
    cc_out = job.c("source_cloud.laz")
    cc_out.unlink(missing_ok=True)
    run([tool(job.cfg, "cloudcompare_exe"), "-SILENT", "-AUTO_SAVE", "OFF",
         "-O", str(local), "-C_EXPORT_FMT", "LAS", "-EXT", "laz", "-NO_TIMESTAMP", "-SAVE_CLOUDS"])
    local.unlink()
    if not cc_out.exists():
        raise RuntimeError(f"CloudCompare could not convert {src}")
    cc_out.replace(out)


# --------------------------------------------------------------------------- text sniffing
_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_KNOWN = {"x": "X", "y": "Y", "z": "Z", "r": "Red", "g": "Green", "b": "Blue", "red": "Red", "green": "Green",
          "blue": "Blue", "i": "Intensity", "intensity": "Intensity", "nx": "NormalX", "ny": "NormalY",
          "nz": "NormalZ", "classification": "Classification", "class": "Classification",
          "easting": "X", "northing": "Y", "elevation": "Z", "height": "Z"}


def _split(line, sep):
    return [t for t in (line.split(sep) if sep else line.split()) if t != ""]


def _pts_without_count(src):
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        first = f.readline().strip()
    return not re.fullmatch(r"\d+", first)


def _integer_columns(data, cols):
    return all(all(float(r[i]) == int(float(r[i])) and 0 <= float(r[i]) <= 65535 for r in data) for i in cols)


def text_reader(src, n_lines=200):
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        lines = [f.readline() for _ in range(n_lines)]
    lines = [ln.rstrip("\r\n") for ln in lines if ln]
    sep = next((cand for cand in (";", ",", "\t") if sum(cand in ln for ln in lines) > len(lines) * 0.8), None)

    skip, names = 0, None
    for ln in lines:
        toks = _split(ln.strip().lstrip("/#").strip(), sep)
        if len(toks) >= 3 and all(_NUM.match(t) for t in toks):
            break
        # a lone integer is a point count (PTS style); words are a header line
        if toks and not all(_NUM.match(t) for t in toks):
            names = toks
        skip += 1
    data = [_split(ln.strip(), sep) for ln in lines[skip:] if ln.strip()]
    if not data:
        raise RuntimeError(f"No numeric point records found in {src}")
    ncol = min(len(r) for r in data)

    if names and len(names) >= ncol:
        dims = [_KNOWN.get(n.lower().strip("\"' "), re.sub(r"\W", "_", n.strip("\"' ")) or f"Col{i + 1}")
                for i, n in enumerate(names[:ncol])]
    else:
        dims = ["X", "Y", "Z"] + [f"Col{i + 1}" for i in range(3, ncol)]
        if ncol >= 6 and _integer_columns(data, range(3, 6)):
            dims[3:6] = ["Red", "Green", "Blue"]
            if ncol >= 9:
                dims[6:9] = ["NormalX", "NormalY", "NormalZ"]
        elif ncol >= 7 and _integer_columns(data, range(4, 7)):
            dims[3:7] = ["Intensity", "Red", "Green", "Blue"]
    if not {"X", "Y", "Z"} <= set(dims):
        raise RuntimeError(f"Could not identify X/Y/Z columns in {src} (header {names})")
    reader = {"type": "readers.text", "filename": src, "header": (sep or " ").join(dims), "skip": skip}
    if sep:
        reader["separator"] = sep
    return reader
