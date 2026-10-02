@echo off
REM Installs the whole toolkit: the toolkit's Python (once), then every tool in tools\ with its own install.bat
REM (Tapir and the palette buttons in Archicad, ...). Close Archicad first: it loads add-ons only at start.
REM Run it again after moving the toolkit folder, or after  git pull  brought a new tool.
setlocal
set "TOOLKIT_NO_PAUSE=1"
set "FAILED="
echo Installing the toolkit's Python ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core\setup_env.ps1" || goto env_failed
set "TOOLKIT_ENV_READY=1"
for /d %%T in ("%~dp0tools\*") do (
    if exist "%%~T\install.bat" (
        echo.
        call "%%~T\install.bat" || call set "FAILED=%%FAILED%% %%~nxT"
    )
)
echo.
if defined FAILED (
    echo Not installed:%FAILED% - see the messages above.
) else (
    echo Every tool is installed. In Archicad: Window ^> Palettes ^> Tapir, then Reload scripts.
)
pause
if defined FAILED exit /b 1
exit /b 0
:env_failed
echo.
echo The toolkit's Python could not be set up: see the messages above.
pause
exit /b 1
