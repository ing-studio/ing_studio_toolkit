@echo off
REM Uninstalls the archicad_window_ids tool: takes the "Window IDs" button out of the Tapir palette.
REM Tapir and the toolkit's Python stay (the other tools use them); the toolkit's uninstall.bat removes everything.
setlocal
call "%~dp0uid.bat" addon remove
if not defined TOOLKIT_NO_PAUSE pause
