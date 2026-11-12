#!/usr/bin/env python3
"""One-shot fleet install worker. JSON stdin/stdout; never a service or host resolver."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile

TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(path):
    if path.is_symlink():
        require(path.lstat().st_uid == os.getuid(), "launcher is not user-owned")
        return {"kind": "symlink", "target": os.readlink(path)}
    if not path.exists():
        return {"kind": "absent"}
    require(path.is_file(), "launcher must be a regular file or symlink: " + str(path))
    require(path.stat().st_uid == os.getuid(), "launcher is not user-owned")
    require(path.stat().st_size <= 64 * 1024 * 1024, "launcher file exceeds 64 MiB")
    return {"kind": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def inside_home(value, home):
    require(isinstance(value, str) and value and not any(ord(c) < 32 for c in value), "invalid installation path")
    path = Path(value)
    require(path.is_absolute() and str(path) == value and ".." not in path.parts and path != home and home in path.parents,
            "installation paths must be canonical and strictly inside expected HOME")
    for parent in [path] + list(path.parents):
        require(not parent.is_symlink(), "symlink in installation path: " + str(parent))
        if parent.exists():
            info = parent.stat()
            require(stat.S_ISDIR(info.st_mode), "not a directory: " + str(parent))
            if parent == home or home in parent.parents:
                require(info.st_uid == os.getuid() and not info.st_mode & 0o022,
                        "installation directory must be owned and not group/world-writable: " + str(parent))
        if parent == home:
            break
    return path


def identity(host):
    actual = {"hostname": platform.node(), "user": pwd.getpwuid(os.getuid()).pw_name,
              "home": os.environ.get("HOME"), "platform": {
                  ("Darwin", "arm64"): "macos-arm64", ("Linux", "x86_64"): "linux-x86_64"
              }.get((platform.system(), platform.machine()), "unsupported")}
    require(os.getuid() != 0, "run as the target user, not root")
    require(actual["platform"] != "unsupported", "supported targets are Darwin arm64 and Linux x86_64")
    expected = {"home": host["home"], "platform": host["platform"]}
    install = host.get("install", {})
    if install.get("expected_hostname"):
        expected["hostname"] = install["expected_hostname"]
    if install.get("expected_user"):
        expected["user"] = install["expected_user"]
    if host["transport"] == "ssh":
        ssh_user = host["address"].split("@", 1)[0]
        require(not install.get("expected_user") or install["expected_user"] == ssh_user,
                "install.expected_user conflicts with configured SSH user")
        expected["user"] = ssh_user
    require(all(actual[k] == v for k, v in expected.items()),
            "host identity mismatch: expected " + json.dumps(expected) + "; observed " + json.dumps(actual))
    home = Path(actual["home"])
    require(home.is_absolute() and home.resolve() == home and home.is_dir(), "HOME must be canonical")
    return {"declared_host_id": host["host_id"], "observed": actual,
            "host_id_independently_verified": False}


def installer_bytes(request):
    code = base64.b64decode(request["installer"], validate=True)
    require(hashlib.sha256(code).hexdigest() == request["installer_sha256"], "installer transport checksum mismatch")
    return code


def core_read(request, command, root, version=None):
    with tempfile.TemporaryDirectory(prefix="teerex-fleet-inspect-") as temporary:
        installer = Path(temporary) / "teerex-install"
        installer.write_bytes(installer_bytes(request))
        argv = ["/bin/bash", str(installer), command, "--prefix", str(root)]
        if version:
            argv += ["--version", version]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        try:
            receipt = json.loads(result.stdout)
        except ValueError:
            raise ValueError("requires alpha.5 core installer inspect/verify JSON API: " + result.stderr[-2048:])
        require(result.returncode == 0 and receipt.get("ok") is True and receipt.get("schema_version") == 1,
                "core " + command + " refused: " + json.dumps(receipt))
        return receipt


def inspect(request):
    host = request["host"]
    actual = identity(host)
    version = request["version"]
    require(isinstance(version, str) and TAG.fullmatch(version), "explicit release tag required")
    home = Path(host["home"])
    root = inside_home(host.get("install", {}).get("prefix") or str(home / ".local/opt/teerex-managed"), home)
    state = core_read(request, "inspect", root)
    require(state["state"] != "unmanaged", "unmanaged installation root; choose a different install.prefix; manual folder left untouched")
    require(state["state"] in ("absent", "managed") and not state["busy"], "managed core installer is busy or invalid")
    active = state["active_version"]
    installed = state["installed_versions"]
    executable = root / "current/teerex"
    launcher = None
    launcher_before = None
    launcher_action = "none"
    launcher_backup = None
    if request.get("path_consent"):
        launcher = Path(host["teerex"])
        bindir = inside_home(str(launcher.parent), home)
        if host.get("install", {}).get("bin_dir"):
            require(str(bindir) == host["install"]["bin_dir"], "install.bin_dir must match configured teerex launcher parent")
        require(launcher.name == "teerex", "configured launcher must be named teerex")
        require(str(bindir) in os.environ.get("PATH", "").split(os.pathsep),
                "launcher directory is not on transport PATH; configure PATH explicitly yourself, then retry; profiles are never edited")
        launcher_before = fingerprint(launcher)
        if launcher_before == {"kind": "symlink", "target": str(executable)}:
            launcher_action = "retain"
        elif launcher_before["kind"] == "absent":
            launcher_action = "create"
        else:
            require(request.get("replace_launcher"), "existing manual launcher; use --replace-launcher with --path after reviewing its identity; it will be retained as a backup")
            launcher_action = "backup-and-replace"
            suffix = hashlib.sha256(json.dumps(launcher_before, sort_keys=True).encode()).hexdigest()[:16]
            launcher_backup = str(launcher.with_name("teerex.before-fleet-" + suffix))
            require(not os.path.lexists(launcher_backup), "retained launcher backup already exists; inspect it before retrying: " + launcher_backup)
    else:
        require(not request.get("replace_launcher"), "--replace-launcher requires --path consent")
    operation = request.get("operation", "install")
    require(operation in ("install", "rollback"), "unsupported operation")
    if operation == "rollback":
        require(version in installed, "rollback requires a retained managed release")
        action = "rollback"
    elif active == version:
        action = "verify"
    elif version in installed:
        action = "rollback"
    else:
        action = "upgrade" if active else "install"
    active_identity = core_read(request, "verify", root, active) if active else None
    selected_identity = core_read(request, "verify", root, version) if version in installed else None
    archive_platform = {"macos-arm64": "aarch64-macos", "linux-x86_64": "x86_64-linux"}[host["platform"]]
    return {"identity": actual, "prefix": str(root), "active_before": active, "installed": installed,
            "version": version, "action": action, "asset": "teerex-" + version + "-" + archive_platform + ".tar.gz",
            "active_identity": active_identity, "selected_identity": selected_identity,
            "launcher": str(launcher) if launcher else None, "launcher_before": launcher_before,
            "launcher_action": launcher_action, "launcher_backup": launcher_backup, "path_scope": "transport environment only",
            "path_selected_before": shutil.which("teerex"), "executable": str(executable),
            "undo": {"retained_version": active, "first_install": active is None,
                     "manual_folders": "untouched", "profiles": "untouched"}}


def run_installer(installer, action, plan, source=None):
    argv = ["/bin/bash", str(installer), action, "--prefix", plan["prefix"], "--version", plan["version"]]
    if source:
        argv += ["--from", str(source)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    require(result.returncode == 0, "core installer failed: " + result.stdout[-8192:] + result.stderr[-8192:])
    return {"stdout": result.stdout[-8192:], "stderr": result.stderr[-8192:]}


def check_version(executable, version):
    result = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=10)
    expected = "teerex " + version[1:]
    require(result.returncode == 0 and result.stdout.strip() == expected,
            "version verification failed: expected " + expected + "; stdout=" + result.stdout[:512] + "; stderr=" + result.stderr[:512])
    return result.stdout.strip()


def apply(request):
    plan = inspect(request)
    require(plan == request["plan"], "host installation/PATH state changed since plan; re-plan before applying")
    home = Path(request["host"]["home"])
    # One fleet mutex per HOME also serializes launchers shared by different roots.
    lock = home / ".teerex-fleet-install.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        raise ValueError("fleet lock exists; inspect running installers before manually removing " + str(lock))
    backup = None
    launcher_changed = False
    installer_log = None
    try:
        require(inspect(request) == plan, "installation changed while acquiring fleet lock")
        with tempfile.TemporaryDirectory(prefix="teerex-fleet-") as temporary:
            temporary = Path(temporary)
            installer = temporary / "teerex-install"
            installer.write_bytes(installer_bytes(request))
            if plan["action"] in ("install", "upgrade"):
                for name in (plan["asset"], "SHA256SUMS"):
                    (temporary / name).write_bytes(base64.b64decode(request["assets"][name], validate=True))
            try:
                if plan["action"] != "verify":
                    installer_log = run_installer(installer, plan["action"], plan,
                                                  temporary if plan["action"] in ("install", "upgrade") else None)
                verified = core_read(request, "verify", plan["prefix"], plan["version"])
                version_output = check_version(verified["executable"], plan["version"])
                require(core_read(request, "verify", plan["prefix"], plan["version"]) == verified,
                        "installed bytes changed while verifying version")
                if plan["launcher"]:
                    launcher = Path(plan["launcher"])
                    inside_home(str(launcher.parent), home)
                    require(fingerprint(launcher) == plan["launcher_before"], "launcher changed since plan")
                    launcher.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if plan["launcher_action"] == "backup-and-replace":
                        backup = Path(plan["launcher_backup"])
                        require(not os.path.lexists(backup), "backup collision")
                        launcher.rename(backup)
                    if plan["launcher_action"] in ("create", "backup-and-replace"):
                        launcher.symlink_to(plan["executable"])
                        launcher_changed = True
                    require(shutil.which("teerex") == str(launcher),
                            "another teerex shadows the consented launcher on transport PATH")
                    check_version(launcher, plan["version"])
                final_state = core_read(request, "inspect", plan["prefix"])
                require(final_state["active_version"] == plan["version"], "active version changed during verification")
            except Exception as failure:
                undo = {"ok": True}
                try:
                    if launcher_changed:
                        launcher = Path(plan["launcher"])
                        require(launcher.is_symlink() and os.readlink(launcher) == plan["executable"], "launcher changed; refusing rollback overwrite")
                        launcher.unlink()
                    if backup:
                        require(not os.path.lexists(plan["launcher"]), "launcher appeared; backup retained")
                        backup.rename(plan["launcher"])
                    state = core_read(request, "inspect", plan["prefix"])
                    if state["active_version"] != plan["active_before"]:
                        require(state["active_version"] == plan["version"], "active version changed externally; refusing rollback")
                        previous = dict(plan, version=plan["active_before"] or plan["version"])
                        if plan["active_before"]:
                            run_installer(installer, "rollback", previous)
                        else:
                            result = subprocess.run(["/bin/bash", str(installer), "remove", "--prefix", plan["prefix"],
                                                     "--version", plan["version"], "--deactivate"], capture_output=True, text=True, timeout=180)
                            require(result.returncode == 0, result.stdout + result.stderr)
                    undo["active_version"] = core_read(request, "inspect", plan["prefix"])["active_version"]
                    require(undo["active_version"] == plan["active_before"], "previous activation was not restored")
                except Exception as rollback_error:
                    undo = {"ok": False, "error": str(rollback_error), "backup": str(backup) if backup else None}
                return {"ok": False, "plan": plan, "error": str(failure), "rollback": undo,
                        "installer_log": installer_log}
        return {"ok": True, "plan": plan, "verified_version": version_output, "verified_installation": verified,
                "launcher_backup": str(backup) if backup else None, "installer_log": installer_log}
    finally:
        lock.rmdir()


def main():
    os.umask(0o077)
    try:
        request = json.load(sys.stdin)
        if request["phase"] == "plan":
            value = {"ok": True, "plan": inspect(request)}
        else:
            require(request["phase"] == "apply", "invalid phase")
            value = apply(request)
        print(json.dumps(value, sort_keys=True))
        return 0 if value["ok"] else 1
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
