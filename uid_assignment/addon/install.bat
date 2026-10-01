@echo off
REM Installs the Window IDs add-on: Tapir into Archicad 28 / 29 (if it is not there yet) and the "Window IDs"
REM button into the Tapir palette. Restart Archicad after a first install.   Remove the button:  install.bat remove
setlocal
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=install"
call "%~dp0..\uid.bat" addon %ACTION%
echo.
pause
