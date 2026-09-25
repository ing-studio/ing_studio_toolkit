"""Installing the Archicad add-on of this pipeline (see addon/README.md).

1. Tapir: the open-source Archicad add-on whose JSON commands the pipeline uses. The pinned release is downloaded
   from GitHub into %LOCALAPPDATA%\\Tapir\\Archicad <version> (the version in use, archicad.version) and checked
   against its SHA-256. Archicad keeps the user add-on list in
   HKCU\\Software\\GRAPHISOFT\\Archicad\\Archicad <version> ...\\Add-On Manager\\Include as
   "#1.", "#2.", ... = "lan.flat:///C:/path/addon.apx" plus "Include Number"; the .apx is appended to that list
   (other add-ons are kept; a backup of the list is written next to it). A running Archicad loads add-ons only at
   start, and may rewrite the list when it quits.
2. The palette button (addon/palette/*.py): Tapir lists every script in Documents\\Tapir\\custom-scripts in its
   palette and runs it with uv. The installed copy is told where this pipeline is.
"""
import hashlib
import os
import shutil
import urllib.request
import winreg
from pathlib import Path

from ..util import PIPELINE_DIR, log, save_json, warn
from .client import ArchicadError, archicad_running, version

ADDON_DIR = PIPELINE_DIR / "addon"
TAPIR_VERSION = "1.5.9"
TAPIR_SHA256 = {28: "4a38838bb311a0d5b31e7525c04bfa98bdacf6239e55d233694dc0e630822ee8",
                29: "858ca5cf52b3d115f546aae6600efa9680ee6cb87ed8e72fc905e02b5122156a"}
PALETTE_SOURCE = ADDON_DIR / "palette"
PALETTE_TARGET = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "Tapir" / "custom-scripts"
REGISTRY_ROOT = r"Software\GRAPHISOFT\Archicad"


def tapir_file():
    return f"TapirAddOn_AC{version()}_Win.apx"


def tapir_url():
    return f"https://github.com/ENZYME-APD/tapir-archicad-automation/releases/download/{TAPIR_VERSION}/{tapir_file()}"


def apx_target():
    """Where the Tapir of the Archicad version in use is kept."""
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Tapir" / f"Archicad {version()}" / tapir_file()


# --------------------------------------------------------------------------- registry
def _include_keys():
    keys = []
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
            if name.lower().startswith(f"archicad {version()}."):
                keys.append(rf"{REGISTRY_ROOT}\{name}\Add-On Manager\Include")
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


def is_tapir_registered():
    return apx_target().exists() and any(any("tapiraddon" in v.lower() for v in _read_entries(k)) for k in _include_keys())


# --------------------------------------------------------------------------- install / remove
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download_tapir():
    """The pinned Tapir release for the Archicad version in use (kept when it is already there and intact)."""
    target, url, sha = apx_target(), tapir_url(), TAPIR_SHA256[version()]
    if target.exists() and _sha256(target) == sha:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".download")
    log(f"addon: downloading Tapir {TAPIR_VERSION} from {url} ...")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if _sha256(tmp) != sha:
        tmp.unlink()
        raise ArchicadError(f"the downloaded Tapir does not match its checksum - not installed ({url})")
    tmp.replace(target)  # written by Python: carries no "downloaded from the internet" mark


def register_tapir(remove=False):
    """Tapir in the Add-On Manager list of every language version of the Archicad version in use."""
    keys = _include_keys()
    if not keys:
        raise ArchicadError(f"No Archicad {version()} settings in the registry - start and close Archicad once")
    entry = "lan.flat:///" + apx_target().as_posix()
    if not remove:
        download_tapir()
    backup = apx_target().parent.parent / f"addon_manager_backup_{os.environ.get('COMPUTERNAME', 'pc')}.json"
    for key in keys:
        before = _read_entries(key)
        kept = [v for v in before if "tapiraddon" not in v.lower()]
        wanted = kept if remove else kept + [entry]
        if wanted == before:
            continue  # already as wanted: the list is not rewritten
        if not backup.exists():
            save_json(backup, {"key": key, "entries": before})
        _write_entries(key, wanted)
    log(f"addon: Tapir {TAPIR_VERSION} {'removed from' if remove else 'registered in'} the Archicad "
        f"{version()} Add-On Manager ({apx_target()})")
    if archicad_running():
        warn("addon: Archicad is running; it loads add-ons only at start - restart it to use Tapir")


def install_palette(remove=False):
    """The palette button(s) into Documents\\Tapir\\custom-scripts, told where this pipeline is."""
    for src in sorted(PALETTE_SOURCE.glob("*.py")):
        dst = PALETTE_TARGET / src.name
        if remove:
            dst.unlink(missing_ok=True)
            log(f"addon: palette button removed: {dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8").replace("__PIPELINE_DIR__", str(PIPELINE_DIR)), encoding="utf-8")
        log(f"addon: palette button installed: {dst}  (Tapir palette > Reload scripts)")
    if not remove and not shutil.which("uv") and not (Path.home() / ".local" / "bin" / "uv.exe").exists():
        warn("addon: Tapir runs palette scripts with 'uv', which was not found; Tapir offers to install it on "
            "first use (https://docs.astral.sh/uv/)")


def install(remove=False, palette_only=False):
    if not palette_only:
        register_tapir(remove)
    install_palette(remove)


def status():
    return {"archicad_version": version(), "tapir_version": TAPIR_VERSION, "tapir_apx": str(apx_target()),
            "tapir_apx_intact": apx_target().exists() and _sha256(apx_target()) == TAPIR_SHA256[version()],
            "tapir_registered": is_tapir_registered(),
            "palette_buttons": [str(PALETTE_TARGET / p.name) for p in sorted(PALETTE_SOURCE.glob("*.py"))
                                if (PALETTE_TARGET / p.name).exists()]}
