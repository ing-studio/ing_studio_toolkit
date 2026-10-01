# Installs the Window IDs add-on (uid_assignment) into Archicad:
#   1. Tapir into Archicad 28 / 29, if it is not there yet (restart Archicad afterwards)
#   2. the "Window IDs" button into the Tapir palette (Window > Palettes > Tapir > Reload scripts)
#
#   powershell -ExecutionPolicy Bypass -File addon\install.ps1           install
#   powershell -ExecutionPolicy Bypass -File addon\install.ps1 -Remove   take the button away (Tapir stays)
#
# Needs only Python 3.10+ (no packages): the py launcher, python on PATH, or the toolkit's pipeline_env.
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$tool_dir = Split-Path -Parent $PSScriptRoot
$action = if ($Remove) { 'remove' } else { 'install' }

$candidates = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += , @('py', '-3') }
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += , @('python') }
$env_py = Join-Path $env:LOCALAPPDATA 'pipeline_env\.venv\Scripts\python.exe'
if (Test-Path $env_py) { $candidates += , @($env_py) }

$python = $null
foreach ($c in $candidates) {
    $exe, $pre = $c[0], @($c | Select-Object -Skip 1)
    & $exe @pre -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $python = $c; break }
}
if (-not $python) {
    Write-Host 'No Python 3.10+ found: install it from python.org (tick "Add python.exe to PATH") and run this again.' -ForegroundColor Red
    exit 1
}

$env:PYTHONIOENCODING = 'utf-8'
$run = 'import sys; sys.path.insert(0, sys.argv.pop(1)); from uids.cli import main; sys.exit(main())'
$exe, $pre = $python[0], @($python | Select-Object -Skip 1)
& $exe @pre -c $run $tool_dir addon $action
$code = $LASTEXITCODE
if ($code -eq 0 -and -not $Remove) {
    Write-Host ''
    Write-Host 'Done. In Archicad: Window > Palettes > Tapir, then Reload scripts; the button is "Window IDs".' -ForegroundColor Green
    Write-Host 'If Tapir was just added, restart Archicad first.'
}
exit $code
