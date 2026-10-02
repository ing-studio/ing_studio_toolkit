@echo off
REM The launcher of every tool. A tool's .bat sets
REM   TOOL_DIR      its folder ("%~dp0.")
REM   TOOL_MODULE   the module whose main() runs (relief.cli, ...)
REM   TOOL_PYTHON   qgis = prefer QGIS's Python (it brings PDAL, for point clouds); empty = the toolkit's Python
REM and then:  call "%~dp0..\..\core\run.cmd" %*
REM
REM Python, the first one found:
REM   1. %ING_TOOLKIT_PYTHON%, when set (a Python of your choice, with the packages of core\requirements.txt)
REM   2. QGIS's Python, when the tool prefers it and QGIS is installed
REM   3. the toolkit's Python, made by install.bat in %LOCALAPPDATA%\ing_studio_toolkit\env
REM Python is started with core\ and the tool's folder on sys.path (QGIS's Python clears PYTHONPATH, so Python puts
REM them there itself). A tool started without arguments (a double-click) waits for a key at the end, so its window
REM stays readable.
set "PYTHONIOENCODING=utf-8"
set "TOOL_RUN=import sys; sys.path[:0] = [sys.argv.pop(1), sys.argv.pop(1)]; from %TOOL_MODULE% import main; sys.exit(main())"
set "TOOLKIT_ENV_PY=%LOCALAPPDATA%\ing_studio_toolkit\env\.venv\Scripts\python.exe"
set "PAUSE_AT_END="
if "%~1"=="" set "PAUSE_AT_END=1"
set "QGIS_PY="
if /i "%TOOL_PYTHON%"=="qgis" for /d %%Q in ("C:\Program Files\QGIS*") do (
    if exist "%%~Q\bin\python-qgis-ltr.bat" set "QGIS_PY=%%~Q\bin\python-qgis-ltr.bat"
    if exist "%%~Q\bin\python-qgis.bat" set "QGIS_PY=%%~Q\bin\python-qgis.bat"
)
REM (the exit code is read outside any ( ) block: inside one, %ERRORLEVEL% is filled in before the command runs)
if defined ING_TOOLKIT_PYTHON goto custom
if defined QGIS_PY goto qgis
if exist "%TOOLKIT_ENV_PY%" goto env
echo No Python for the toolkit yet: double-click install.bat in the tool's folder (or in the toolkit's folder).
if defined PAUSE_AT_END pause
exit /b 1
:custom
"%ING_TOOLKIT_PYTHON%" -c "%TOOL_RUN%" "%~dp0." "%TOOL_DIR%" %*
goto done
:qgis
call "%QGIS_PY%" -c "%TOOL_RUN%" "%~dp0." "%TOOL_DIR%" %*
goto done
:env
"%TOOLKIT_ENV_PY%" -c "%TOOL_RUN%" "%~dp0." "%TOOL_DIR%" %*
:done
set "TOOL_EXIT=%ERRORLEVEL%"
if defined PAUSE_AT_END (echo. & pause)
exit /b %TOOL_EXIT%
