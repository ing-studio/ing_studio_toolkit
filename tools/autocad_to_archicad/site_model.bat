@echo off
REM AutoCAD site plan -> Archicad site model.   site_model.bat plan.dwg survey.e57   (site_model.bat --help)
REM Without files (a double-click): the drawing, point cloud and PDFs in input\, results in output\.
REM Python: the toolkit's (install.bat).
setlocal
set "TOOL_DIR=%~dp0."
set "TOOL_MODULE=site_model.cli"
set "TOOL_PYTHON="
call "%~dp0..\..\core\run.cmd" %*
exit /b %ERRORLEVEL%
