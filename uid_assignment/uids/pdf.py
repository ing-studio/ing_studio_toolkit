"""PDF files from SVG pages, printed by the Edge (or Chrome) every Windows computer has - nothing to install."""
import glob
import subprocess
import tempfile
from pathlib import Path

from .util import log, warn

BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


def browser():
    for pattern in BROWSERS:
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    return None


def write(pdf_path, pages, size_mm):
    """Each SVG of `pages` on its own page of `size_mm` (width, height). Returns the path, or None."""
    exe = browser()
    if not exe:
        warn(f"pdf: no Edge or Chrome found - {Path(pdf_path).name} not written")
        return None
    w, h = size_mm
    page_html = (f'<!doctype html><html><head><meta charset="utf-8"><style>@page{{size:{w}mm {h}mm;margin:0}}'
                 f'html,body{{margin:0;padding:0}}.p{{width:{w}mm;height:{h}mm;overflow:hidden;'
                 'page-break-after:always}'
                 '.p:last-child{page-break-after:auto}svg{display:block}</style></head><body>'
                 + "".join(f'<div class="p">{svg}</div>' for svg in pages) + "</body></html>")
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.html"
        src.write_text(page_html, encoding="utf-8")
        pdf_path.unlink(missing_ok=True)
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--print-to-pdf-no-header", f"--user-data-dir={Path(tmp) / 'profile'}",
                        f"--print-to-pdf={pdf_path}", src.as_uri()], capture_output=True, timeout=300)
    if not pdf_path.exists():
        warn(f"pdf: {pdf_path.name} was not written by {Path(exe).name}")
        return None
    log(f"pdf: {pdf_path} ({len(pages)} page(s))")
    return pdf_path
