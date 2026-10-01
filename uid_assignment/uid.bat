@echo off
REM Window IDs tool - terminal entry.   uid.bat   or   uid.bat --port 19726 --dry-run   (uid.bat --help)
REM Needs only Python 3.10+ (no packages): the py launcher, python on PATH, or the toolkit's pipeline_env.
setlocal
set "PYTHONIOENCODING=utf-8"
set "UID_RUN=import sys; sys.path.insert(0, sys.argv.pop(1)); from uids.cli import main; sys.exit(main())"
set "PY_ENV=%LOCALAPPDATA%\pipeline_env\.venv\Scripts\python.exe"
where py >nul 2>nul && goto launcher
where python >nul 2>nul && goto python
if exist "%PY_ENV%" goto env
echo No Python found: install Python 3.10+ from python.org (or run the relief tool's setup_env.ps1)
exit /b 1
:launcher
py -3 -c "%UID_RUN%" "%~dp0." %*
exit /b %ERRORLEVEL%
:python
python -c "%UID_RUN%" "%~dp0." %*
exit /b %ERRORLEVEL%
:env
"%PY_ENV%" -c "%UID_RUN%" "%~dp0." %*
exit /b %ERRORLEVEL%
