@echo off
REM Uninstalls the max_corona_materials tool. It installs nothing of its own (no add-on in 3ds Max), so there is
REM nothing to take away here; its cache can be deleted. The toolkit's Python stays (the other tools use it); the
REM toolkit's uninstall.bat removes everything.
setlocal
echo max_corona_materials adds nothing to 3ds Max: nothing to remove.
echo Its cache (safe to delete): %LOCALAPPDATA%\ing_studio_toolkit\max_corona_materials
if not defined TOOLKIT_NO_PAUSE pause
