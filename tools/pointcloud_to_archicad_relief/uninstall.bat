@echo off
REM Uninstalls the relief tool: takes the "Relief from point cloud" button out of the Tapir palette.
REM Tapir and the toolkit's Python stay (the other tools use them); the toolkit's uninstall.bat removes everything.
setlocal
call "%~dp0relief.bat" addon remove
if not defined TOOLKIT_NO_PAUSE pause
