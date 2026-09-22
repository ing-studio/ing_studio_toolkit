# Archicad button

Adds a **Relief from point cloud** button to Archicad 28's Tapir palette. The button runs the tool on the open
project.

## Install
1. Close Archicad.
2. Double-click `install.bat`. It downloads the free Tapir add-on and adds the button.
3. Start Archicad and open **Window › Palettes › Tapir**. If the button is missing, click **Reload scripts**.

To uninstall, run `install.bat remove`.

## Use
1. Open and **save** your project.
2. Click **Relief from point cloud**.
3. Pick the point cloud file(s), or choose **No** to use the survey cloud set in `config\project.json`.
4. The tool runs in its own window, so you can keep working.
5. When it finishes, a message appears. The result, `<project>_ReliefOnly.pln`, is in the `output` folder next to
   your project.

Teamwork projects are not supported. Save a solo copy of the project (`.pln`) and run the button there.
