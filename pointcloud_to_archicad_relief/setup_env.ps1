# Creates a Python 3.12 environment for the pipeline in %LOCALAPPDATA%\pipeline_env (no admin rights needed).
# Enough for the reference, contours, archicad and qa stages; the point cloud stages also need PDAL (QGIS).
$ErrorActionPreference = 'Stop'
$env_dir = Join-Path $env:LOCALAPPDATA 'pipeline_env'
New-Item -ItemType Directory -Force $env_dir | Out-Null
$env:UV_CACHE_DIR = Join-Path $env_dir 'cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $env_dir 'python'
$uv = Join-Path $env_dir 'uv\uv.exe'
if (-not (Test-Path $uv)) {
    $zip = Join-Path $env_dir 'uv.zip'
    Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.12.15/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip -UseBasicParsing
    Expand-Archive $zip (Join-Path $env_dir 'uv') -Force
    Remove-Item $zip
}
& $uv venv (Join-Path $env_dir '.venv') --python 3.12
if ($LASTEXITCODE) { throw "uv venv failed" }
$py = Join-Path $env_dir '.venv\Scripts\python.exe'
& $uv pip install --python $py numpy scipy shapely matplotlib pandas `
    'https://github.com/cgohlke/geospatial-wheels/releases/download/v2026.8.20/gdal-3.13.3-cp312-cp312-win_amd64.whl'
if ($LASTEXITCODE) { throw "uv pip install failed" }
& $py -c "from osgeo import gdal; import numpy, scipy, shapely, matplotlib, pandas; print('OK gdal', gdal.__version__)"
