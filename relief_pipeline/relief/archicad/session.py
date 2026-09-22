"""Finding, starting and connecting to the Archicad instance that has a given project open.

Several Archicad instances can run on one machine (each on its own port 19723-19744), including Teamwork projects
of other users. The pipeline only talks to the instance that has the project it needs open (found by its path), or
starts a separate Archicad 28 on that project. Other instances are never touched.
"""
import os
import subprocess
import time
from pathlib import Path

from ..util import log, same_path, tool
from .addon import is_tapir_registered, register_tapir
from .client import ARCHICAD_VERSION, PORTS, Archicad, ArchicadError, DialogWatch, SafetyStop, archicad_running


def _listening_ports(pid):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    ports = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[3] == "LISTENING" and parts[4] == str(pid):
            port = int(parts[1].rsplit(":", 1)[1])
            if port in PORTS:
                ports.add(port)
    return sorted(ports)


def _pid_of_port(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            return int(parts[4])
    return None


def scan_instances(host):
    """Running Archicad instances: port, version, Tapir availability, open project (only known with Tapir)."""
    found = []
    for port in PORTS:
        ac = Archicad(host, port)
        try:
            version = ac.api("API.GetProductInfo", timeout=10).get("version")
        except Exception:
            continue
        inst = {"client": ac, "port": port, "version": version, "tapir": False, "teamwork": None, "location": ""}
        try:
            inst["tapir"] = not ac.missing_tapir_commands(("GetProjectInfo",))
            if inst["tapir"]:
                inst["location"], inst["teamwork"] = ac.project_location()
        except Exception as ex:
            inst["error"] = str(ex)
        found.append(inst)
    return found


def _describe(inst):
    project = inst["location"] or ("unknown project (no Tapir)" if not inst["tapir"] else "untitled")
    return f"port {inst['port']}: Archicad {inst['version']}, {'Teamwork ' if inst['teamwork'] else ''}{project}"


_connections = {}


def find_instance(host, pln, instances=None):
    """The running Archicad instance that has `pln` open, or None."""
    for inst in instances if instances is not None else scan_instances(host):
        if inst["location"] and same_path(inst["location"], pln):
            return inst
    return None


def project_is_open(host, pln, tries=3, pause=15):
    """Whether a running Archicad has `pln` open - the question that decides whether the file may be replaced.

    An instance that is still opening a project, or is busy with user input, answers nothing at all, so as long as
    the lock file is there the scan is repeated. The lock file alone is not proof the other way round: Archicad
    leaves one behind when it is killed."""
    locked = Path(str(pln) + ".lck").exists()
    for i in range(tries if locked else 1):
        if find_instance(host, pln):
            return True
        if i + 1 < tries:
            log(f"archicad: {Path(pln).name} is locked but no instance answered - looking again ...")
            time.sleep(pause)
    return False


def forget_project(pln):
    """Drop the cached client of `pln` - what it is connected to no longer holds the file we are about to write."""
    _connections.pop(os.path.normcase(str(pln)), None)


def connect_project(job, pln):
    """Client (with safety stop) for the Archicad instance that has `pln` open; starts Archicad 28 on it if needed."""
    host = job.cfg["archicad"]["host"]
    key = os.path.normcase(str(pln))
    cached = _connections.get(key)
    if cached:
        cached.watch.check()
        try:
            if same_path(cached.project_location()[0], pln):
                return cached
        except SafetyStop:
            raise
        except Exception:
            forget_project(pln)

    instances = scan_instances(host)
    for inst in instances:
        log(f"archicad: found {_describe(inst)}")
    inst = find_instance(host, pln, instances)
    if inst is None and Path(str(pln) + ".lck").exists():
        inst = find_instance(host, pln) if project_is_open(host, pln) else None  # never open the same file twice
    if inst:
        if inst["teamwork"] or inst["version"] != ARCHICAD_VERSION:
            raise ArchicadError(f"{pln} is open in an unsupported instance ({_describe(inst)})")
        ac = Archicad(host, inst["port"], DialogWatch(_pid_of_port(inst["port"]), job.pln_dir))
        _check_tapir(ac)
        _connections[key] = ac
        return ac

    if not is_tapir_registered():
        register_tapir()
    exe = tool(job.cfg, "archicad_exe")
    log(f"archicad: starting {exe} on {pln} (answer library dialogs if asked; any other dialog stops the pipeline) ...")
    proc = subprocess.Popen([exe, str(pln)], close_fds=True)
    watch = DialogWatch(proc.pid, job.pln_dir)
    ac = _wait_for_project(host, pln, proc, watch)
    time.sleep(10)  # add-on version warnings appear shortly after the project is loaded
    watch.check()
    _check_tapir(ac)
    _connections[key] = ac
    return ac


def _wait_for_project(host, pln, proc, watch, seconds=3600):
    """The API client of the Archicad instance that has the project open.

    Not necessarily the process we started: Archicad often hands the project over to a second process, which is why
    every JSON port is tried and the open project path - unique, we just created that file - decides. Opening a
    project over a network share can take half an hour, and while Archicad is still starting its API answers with
    errors ('ongoing user input'), so anything but a safety stop is simply retried."""
    t_end = time.time() + seconds
    while time.time() < t_end:
        time.sleep(5)
        watch.check()
        if proc.poll() is not None and not _listening_ports(proc.pid) and not archicad_running():
            raise ArchicadError(f"Archicad exited (code {proc.returncode}) before the project was open")
        for port in PORTS:
            ac = Archicad(host, port, watch)
            try:
                if int(ac.api("API.GetProductInfo", timeout=10).get("version")) != ARCHICAD_VERSION:
                    continue  # other Archicad versions on this machine are never used
                if ac.missing_tapir_commands(("GetProjectInfo",)):
                    continue
                location, _ = ac.project_location()
            except SafetyStop:
                raise
            except Exception:
                continue  # still starting, busy, or an instance without Tapir: try again next round
            if same_path(location, pln):
                log(f"archicad: {Path(pln).name} open in the new instance (port {port})")
                return ac
    raise ArchicadError(f"Archicad started but the project was not open within {seconds // 60} min - if Tapir is "
                        "missing there, check Options > Add-On Manager and run again")


def _check_tapir(ac):
    missing = ac.missing_tapir_commands()
    if missing:
        raise ArchicadError(f"Tapir commands not available ({', '.join(missing)}). Close this Archicad, run "
                            "'relief.bat addon install' and run again.")
    log(f"archicad: Tapir {ac.tapir('GetAddOnVersion').get('version')} on port {ac.port}")



