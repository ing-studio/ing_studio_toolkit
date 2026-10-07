@echo off
REM Installs the archicad_window_ids tool: the toolkit's Python (once per computer), then the Archicad add-on -
REM Tapir into Archicad 28 / 29, if it is not there yet, and the "Window IDs" button in the Tapir palette.
REM Close Archicad first: it loads add-ons only at start. Run it again after moving the toolkit folder.
setlocal
echo Installing archicad_window_ids ...
if not defined TOOLKIT_ENV_READY (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\core\setup_env.ps1" || goto failed
)
call "%~dp0uid.bat" addon install || goto failed
echo.
echo Done. In Archicad: Window ^> Palettes ^> Tapir, then Reload scripts. The button is "Window IDs".
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
