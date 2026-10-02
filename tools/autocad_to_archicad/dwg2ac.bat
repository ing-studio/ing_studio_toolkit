@echo off
REM AutoCAD site plan -> Archicad site model.   dwg2ac.bat plan.dwg survey.e57   (dwg2ac.bat --help)
REM Without files (a double-click): the drawing, point cloud and PDFs in input\, results in output\.
REM Python: the toolkit's (install.bat).
setlocal
set "TOOL_DIR=%~dp0."
set "TOOL_MODULE=acad.cli"
set "TOOL_PYTHON="
call "%~dp0..\..\core\run.cmd" %*
exit /b %ERRORLEVEL%
