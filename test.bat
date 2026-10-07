@echo off
REM Runs the test suites with the toolkit's Python: every one, or the ones named.
REM   test.bat                       core and every tool
REM   test.bat core archicad_window_ids   only these
REM Each suite runs in its own Python, from its own folder. They need no Archicad, AutoCAD or network;
REM set ING_TEST_3DSMAX=1 to run max_corona_materials' steps in 3ds Max too.
setlocal
set "TOOL_DIR=%~dp0."
set "TOOL_MODULE=ing_core.cli"
set "TOOL_PYTHON="
call "%~dp0core\run.cmd" test %*
exit /b %ERRORLEVEL%
