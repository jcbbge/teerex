"""Plan/apply installation of a prepared native Rex action fragment; no runtime injection."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

LIMIT = 262144


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("expected_owned_regular_file")
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("file_exceeds_262144_bytes")
        data.decode("utf-8")
        return data
    finally:
        os.close(fd)


def rex_call(base, args):
    # Disk-backed bounded retention avoids pipe deadlocks or unbounded in-memory capture.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(base + args, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            raise ValueError("rex_deadline_uncertain")
        out.seek(0)
        raw = out.read(LIMIT + 1)
        err.seek(0)
        diagnostic = err.read(4096).decode("utf-8", errors="replace")
        if len(raw) > LIMIT:
            raise ValueError("rex_evidence_exceeds_262144_bytes")
        if child.returncode:
            raise ValueError("rex_failed: " + diagnostic)
        return json.loads(raw)


def same_path(a, b):
    return isinstance(a, str) and isinstance(b, str) and os.path.realpath(a) == os.path.realpath(b)


def execute(args, result):
    for value in (args.init, args.file, args.socket, args.plan):
        if not os.path.isabs(value):
            raise ValueError("absolute_paths_required")
    if len({os.path.realpath(p) for p in (args.init, args.file, args.plan)}) != 3:
        raise ValueError("init_fragment_plan_must_be_distinct")
    init = read_regular(args.init)
    fragment = read_regular(args.file)
    matches = re.findall(rb"^-- teerex-surface-action:([a-z0-9_]{1,64})$", fragment, re.M)
    if not matches or len(matches)>128 or len(set(matches))!=len(matches):
        raise ValueError("not_a_prepared_surface_fragment")
    names = [name.decode("ascii") for name in matches]
    name = names[0]
    # Lua decimal escapes work for controls; JSON's \u form is not Lua syntax.
    quoted = '"' + ''.join('\\' + c if c in '\\"' else '\\%03d' % ord(c) if ord(c) < 32 or ord(c) == 127 else c for c in args.file) + '"'
    inclusion = "\n-- teerex surface palette: " + name + "\ndofile(" + quoted + ")\n"
    base = [os.environ.get("TEEREX_REX", "rex"), "--autostart=false", "--server", "unix://" + args.socket,
            "--timeout", "3s", "--color", "never"]
    keymap = rex_call(base, ["api", "call", "client.keymap", "{}"])
    config = keymap.get("config", {})
    if not same_path(config.get("path"), args.init) or not config.get("instance_id"):
        raise ValueError("init_is_not_selected_servers_observed_config")
    if any(a.get("name") in names for a in keymap.get("actions", [])):
        raise ValueError("action_name_already_registered")
    plan = {"schema_version": 1, "kind": "surface_palette_install_plan", "init": args.init,
            "file": args.file, "socket": args.socket, "name": name, "names": names,
            "init_sha256": digest(init), "fragment_sha256": digest(fragment),
            "server_instance_id": config["instance_id"], "config_hash": config.get("hash"),
            "append_exactly": inclusion, "reloads": 1,
            "registration_check": "fresh_client.keymap_action_name_kind_source_and_config_generation"}
    if not args.apply:
        encoded = (json.dumps(plan, indent=2, ensure_ascii=False) + "\n").encode()
        fd = os.open(args.plan, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        result.update(outcome="planned", plan=plan, plan_sha256=digest(encoded), config_updated=False)
        return 0
    encoded = read_regular(args.plan)
    if not re.fullmatch(r"[0-9a-f]{64}", args.apply) or digest(encoded) != args.apply:
        raise ValueError("plan_hash_changed")
    if json.loads(encoded) != plan:
        raise ValueError("plan_source_config_or_server_changed")
    # Preserve every existing byte and mode. Cooperating writers are excluded; this is not
    # an OS lease against another administrator writing without the advisory lock.
    fd = os.open(args.init, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("init_changed")
        current = os.read(fd, LIMIT + 1)
        if current != init or read_regular(args.file) != fragment or read_regular(args.plan) != encoded:
            raise ValueError("plan_source_or_init_changed")
        data = inclusion.encode("utf-8")
        result["config_updated"] = True  # a failed write may still append a prefix
        if os.write(fd, data) != len(data):
            raise ValueError("config_append_incomplete")
        os.fsync(fd)
    finally:
        os.close(fd)
    result["append_exactly"] = inclusion
    check = rex_call(base, ["config", "check", args.init, "--json"])
    if check.get("diagnostics"):
        result["diagnostics"] = check["diagnostics"]
        raise ValueError("config_check_diagnostics_no_reload")
    result["reload_attempted"] = True
    reload = rex_call(base, ["api", "call", "server.config_reload", "{}"])
    result["reload"] = reload
    if reload.get("diagnostics"):
        raise ValueError("config_reload_diagnostics")
    actual = rex_call(base, ["api", "call", "client.keymap", "{}"])
    observed = actual.get("config", {})
    actions = [next((a for a in actual.get("actions", []) if a.get("name") == name), None) for name in names]
    action = actions[0]
    result["observed_action"] = action
    result["observed_actions"] = actions
    result["observed_config"] = observed
    def action_verified(action):
        source = action.get("source", "").rsplit(":", 1)[0] if action else ""
        if source and not os.path.isabs(source):
            source = os.path.join(os.path.dirname(args.init), source)
        return action and action.get("kind") == "lua" and same_path(source, args.file)
    if not (same_path(observed.get("path"), args.init) and observed.get("instance_id") == config["instance_id"]
            and observed.get("generation") == reload.get("generation") and all(action_verified(a) for a in actions) and read_regular(args.file) == fragment):
        raise ValueError("registration_not_verified")
    result.update(outcome="registered_and_verified", registered_in_running_server=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("init", "file", "socket", "plan"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--apply", metavar="PLAN_SHA256", help="approve the exact previously printed plan hash")
    args = parser.parse_args()
    result = {"schema_version": 1, "kind": "surface_palette_install_result", "outcome": "refused",
              "registered_in_running_server": False, "config_updated": False, "reload_attempted": False,
              "automatic_rollback": False, "retry_safe": False}
    try:
        code = execute(args, result)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["failure_reason"] = str(error)
        result["outcome"] = "uncertain" if result["config_updated"] else "refused"
        code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
