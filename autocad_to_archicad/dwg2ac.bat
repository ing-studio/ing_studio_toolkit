@echo off
REM AutoCAD -> Archicad site tool - terminal entry.   dwg2ac.bat plan.dwg survey.e57   (dwg2ac.bat --help)
REM Python: the environment made once by setup_env.ps1.
setlocal
set "ACAD=import sys; sys.path.insert(0, sys.argv.pop(1)); from acad.cli import main; sys.exit(main())"
set "PYTHONIOENCODING=utf-8"
set "PY_ENV=%LOCALAPPDATA%\ing_studio_toolkit\autocad_to_archicad\env\.venv\Scripts\python.exe"
if exist "%PY_ENV%" goto env
echo No Python environment yet: run once   powershell -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1"
exit /b 1
:env
"%PY_ENV%" -c "%ACAD%" "%~dp0." %*
exit /b %ERRORLEVEL%
