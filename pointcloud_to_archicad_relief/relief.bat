@echo off
REM Relief pipeline - terminal entry.   relief.bat run --pln <project.pln> --cloud <cloud.e57>   (see README.md)
REM Python: QGIS (includes PDAL + GDAL, needed for the point cloud stages) or the environment made by setup_env.ps1.
setlocal
REM QGIS clears PYTHONPATH, so Python itself puts the pipeline folder on sys.path (works from any folder)
set "RELIEF=import sys; sys.path.insert(0, sys.argv.pop(1)); from relief.cli import main; sys.exit(main())"
set "PYTHONIOENCODING=utf-8"
set "PY_ENV=%LOCALAPPDATA%\pipeline_env\.venv\Scripts\python.exe"
set "QGIS_PY="
for /d %%Q in ("C:\Program Files\QGIS*") do (
    if exist "%%~Q\bin\python-qgis-ltr.bat" set "QGIS_PY=%%~Q\bin\python-qgis-ltr.bat"
    if exist "%%~Q\bin\python-qgis.bat" set "QGIS_PY=%%~Q\bin\python-qgis.bat"
)
if defined QGIS_PY (
    call "%QGIS_PY%" -c "%RELIEF%" "%~dp0." %*
    exit /b %ERRORLEVEL%
)
if exist "%PY_ENV%" (
    "%PY_ENV%" -c "%RELIEF%" "%~dp0." %*
    exit /b %ERRORLEVEL%
)
echo No Python found: install QGIS 3.44+, or run  powershell -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1"
exit /b 1
