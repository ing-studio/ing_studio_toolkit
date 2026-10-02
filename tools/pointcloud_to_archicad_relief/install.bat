@echo off
REM Installs the relief tool: the toolkit's Python (once per computer), then the Archicad add-on - Tapir, if it is
REM not there yet, and the "Relief from point cloud" button in the Tapir palette.
REM Close Archicad first: it loads add-ons only at start. Run it again after moving the toolkit folder.
setlocal
echo Installing pointcloud_to_archicad_relief ...
if not defined TOOLKIT_ENV_READY (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\core\setup_env.ps1" || goto failed
)
call "%~dp0relief.bat" addon install || goto failed
echo.
echo Done. In Archicad: Window ^> Palettes ^> Tapir, then Reload scripts. The button is "Relief from point cloud".
echo If Tapir was just added, restart Archicad first.
goto end
:failed
echo.
echo The installation stopped: see the messages above.
set "INSTALL_FAILED=1"
:end
if not defined TOOLKIT_NO_PAUSE pause
if defined INSTALL_FAILED exit /b 1
exit /b 0
