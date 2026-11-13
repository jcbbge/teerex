#!/usr/bin/env python3
"""Local, opt-in cartridge lifecycle. Python 3.9+, standard library only."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
import tempfile
import time


class ContractError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def emit(value, stream=sys.stdout):
    print(json.dumps(dict(schema_version=1, **value), sort_keys=True), file=stream)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    regular(path)
    require(path.stat().st_size <= 1024 * 1024, "JSON exceeds 1 MiB")
    return json.loads(path.read_text(), object_pairs_hook=unique)


def digest(path):
    regular(path)
    require(path.stat().st_size <= 64 * 1024 * 1024, "payload exceeds 64 MiB")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,47}", value) is not None


def version(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?", value) is not None


def relative(value):
    require(isinstance(value, str) and value and "\\" not in value, "invalid package path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and str(p) == value and all(x not in (".", "..") for x in p.parts), "unsafe package path")
    return p


def regular(path):
    mode = path.lstat().st_mode
    require(stat.S_ISREG(mode) and path.stat().st_nlink == 1, "not a single regular file: " + str(path))


def directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), "not a user-owned directory: " + str(path))
    require(info.st_mode & 0o022 == 0, "directory writable by other users: " + str(path))


def safe_path(path, create=False):
    """Reject symlink ancestors, including dangling ones; never normalize away '..'."""
    require(path.is_absolute() and all(x not in (".", "..") for x in path.parts), "absolute canonical path required")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            if not create:
                continue
            current.mkdir(mode=0o700)
        require(not current.is_symlink() and current.is_dir(), "symlink or non-directory ancestor: " + str(current))
    return path


def host():
    pair = (platform.system(), platform.machine())
    require(pair in (("Darwin", "arm64"), ("Linux", "x86_64")), "supported hosts: Apple-silicon Mac and Linux x86_64")
    return "aarch64-macos" if pair[0] == "Darwin" else "x86_64-linux"


def manifest(value):
    keys = {"schema_version", "id", "version", "status", "kind", "platform", "entrypoint", "dependencies", "files", "provenance", "compatibility", "permissions", "data_policy"}
    require(isinstance(value, dict) and set(value) == keys and value["schema_version"] == 1, "unsupported manifest fields/schema")
    require(identifier(value["id"]) and version(value["version"]), "invalid cartridge ID/version")
    require(value["status"] in ("ready", "experimental") and value["kind"] in ("program", "script", "extension", "agent"), "invalid status/kind")
    require(value["platform"] in ("aarch64-macos", "x86_64-linux"), "invalid manifest platform")
    require(value["data_policy"] == "retain", "only retain data policy is supported")
    deps = value["dependencies"]
    require(isinstance(deps, dict) and all(identifier(k) and version(v) and k != value["id"] for k, v in deps.items()), "invalid exact dependencies")
    require(isinstance(value["permissions"], list) and all(isinstance(x, str) and x for x in value["permissions"]), "invalid permissions disclosure")
    require(isinstance(value["provenance"], dict) and isinstance(value["compatibility"], dict), "provenance and compatibility required")
    files = value["files"]
    require(isinstance(files, list) and 1 <= len(files) <= 128, "1..128 payload files required")
    paths = set()
    for item in files:
        require(isinstance(item, dict) and set(item) == {"path", "sha256", "executable"}, "invalid file record")
        p = str(relative(item["path"]))
        require(p != "manifest.json" and p not in paths, "duplicate or reserved payload path")
        require(isinstance(item["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "invalid SHA256")
        require(type(item["executable"]) is bool, "invalid executable flag")
        paths.add(p)
    require(not any(a != b and b.startswith(a + "/") for a in paths for b in paths), "file/directory collision")
    entry = value["entrypoint"]
    require(isinstance(entry, list) and entry and all(isinstance(x, str) and x and "\0" not in x for x in entry), "invalid argv entrypoint")
    require(entry[0] in paths and next(x["executable"] for x in files if x["path"] == entry[0]), "entrypoint must be executable payload")
    return value


def verify_package(path, expected_hash=None):
    safe_path(path)
    m = manifest(read_json(path / "manifest.json"))
    if expected_hash is not None:
        require(digest(path / "manifest.json") == expected_hash, "manifest identity changed")
    expected = {"manifest.json"} | {f["path"] for f in m["files"]}
    directories = {str(p) for name in expected for p in PurePosixPath(name).parents if str(p) != "."}
    actual = set()
    for parent, dirs, files in os.walk(path, followlinks=False):
        for name in dirs:
            p = Path(parent) / name
            require(not p.is_symlink() and str(p.relative_to(path)) in directories, "unexpected package directory")
        for name in files:
            p = Path(parent) / name
            regular(p)
            actual.add(str(p.relative_to(path)))
    require(actual == expected, "package contains missing or additional files")
    for item in m["files"]:
        p = path / item["path"]
        require(digest(p) == item["sha256"], "payload checksum mismatch: " + item["path"])
        require(bool(p.stat().st_mode & 0o111) == item["executable"], "payload executable mode changed")
    return m


def catalog(path):
    safe_path(path)
    index = read_json(path / "catalog.json")
    require(isinstance(index, dict) and set(index) == {"schema_version", "packages"} and index["schema_version"] == 1, "invalid catalog")
    require(isinstance(index["packages"], list) and len(index["packages"]) <= 128, "catalog limit exceeded")
    result = {}
    for entry in index["packages"]:
        require(isinstance(entry, dict) and set(entry) == {"path", "manifest_sha256"}, "invalid catalog entry")
        require(isinstance(entry["manifest_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", entry["manifest_sha256"]), "catalog requires a SHA256 manifest pin")
        p = path / str(relative(entry["path"]))
        m = verify_package(p, entry["manifest_sha256"])
        require(m["id"] not in result, "one version per ID per catalog")
        require(m["platform"] == host(), "catalog platform does not match host")
        result[m["id"]] = (m, p, entry["manifest_sha256"])
    return result


def closure(selected, packages):
    visiting, done = set(), []

    def visit(key):
        require(key in packages, "missing dependency: " + key)
        require(key not in visiting, "dependency cycle: " + key)
        if key in done:
            return
        visiting.add(key)
        for dep, pin in sorted(packages[key]["dependencies"].items()):
            require(dep in packages and packages[dep]["version"] == pin, "unsatisfied exact dependency: " + dep + "=" + pin)
            visit(dep)
        visiting.remove(key)
        done.append(key)

    for key in selected:
        visit(key)
    return done


@contextmanager
def lock(path):
    if os.path.lexists(path):
        regular(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        require(os.fstat(fd).st_uid == os.getuid(), "lock is not user-owned")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ContractError("in use or concurrent lifecycle operation: " + path.name)
        yield fd
    finally:
        os.close(fd)


class Store:
    def __init__(self, root, create=False):
        require(os.getuid() != 0, "run as your own user, not root/sudo")
        home = Path(os.environ["HOME"])
        safe_path(home)
        directory(home)
        require(root.is_absolute() and root != home and home in root.parents, "root must be strictly inside HOME")
        safe_path(root, create)
        self.root = root
        self.state = {"schema_version": 1, "active": {}, "installed": {}, "retired": {}}
        if root.exists():
            directory(root)
            marker = root / ".teerex-cartridges"
            if not marker.exists():
                require(create and not any(root.iterdir()), "refusing unmarked/nonempty cartridge root")
                marker.write_text("teerex-cartridges-v1\n")
                marker.chmod(0o600)
            regular(marker)
            require(marker.read_text() == "teerex-cartridges-v1\n", "wrong cartridge root marker")
        self.exists = root.exists()

    def load(self):
        path = self.root / "state.json"
        if path.exists() or path.is_symlink():
            self.state = read_json(path)
        s = self.state
        require(isinstance(s, dict) and set(s) == {"schema_version", "active", "installed", "retired"} and s["schema_version"] == 1, "invalid registry")
        require(all(isinstance(s[k], dict) for k in ("active", "installed", "retired")), "invalid registry maps")
        for records in (s["installed"], s["retired"]):
            for key, versions in records.items():
                require(identifier(key) and isinstance(versions, dict), "invalid installed ID")
                for v, sha in versions.items():
                    require(version(v) and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha), "invalid registry version/hash")
        for key, v in s["active"].items():
            require(key in s["installed"] and v in s["installed"][key], "active version not installed")

    def save(self):
        fd, name = tempfile.mkstemp(prefix=".state-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.state, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.root / "state.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def path(self, key, v, retired=False):
        return self.root / ("retired" if retired else "packages") / key / v

    def get(self, key, v):
        require(key in self.state["installed"] and v in self.state["installed"][key], "cartridge version is not installed")
        m = verify_package(self.path(key, v), self.state["installed"][key][v])
        require(m["id"] == key and m["version"] == v and m["platform"] == host(), "installed identity/platform mismatch")
        return m

    def active_manifests(self):
        return {key: self.get(key, v) for key, v in self.state["active"].items()}

    def lease_path(self, key, v):
        path = self.root / "leases" / key
        safe_path(path, True)
        return path / v

    def check_idle(self, keys):
        for key, v in keys:
            path = self.root / "leases" / key / v
            safe_path(path.parent)
            if os.path.lexists(path):
                with lock(path):
                    pass


def describe(store, m):
    return dict(id=m["id"], version=m["version"], status=m["status"], kind=m["kind"],
                dependencies=m["dependencies"], compatibility=m["compatibility"], provenance=m["provenance"],
                permissions=m["permissions"], code=str(store.path(m["id"], m["version"])),
                data=str(store.root / "data" / m["id"]), data_policy="retain")


def install(store, args):
    available = catalog(Path(args.catalog).absolute())
    require(bool(args.ids) != args.all, "choose explicit IDs or --all")
    selected = sorted(k for k, (m, _, _) in available.items() if m["status"] == "ready" or args.allow_experimental) if args.all else args.ids
    excluded = sorted(k for k, (m, _, _) in available.items() if args.all and not args.allow_experimental and m["status"] == "experimental")
    manifests = {k: value[0] for k, value in available.items()}
    ordered = closure(selected, manifests)
    require(args.allow_experimental or all(manifests[k]["status"] == "ready" for k in ordered), "experimental cartridge requires --allow-experimental")
    active = store.active_manifests()
    proposed = dict(active, **{k: manifests[k] for k in ordered})
    closure(sorted(proposed), proposed)
    changes = [(k, store.state["active"][k]) for k in ordered if k in store.state["active"] and store.state["active"][k] != manifests[k]["version"]]
    store.check_idle(changes) if store.exists else None
    for key in ordered:
        m, _, sha = available[key]
        v = m["version"]
        if v in store.state["installed"].get(key, {}):
            require(store.state["installed"][key][v] == sha, "installed version identity differs; no overwrite")
            store.get(key, v)
        else:
            require(not os.path.lexists(store.path(key, v)) and not os.path.lexists(store.path(key, v, True)), "unregistered or retired version exists; inspect or restore it")
    result = dict(ok=True, operation="install", applied=args.apply, selected=selected, excluded_experimental=excluded,
                  packages=[describe(store, manifests[k]) for k in ordered], active_before=store.state["active"].copy(),
                  atomic_activation=True, hooks_executed=False, undo="remove each new version with --deactivate --apply; activate retained prior versions explicitly")
    if args.apply:
        added = []
        try:
            for key in ordered:
                m, source, sha = available[key]
                v = m["version"]
                if v not in store.state["installed"].get(key, {}):
                    destination = store.path(key, v)
                    safe_path(destination.parent, True)
                    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=destination.parent))
                    try:
                        shutil.copytree(source, stage, dirs_exist_ok=True, symlinks=True)
                        verify_package(stage, sha)
                        for p in stage.rglob("*"):
                            p.chmod(0o700 if p.is_dir() or p.stat().st_mode & 0o111 else 0o600)
                        os.rename(stage, destination)
                        added.append(destination)
                    finally:
                        if stage.exists():
                            shutil.rmtree(stage)
                    store.state["installed"].setdefault(key, {})[v] = sha
                store.state["active"][key] = v
            store.save()
        except BaseException:
            for p in reversed(added):
                shutil.rmtree(p)
            raise
    return result


def change(store, args):
    key, v = args.id, args.version
    require(identifier(key) and version(v), "invalid ID/version")
    retired = args.command == "restore"
    if retired:
        source = store.path(key, v, True)
        require(v in store.state["retired"].get(key, {}), "version is not retired")
        m = verify_package(source, store.state["retired"][key][v])
        require(m["id"] == key and m["version"] == v and m["platform"] == host(), "retired identity/platform mismatch")
        require(v not in store.state["installed"].get(key, {}) and not os.path.lexists(store.path(key, v)), "version already installed or path occupied")
    else:
        m = store.get(key, v)
    active = store.active_manifests()
    if args.command == "activate":
        proposed = dict(active, **{key: m})
        closure(sorted(proposed), proposed)
        if key in active and active[key]["version"] != v:
            store.check_idle([(key, active[key]["version"])])
    elif args.command == "remove":
        require(store.state["active"].get(key) != v or args.deactivate, "active removal requires --deactivate")
        for dep in active.values():
            require(dep["dependencies"].get(key) != v, "active dependent blocks removal: " + dep["id"])
        store.check_idle([(key, v)])
        require(not os.path.lexists(store.path(key, v, True)), "retired destination occupied")
    result = dict(ok=True, operation=args.command, applied=args.apply, package=describe(store, m),
                  data_retained=True, restored_inactive=retired)
    if args.apply:
        if args.command == "activate":
            store.state["active"][key] = v
            store.save()
        else:
            destination = store.path(key, v, not retired)
            source = store.path(key, v, retired)
            safe_path(destination.parent, True)
            os.rename(source, destination)
            try:
                if retired:
                    store.state["installed"].setdefault(key, {})[v] = store.state["retired"][key].pop(v)
                    if not store.state["retired"][key]:
                        del store.state["retired"][key]
                else:
                    store.state["retired"].setdefault(key, {})[v] = store.state["installed"][key][v]
                    del store.state["installed"][key][v]
                    if not store.state["installed"][key]:
                        del store.state["installed"][key]
                    if store.state["active"].get(key) == v:
                        del store.state["active"][key]
                store.save()
            except BaseException:
                os.rename(destination, source)
                raise
    return result


@contextmanager
def existing_lock(path, exclusive=False):
    """Inspection never creates a lock; repair requires the stable inode."""
    regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid(), "unsafe recovery lock")
        require(info.st_mode & 0o022 == 0, "recovery lock is writable by other users")
        require((info.st_dev, info.st_ino) == (path.stat().st_dev, path.stat().st_ino), "recovery lock identity changed")
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ContractError("in use or concurrent lifecycle operation: " + path.name)
        yield
    finally:
        os.close(fd)


def recovery_command(store, *args):
    return ["teerex", "cartridges", "--root", str(store.root), *args]


def stages(store):
    packages = store.root / "packages"
    if not os.path.lexists(packages):
        return []
    safe_path(packages)
    return sorted(p for owner in packages.iterdir() if owner.is_dir() and not owner.is_symlink()
                  and identifier(owner.name) for p in owner.iterdir() if p.name.startswith(".stage-"))


def stage_identity(path, cutoff):
    """Only private, owned, unlinked trees; newest member determines age."""
    safe_path(path)
    directory(path.parent.parent)
    directory(path.parent)
    directory(path)
    info = path.stat()
    newest = info.st_mtime
    for parent, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            child = Path(parent) / name
            item = child.lstat()
            require(item.st_uid == os.getuid() and not child.is_symlink(), "stage contains foreign or linked paths")
            if child.is_dir():
                directory(child)
            else:
                regular(child)
            newest = max(newest, item.st_mtime)
    require(newest <= cutoff, "stage is newer than the age threshold")
    return info.st_dev, info.st_ino


def doctor(store):
    findings = []
    def finding(kind, path, detail, command=None):
        findings.append(dict(kind=kind, path=str(path), detail=detail,
                             next_command=command or recovery_command(store, "doctor")))
    valid = True
    try:
        store.load() if store.exists else None
    except (ContractError, OSError, ValueError) as error:
        valid = False
        finding("invalid_registry", store.root / "state.json", str(error) + "; retain evidence; no automatic registry repair")
    if store.exists:
        if not os.path.lexists(store.root / ".lock"):
            finding("missing_lifecycle_lock", store.root / ".lock", "No stable lock to coordinate inspection; repair is refused until normal lifecycle initialization")
        for stage in stages(store):
            finding("interrupted_stage", stage, "Review an explicit age/ownership/lock-checked repair plan",
                    recovery_command(store, "repair", "--plan"))
        for pending in sorted(store.root.glob(".state-*")):
            finding("pending_registry", pending, "Uncommitted registry bytes are never adopted or deleted; retain for manual review")
    if valid:
        for section in ("installed", "retired"):
            for key, versions in sorted(store.state[section].items()):
                for v, expected in sorted(versions.items()):
                    path = store.path(key, v, section == "retired")
                    try:
                        m = verify_package(path, expected)
                        require(m["id"] == key and m["version"] == v and m["platform"] == host(), "registered identity/platform mismatch")
                    except (ContractError, OSError, ValueError) as error:
                        finding("payload_mismatch", path, str(error) + "; preserve bytes and review; no safe automatic repair")
                    if section == "installed" and store.state["active"].get(key) != v:
                        finding("inactive_version", path, "Installed version is inactive; activation rechecks exact dependencies",
                                recovery_command(store, "activate", key, "--version", v, "--apply"))
        for section, folder in (("installed", "packages"), ("retired", "retired")):
            base = store.root / folder
            if base.exists():
                safe_path(base)
                for owner in sorted(base.iterdir()):
                    if owner.is_symlink() or not owner.is_dir() or not identifier(owner.name):
                        finding("unexpected_code_path", owner, "Unrecognized path; no automatic adoption or deletion")
                        continue
                    for path in sorted(owner.iterdir()):
                        if path.name.startswith(".stage-") and folder == "packages":
                            continue
                        if path.name not in store.state[section].get(owner.name, {}):
                            finding("unregistered_code", path, "Code has no committed registration; preserve for manual review")
        data = store.root / "data"
        if data.exists():
            safe_path(data)
            for path in sorted(data.iterdir()):
                if not any(store.path(path.name, v).is_dir() for v in store.state["installed"].get(path.name, {})):
                    finding("retained_data_without_code", path, "Data is retained and never purged; list retired versions for explicit restore",
                            recovery_command(store, "list"))
    return dict(ok=True, operation="doctor", applied=False, root=str(store.root), registry_valid=valid,
                findings=findings, automatic_repair=False, data_retained=True, observation_is_atomic=False)


def repair(store, args):
    require(shutil.rmtree.avoids_symlink_attacks, "safe descriptor-based stage removal is unavailable on this Python/platform")
    store.load()
    # A live managed invocation is never interpreted as abandoned work.
    leases = store.root / "leases"
    if os.path.lexists(leases):
        safe_path(leases)
        directory(leases)
        for owner in leases.iterdir():
            safe_path(owner)
            directory(owner)
            for lease in owner.iterdir():
                with existing_lock(lease, exclusive=True):
                    pass
    cutoff = time.time() - args.older_than_minutes * 60
    selected, skipped = [], []
    for path in stages(store):
        try:
            identity = stage_identity(path, cutoff)
        except (ContractError, OSError, ValueError) as error:
            skipped.append(dict(path=str(path), reason=str(error)))
            continue
        selected.append((path, identity))
    removed = []
    for path, identity in selected:
        if args.apply:
            require(stage_identity(path, cutoff) == identity, "stage identity changed since plan")
            shutil.rmtree(path)
            removed.append(str(path))
    return dict(ok=True, operation="repair", applied=args.apply, older_than_minutes=args.older_than_minutes,
                selected=[str(path) for path, _ in selected], removed=removed, skipped=skipped,
                data_retained=True, registry_changed=False, automatic_adoption=False, atomic=False,
                apply_command=recovery_command(store, "repair", "--apply", "--older-than-minutes", str(args.older_than_minutes)))


def main():
    parser = argparse.ArgumentParser(prog="teerex cartridges" if sys.argv[0] == "-c" else None, description=__doc__)
    parser.add_argument("--root", default=os.path.join(os.environ["HOME"], ".local/opt/teerex-cartridges"))
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("install", help="plan installation; --apply explicitly mutates")
    p.add_argument("ids", nargs="*")
    p.add_argument("--catalog", required=True)
    p.add_argument("--all", action="store_true")
    p.add_argument("--allow-experimental", action="store_true")
    p.add_argument("--apply", action="store_true")
    for name in ("activate", "remove", "restore"):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--version", required=True)
        p.add_argument("--apply", action="store_true")
        if name == "remove":
            p.add_argument("--deactivate", action="store_true")
    sub.add_parser("list")
    sub.add_parser("doctor", help="read-only root, registry, payload and retained-data findings; never repairs")
    p = sub.add_parser("repair", help="explicit cleanup of old owned staging directories only; never registry/code/data repair")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--older-than-minutes", type=int, default=30, help="minimum age of every stage member, default 30; must be positive")
    p = sub.add_parser("run", help="execute an active cartridge with cooperative dependency leases")
    p.add_argument("id")
    p.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    host()
    os.umask(0o077)
    root = Path(args.root)
    store = Store(root, create=args.command == "install" and args.apply)
    require(store.exists or args.command in ("install", "list", "doctor"), "cartridge root does not exist")
    if args.command in ("doctor", "repair"):
        from contextlib import nullcontext
        if args.command == "repair":
            require(args.older_than_minutes > 0, "repair age threshold must be positive")
            require(os.path.lexists(root / ".lock"), "repair requires an existing lifecycle lock; inspect with doctor")
        with existing_lock(root / ".lock", exclusive=args.command == "repair") if os.path.lexists(root / ".lock") else nullcontext():
            emit(doctor(store) if args.command == "doctor" else repair(store, args))
        return
    run_fds = []
    try:
        # Plans on an absent root are read-only. Existing-root plans take the
        # same short lifecycle mutex to avoid reading an incomplete transaction.
        from contextlib import nullcontext
        with lock(root / ".lock") if store.exists else nullcontext():
            store.load() if store.exists else None
            if args.command == "install":
                emit(install(store, args))
            elif args.command == "list":
                emit(dict(ok=True, operation="list", active=store.state["active"], installed=store.state["installed"], retired=store.state["retired"], data_policy="retain"))
            elif args.command == "run":
                active = store.active_manifests()
                require(args.id in active, "cartridge is not active")
                required = closure([args.id], active)
                # Hold shared leases across exec. Closing them, bypassing this
                # launcher, or detached work is outside the cooperative contract.
                for key in required:
                    path = store.lease_path(key, active[key]["version"])
                    if os.path.lexists(path):
                        regular(path)
                    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                    run_fds.append(fd)
                    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    os.set_inheritable(fd, True)
                m = active[args.id]
                data = safe_path(root / "data" / args.id, True)
                directory(data)
                executable = str(store.path(args.id, m["version"]) / m["entrypoint"][0])
                argv = [executable] + m["entrypoint"][1:] + (args.args[1:] if args.args[:1] == ["--"] else args.args)
            else:
                emit(change(store, args))
        if args.command == "run":
            env = dict(os.environ, TEEREX_CARTRIDGE_DATA=str(data),
                       TEEREX_CARTRIDGE_DEPENDENCIES=json.dumps({key: str(store.path(key, active[key]["version"])) for key in required if key != args.id}, sort_keys=True))
            os.execve(executable, argv, env)
    finally:
        for fd in run_fds:
            os.close(fd)


def next_step(message):
    for problem, step in (
        ("experimental cartridge requires", "Review the plan, then add --allow-experimental if experiments are intended."),
        ("choose explicit IDs or --all", "Pass explicit IDs or --all, but not both."),
        ("cartridge root does not exist", "Check HOME and --root, then install the cartridge first."),
        ("active removal requires", "Re-run with --deactivate to leave this ID inactive."),
        ("active dependent blocks removal", "Remove or switch the named dependent first."),
        ("in use or concurrent lifecycle operation", "Wait for the running cartridge or lifecycle operation to finish, then retry manually."),
        ("root must be strictly inside HOME", "Choose a canonical user-owned root strictly inside HOME."),
        ("symlink or non-directory ancestor", "Choose a canonical path without symlink or non-directory ancestors."),
        ("refusing unmarked/nonempty", "Choose an empty user-owned root inside HOME."),
        ("payload checksum mismatch", "Copy out any edits and inspect the installed payload before retrying."),
        ("package contains missing or additional files", "Copy out any edits and inspect the installed payload before retrying."),
        ("manifest identity changed", "Copy out any edits and inspect the installed manifest before retrying."),
        ("installed version identity differs", "Use a new version number for changed package bytes."),
        ("unregistered or retired version exists", "Restore the retired version or inspect the unregistered directory manually."),
    ):
        if problem in message:
            return step
    return None


def entry():
    try:
        if sys.version_info < (3, 9):
            emit(dict(ok=False, error="Python 3.9+ required, found %s.%s" % sys.version_info[:2],
                      next_step="Install Python 3.9+ on this machine and retry."), sys.stderr)
            sys.exit(1)
        main()
    except KeyboardInterrupt:
        emit(dict(ok=False, error="interrupted: run list and inspect the root for .stage-* directories before retrying",
                  next_step="Run list and inspect the root for .stage-* directories before retrying."), sys.stderr)
        sys.exit(130)
    except (ContractError, OSError, ValueError) as error:
        result = dict(ok=False, error=str(error))
        step = next_step(str(error))
        if step:
            result["next_step"] = step
        emit(result, sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    entry()
