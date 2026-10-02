"""The Archicad add-on of the toolkit: Tapir, and each tool's buttons in the Tapir palette.

1. Tapir: the open-source Archicad add-on whose JSON commands the tools use. The pinned release is downloaded from
   GitHub into %LOCALAPPDATA%\\Tapir\\Archicad <version> and checked against its SHA-256. Archicad keeps the user
   add-on list in HKCU\\Software\\GRAPHISOFT\\Archicad\\Archicad <version> ...\\Add-On Manager\\Include as
   "#1.", "#2.", ... = "lan.flat:///C:/path/addon.apx" plus "Include Number"; the .apx is appended to that list (the
   other add-ons stay; a backup of the list is written next to the .apx). A Tapir already in the list is left as it
   is, unless its file is gone. Archicad loads add-ons only at start, and may rewrite the list when it quits.
2. The palette buttons (a tool's addon\\*.py): Tapir lists every script in Documents\\Tapir\\custom-scripts in its
   palette and runs it with uv, passing the port of the Archicad it was clicked in. The installed copy is told where
   its tool is (__TOOL_DIR__ in the script).

Taking a tool's buttons away leaves Tapir: the other tools use it. remove_tapir() is for the toolkit's uninstall.
"""
import hashlib
import os
import shutil
import urllib.parse
import urllib.request
import winreg
from pathlib import Path

from ..util import log, save_json, warn
from .client import SUPPORTED_VERSIONS, ArchicadError, archicad_running

TAPIR_VERSION = "1.5.9"
TAPIR_SHA256 = {28: "4a38838bb311a0d5b31e7525c04bfa98bdacf6239e55d233694dc0e630822ee8",
                29: "858ca5cf52b3d115f546aae6600efa9680ee6cb87ed8e72fc905e02b5122156a"}
PALETTE_TARGET = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "Tapir" / "custom-scripts"
REGISTRY_ROOT = r"Software\GRAPHISOFT\Archicad"


def tapir_file(version):
    return f"TapirAddOn_AC{version}_Win.apx"


def tapir_url(version):
    return (f"https://github.com/ENZYME-APD/tapir-archicad-automation/releases/download/{TAPIR_VERSION}/"
            f"{tapir_file(version)}")


def apx_target(version):
    """Where the toolkit keeps the Tapir of an Archicad version."""
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Tapir" / f"Archicad {version}" / tapir_file(version)


# --------------------------------------------------------------------------- registry
def _include_keys():
    """{version: [Add-On Manager\\Include key of each language version]} of the supported Archicads used here."""
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
                if v in SUPPORTED_VERSIONS:
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


def entry_file(entry):
    """'lan.flat:///C:/Tapir/TapirAddOn_AC28_Win.apx' -> Path('C:/Tapir/TapirAddOn_AC28_Win.apx'), else None."""
    if not entry.lower().startswith("lan.flat:///"):
        return None
    return Path(urllib.parse.unquote(entry[len("lan.flat:///"):]))


def is_tapir(entry):
    return "tapiraddon" in entry.lower()


def is_live_tapir(entry):
    """A Tapir entry whose file is there (an entry of another form is trusted)."""
    if not is_tapir(entry):
        return False
    f = entry_file(entry)
    return f is None or f.exists()


def is_tapir_registered(version):
    return any(any(is_live_tapir(e) for e in _read_entries(k)) for k in _include_keys().get(version, []))


# --------------------------------------------------------------------------- Tapir
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download_tapir(version):
    """The pinned Tapir release for an Archicad version (kept when it is already there and intact)."""
    target, url, sha = apx_target(version), tapir_url(version), TAPIR_SHA256[version]
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


def register_tapir(versions=None):
    """Tapir in the add-on list of these Archicad versions (default: every supported one used on this machine)."""
    keys = _include_keys()
    asked = list(versions) if versions else sorted(keys)
    if not any(keys.get(v) for v in asked):
        text = (f"no Archicad {' or '.join(map(str, versions or SUPPORTED_VERSIONS))} settings in the registry - "
                "start and close Archicad once, then install again")
        if versions:
            raise ArchicadError(text)
        warn("addon: " + text)
        return
    added_any = False
    for v in asked:
        added = False
        for key in keys.get(v, []):
            before = _read_entries(key)
            if any(is_live_tapir(e) for e in before):
                continue
            download_tapir(v)
            backup = apx_target(v).parent.parent / f"addon_manager_backup_{os.environ.get('COMPUTERNAME', 'pc')}.json"
            if not backup.exists():
                save_json(backup, {"key": key, "entries": before})
            # a Tapir entry whose file is gone is replaced
            _write_entries(key, [e for e in before if not is_tapir(e)] + ["lan.flat:///" + apx_target(v).as_posix()])
            log(f"addon: Tapir {TAPIR_VERSION} added to Archicad {v} ({apx_target(v)})")
            added = added_any = True
        if not added and keys.get(v):
            log(f"addon: Tapir is in Archicad {v} already")
    if added_any and archicad_running():
        warn("addon: Archicad is running; it loads add-ons only at start - restart it to use Tapir")


def remove_tapir():
    """The toolkit's Tapir out of every Archicad's add-on list (a Tapir installed some other way stays)."""
    ours = {apx_target(v).as_posix().lower() for v in SUPPORTED_VERSIONS}
    for v, version_keys in sorted(_include_keys().items()):
        for key in version_keys:
            before = _read_entries(key)
            kept = [e for e in before if not (entry_file(e) and entry_file(e).as_posix().lower() in ours)]
            if kept != before:
                _write_entries(key, kept)
                log(f"addon: Tapir removed from Archicad {v}")


# --------------------------------------------------------------------------- palette buttons
def palette_sources(tool_dir):
    return sorted((Path(tool_dir) / "addon").glob("*.py"))


def install_palette(tool_dir, remove=False):
    """A tool's palette buttons into Documents\\Tapir\\custom-scripts, told where the tool is."""
    for src in palette_sources(tool_dir):
        dst = PALETTE_TARGET / src.name
        if remove:
            dst.unlink(missing_ok=True)
            log(f"addon: palette button removed: {dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8").replace("__TOOL_DIR__", str(Path(tool_dir).resolve())),
                       encoding="utf-8")
        log(f"addon: palette button installed: {dst}  (Tapir palette > Reload scripts)")
    if not remove and not shutil.which("uv") and not (Path.home() / ".local" / "bin" / "uv.exe").exists():
        warn("addon: Tapir runs palette scripts with 'uv', which was not found; Tapir offers to install it on "
             "first use (https://docs.astral.sh/uv/)")


def install(tool_dir, remove=False):
    """A tool's add-on: Tapir (if missing) and its palette buttons; remove = only its buttons go."""
    if not remove:
        register_tapir()
    install_palette(tool_dir, remove)


def status(tool_dir=None):
    keys = _include_keys()
    out = {"tapir_version": TAPIR_VERSION,
           "archicad": {v: {"tapir_registered": is_tapir_registered(v), "tapir_apx": str(apx_target(v)),
                            "tapir_apx_intact": apx_target(v).exists() and _sha256(apx_target(v)) == TAPIR_SHA256[v]}
                        for v in sorted(keys)}}
    if tool_dir:
        out["palette_buttons"] = {p.name: (PALETTE_TARGET / p.name).exists() for p in palette_sources(tool_dir)}
    return out
