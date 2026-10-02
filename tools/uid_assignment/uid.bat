@echo off
REM Window types and IDs.   uid.bat   or   uid.bat --port 19726 --dry-run   (uid.bat --help)
REM Without options: "In this project", in the only open solo project.
REM Python: the toolkit's (install.bat).
setlocal
set "TOOL_DIR=%~dp0."
set "TOOL_MODULE=uids.cli"
set "TOOL_PYTHON="
call "%~dp0..\..\core\run.cmd" %*
exit /b %ERRORLEVEL%
