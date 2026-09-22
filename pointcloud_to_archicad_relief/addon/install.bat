@echo off
REM Installs the Archicad 28 add-on of the relief pipeline: Tapir + the "Relief from point cloud" palette button.
REM Close Archicad first (it reads its add-on list only at start). Remove with:  install.bat remove
setlocal
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=install"
call "%~dp0..\relief.bat" addon %ACTION%
echo.
pause
