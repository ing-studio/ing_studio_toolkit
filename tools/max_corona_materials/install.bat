@echo off
REM Installs the max_corona_materials tool: the toolkit's Python (once per computer), then checks that 3ds Max is
REM there. The tool adds nothing to 3ds Max: it runs it without its window (3dsmaxbatch) for the 3D steps.
setlocal
echo Installing max_corona_materials ...
if not defined TOOLKIT_ENV_READY (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\core\setup_env.ps1" || goto failed
)
call "%~dp0corona_materials.bat" check || goto failed
echo.
echo Done. Put the reference scene (.max) and the model (.fbx) in input\ and double-click corona_materials.bat.
goto end
:failed
echo.
echo The installation stopped: see the messages above.
set "INSTALL_FAILED=1"
:end
if not defined TOOLKIT_NO_PAUSE pause
if defined INSTALL_FAILED exit /b 1
exit /b 0
