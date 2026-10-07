@echo off
REM 3ds Max model -> clean Corona part materials.   corona_materials.bat   or   corona_materials.bat map   (--help)
REM Without options (a double-click): the reference scene and the model in input\, results in output\.
REM Python: the toolkit's (install.bat); 3ds Max with Corona does the 3D work, without its window.
setlocal
set "TOOL_DIR=%~dp0."
set "TOOL_MODULE=corona_materials.cli"
set "TOOL_PYTHON="
call "%~dp0..\..\core\run.cmd" %*
exit /b %ERRORLEVEL%
