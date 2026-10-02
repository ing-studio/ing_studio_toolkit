# Creates (or brings up to date) the toolkit's Python: Python 3.12 with the packages of core\requirements.txt, in
# %LOCALAPPDATA%\ing_studio_toolkit\env. No admin rights needed. Every tool's install.bat runs it; it is quick when
# the environment is already there.
#   powershell -ExecutionPolicy Bypass -File core\setup_env.ps1           create / update
#   powershell -ExecutionPolicy Bypass -File core\setup_env.ps1 -Remove   delete it
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$env_dir = Join-Path $env:LOCALAPPDATA 'ing_studio_toolkit\env'
if ($Remove) {
    if (Test-Path $env_dir) { Remove-Item -Recurse -Force $env_dir; Write-Host "Removed $env_dir" }
    exit 0
}
$requirements = Join-Path $PSScriptRoot 'requirements.txt'
New-Item -ItemType Directory -Force $env_dir | Out-Null
$env:UV_CACHE_DIR = Join-Path $env_dir 'cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $env_dir 'python'
$uv = Join-Path $env_dir 'uv\uv.exe'
if (-not (Test-Path $uv)) {
    Write-Host 'Downloading uv (the Python installer) ...'
    $zip = Join-Path $env_dir 'uv.zip'
    Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/download/0.12.15/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip -UseBasicParsing
    Expand-Archive $zip (Join-Path $env_dir 'uv') -Force
    Remove-Item $zip
}
$py = Join-Path $env_dir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    & $uv venv (Join-Path $env_dir '.venv') --python 3.12
    if ($LASTEXITCODE) { throw 'uv venv failed' }
}
& $uv pip install --quiet --python $py -r $requirements
if ($LASTEXITCODE) { throw 'uv pip install failed' }
& $py -c "from osgeo import gdal; import numpy, scipy, shapely, ezdxf, matplotlib, pymupdf; print('Toolkit Python ready: gdal', gdal.__version__, '- ezdxf', ezdxf.__version__, '- pymupdf', pymupdf.__version__)"
if ($LASTEXITCODE) { throw 'the toolkit Python does not import its packages' }
