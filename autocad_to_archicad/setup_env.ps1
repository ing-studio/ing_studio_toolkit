# Creates the Python 3.12 environment of this tool in %LOCALAPPDATA%\ing_studio_toolkit\autocad_to_archicad\env
# (no admin rights needed). Run once:  powershell -ExecutionPolicy Bypass -File setup_env.ps1
$ErrorActionPreference = 'Stop'
$env_dir = Join-Path $env:LOCALAPPDATA 'ing_studio_toolkit\autocad_to_archicad\env'
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
& $uv pip install --python $py numpy==2.3.3 scipy==1.16.2 shapely==2.1.2 ezdxf==1.4.4 matplotlib==3.10.6 pymupdf==1.28.2 `
    'https://github.com/cgohlke/geospatial-wheels/releases/download/v2026.8.20/gdal-3.13.3-cp312-cp312-win_amd64.whl'
if ($LASTEXITCODE) { throw "uv pip install failed" }
& $py -c "from osgeo import gdal; import numpy, scipy, shapely, ezdxf, matplotlib, pymupdf; print('OK gdal', gdal.__version__, 'ezdxf', ezdxf.__version__, 'pymupdf', pymupdf.__version__)"
