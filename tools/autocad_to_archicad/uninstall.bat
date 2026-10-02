@echo off
REM Uninstalls the autocad_to_archicad tool: takes the "Site model from AutoCAD" button out of the Tapir palette.
REM Tapir and the toolkit's Python stay (the other tools use them); the toolkit's uninstall.bat removes everything.
setlocal
call "%~dp0dwg2ac.bat" addon remove
if not defined TOOLKIT_NO_PAUSE pause
