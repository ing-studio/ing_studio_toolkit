@echo off
REM Uninstalls the whole toolkit: every tool's palette buttons, the Tapir the toolkit added to Archicad (a Tapir
REM installed some other way stays), and the toolkit's Python. The toolkit folder itself is left; delete it yourself.
REM Close Archicad first: it may write its add-on list back when it quits.
setlocal
set "TOOLKIT_NO_PAUSE=1"
for /d %%T in ("%~dp0tools\*") do (
    if exist "%%~T\uninstall.bat" call "%%~T\uninstall.bat"
)
echo.
set "TOOL_DIR=%~dp0."
set "TOOL_MODULE=ing_core.cli"
set "TOOL_PYTHON="
call "%~dp0core\run.cmd" tapir remove
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core\setup_env.ps1" -Remove
REM the Python environments of earlier versions of the tools
if exist "%LOCALAPPDATA%\pipeline_env" rmdir /s /q "%LOCALAPPDATA%\pipeline_env"
if exist "%LOCALAPPDATA%\ing_studio_toolkit\autocad_to_archicad\env" rmdir /s /q "%LOCALAPPDATA%\ing_studio_toolkit\autocad_to_archicad\env"
echo.
choice /m "Also delete the tools' caches of intermediate results (%LOCALAPPDATA%\ing_studio_toolkit)"
if errorlevel 2 goto done
if exist "%LOCALAPPDATA%\ing_studio_toolkit" rmdir /s /q "%LOCALAPPDATA%\ing_studio_toolkit"
echo Caches deleted.
:done
echo.
echo The toolkit is uninstalled.
pause
