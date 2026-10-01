"""Installing the Archicad add-on: Tapir and the "Window IDs" button in its palette.

1. Tapir, the open-source Archicad add-on whose commands the tool uses, for every Archicad version on this machine
   (28, 29). The pinned release is downloaded from GitHub into %LOCALAPPDATA%\\Tapir\\Archicad <version> and checked
   against its SHA-256, then added to Archicad's user add-on list (HKCU\\Software\\GRAPHISOFT\\Archicad\\
   Archicad <version> ...\\Add-On Manager\\Include: "#1.", "#2.", ... and "Include Number"); the other add-ons stay.
   A Tapir already in the list (from the relief tool, say) is left as it is. Archicad loads add-ons only at start.
2. The palette button (addon/palette/*.py): Tapir lists every script in Documents\\Tapir\\custom-scripts in its
   palette and runs it with uv, passing the port of the Archicad it was clicked in. The installed copy is told where
   this tool is.

`remove` takes the button away; Tapir stays (other tools use it).
"""
import hashlib
import json
import os
import shutil
import urllib.request
import winreg
from pathlib import Path

from .archicad import ArchicadError
from .util import TOOL_DIR, log, warn

PALETTE_SOURCE = TOOL_DIR / "addon" / "palette"
PALETTE_TARGET = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "Tapir" / "custom-scripts"
TAPIR_VERSION = "1.5.9"
TAPIR_SHA256 = {28: "4a38838bb311a0d5b31e7525c04bfa98bdacf6239e55d233694dc0e630822ee8",
                29: "858ca5cf52b3d115f546aae6600efa9680ee6cb87ed8e72fc905e02b5122156a"}
REGISTRY_ROOT = r"Software\GRAPHISOFT\Archicad"


def _include_keys():
    """{version: [Add-On Manager\\Include key of each language version]} of the Archicads Tapir exists for."""
    keys = {}
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_ROOT)
    except FileNotFoundError:
        return keys
    with root:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            parts = name.split()
            if len(parts) > 1 and parts[0].lower() == "archicad" and parts[1].split(".")[0].isdigit():
                v = int(parts[1].split(".")[0])
                if v in TAPIR_SHA256:
                    keys.setdefault(v, []).append(rf"{REGISTRY_ROOT}\{name}\Add-On Manager\Include")
    return keys


def _read_entries(key):
    entries = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if name.startswith("#"):
                    entries[int(name.strip("#."))] = value
    except FileNotFoundError:
        pass
    return [entries[n] for n in sorted(entries)]


def _write_entries(key, values):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_ALL_ACCESS) as k:
        old, i = [], 0
        while True:
            try:
                old.append(winreg.EnumValue(k, i)[0])
            except OSError:
                break
            i += 1
        for name in old:
            if name.startswith("#"):
                winreg.DeleteValue(k, name)
        for n, v in enumerate(values, 1):
            winreg.SetValueEx(k, f"#{n}.", 0, winreg.REG_SZ, v)
        winreg.SetValueEx(k, "Include Number", 0, winreg.REG_SZ, str(len(values)))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _download(version, target):
    """The pinned Tapir release for this Archicad version (kept when it is already there and intact)."""
    if target.exists() and _sha256(target) == TAPIR_SHA256[version]:
        return
    url = (f"https://github.com/ENZYME-APD/tapir-archicad-automation/releases/download/{TAPIR_VERSION}/"
           f"{target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".download")
    log(f"addon: downloading Tapir {TAPIR_VERSION} from {url} ...")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if _sha256(tmp) != TAPIR_SHA256[version]:
        tmp.unlink()
        raise ArchicadError(f"the downloaded Tapir does not match its checksum - not installed ({url})")
    tmp.replace(target)


def install_tapir():
    """Tapir in the add-on list of every Archicad version here that does not have it yet."""
    keys = _include_keys()
    if not keys:
        warn("addon: no Archicad 28 or 29 settings in the registry - start and close Archicad once, then install "
             "again")
        return
    for version, version_keys in sorted(keys.items()):
        target = Path(os.environ.get("LOCALAPPDATA", "")) / "Tapir" / f"Archicad {version}" / \
            f"TapirAddOn_AC{version}_Win.apx"
        todo = [k for k in version_keys if not any("tapiraddon" in v.lower() for v in _read_entries(k))]
        if not todo:
            log(f"addon: Tapir is in Archicad {version} already")
            continue
        _download(version, target)
        backup = target.parent.parent / "addon_manager_backup.json"
        for key in todo:
            before = _read_entries(key)
            if not backup.exists():
                backup.write_text(json.dumps({"key": key, "entries": before}, indent=1), encoding="utf-8")
            _write_entries(key, before + ["lan.flat:///" + target.as_posix()])
        log(f"addon: Tapir {TAPIR_VERSION} added to Archicad {version} ({target}) - restart Archicad to load it")


def install(remove=False):
    if not remove:
        install_tapir()
    for src in sorted(PALETTE_SOURCE.glob("*.py")):
        dst = PALETTE_TARGET / src.name
        if remove:
            dst.unlink(missing_ok=True)
            log(f"addon: palette button removed: {dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8").replace("__TOOL_DIR__", str(TOOL_DIR)), encoding="utf-8")
        log(f"addon: palette button installed: {dst}  (Tapir palette > Reload scripts)")
    if not remove and not shutil.which("uv") and not (Path.home() / ".local" / "bin" / "uv.exe").exists():
        warn("addon: Tapir runs palette scripts with 'uv', which was not found; Tapir offers to install it on first "
             "use (https://docs.astral.sh/uv/)")
