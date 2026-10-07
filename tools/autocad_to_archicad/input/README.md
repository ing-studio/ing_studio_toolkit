# input

Put the files of one site here, then double-click `site_model.bat` (or run it without file names):

- the site plan: exactly one `.dwg` or `.dxf`;
- the survey point cloud of the site: one E57, LAS, LAZ, ... file (or set `paths.point_cloud` in `config\project.json`);
- optionally the project PDFs: every `.pdf` here is read (underground levels, floor areas).

Files given on the command line (`site_model.bat plan.dwg survey.e57`) are used instead, wherever they are.

Only this README is kept in git; everything else in this folder stays on your computer.
