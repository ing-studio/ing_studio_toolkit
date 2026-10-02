@echo off
REM Point cloud -> Archicad relief.   relief.bat survey.e57   or   relief.bat project.pln survey.e57   (relief.bat --help)
REM Without files (a double-click): the files in input\, results in output\.
REM Python: QGIS's (it brings PDAL, for new point clouds), else the toolkit's (install.bat).
setlocal
set "TOOL_DIR=%~dp0."
set "TOOL_MODULE=relief.cli"
set "TOOL_PYTHON=qgis"
call "%~dp0..\..\core\run.cmd" %*
exit /b %ERRORLEVEL%
