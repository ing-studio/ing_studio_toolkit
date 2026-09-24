"""AutoCAD -> Archicad site tool: a DWG site plan (+ the survey point cloud) -> an Archicad site model.

The output holds ONE terrain Mesh (adjusted around the streets), the existing and new street surfaces, and the
drawing itself as 2D elements on its own layers.
Entry points: ``dwg2ac.bat`` (terminal), ``python -m acad``.
"""
__version__ = "0.1.0"

from .util import TOOL_SEARCH

TOOL_SEARCH.update({
    "accoreconsole_exe": [r"C:\Program Files\Autodesk\AutoCAD 20*\accoreconsole.exe"],
})
