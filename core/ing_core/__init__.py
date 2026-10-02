"""ing_core: the library the toolkit's tools share.

  util        the toolkit's folders, logging, JSON files, file identity, external programs
  config      a tool's settings: config/default.json <- project.json <- --config <- --set
  archicad    the Archicad JSON API client with its safety stop, the Archicad session a tool works in, element
              helpers, and the add-on installer (Tapir + palette buttons)
  geometry    terrain rasters (GDAL) and adaptive terrain meshes

Entry: core\\run.cmd starts a tool with this folder and the tool's folder on sys.path; python -m ing_core for the
toolkit's own commands (tapir, test).
"""
__version__ = "1.0.0"
