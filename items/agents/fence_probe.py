"""One-shot, fail-closed fence checks. No Rex connection and no worker code before exec."""
import argparse
import errno
import fcntl
import ipaddress
import json
import os
import socket
import stat
import sys


def probe_require(condition, reason):
    if not condition:
        raise ValueError(reason)


def probe_absolute(value):
    probe_require(isinstance(value, str) and value.startswith("/") and "\0" not in value, "absolute_path_required")
    return value


def probe_identity(path):
    # Follow symlinks: exposing the host object via a symlink must not look like a safe copy.
    info = os.stat(path)
    return dict(st_dev=info.st_dev, st_ino=info.st_ino)


def probe_endpoint(value):
    probe_require(isinstance(value, str), "invalid_loopback_endpoint")
    if value.startswith("["):
        address, separator, port = value[1:].partition("]:")
    else:
        address, separator, port = value.partition(":")
    probe_require(separator and port.isascii() and port.isdecimal() and 1 <= int(port) <= 65535, "invalid_loopback_endpoint")
    address = ipaddress.ip_address(address)
    probe_require(address.is_loopback, "loopback_endpoint_required")
    return (socket.AF_INET6 if address.version == 6 else socket.AF_INET), str(address), int(port)


def probe_unique(pairs):
    value = {}
    for key, item in pairs:
        probe_require(key not in value, "duplicate_protect_field")
        value[key] = item
    return value


def probe_config(path, recording):
    fd = os.open(probe_absolute(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        probe_require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                      stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, "protect_file_requires_owned_regular_0600")
        raw = f.read(65537)
    probe_require(len(raw) <= 65536, "protect_file_over_64KiB")
    value = json.loads(raw, object_pairs_hook=probe_unique)
    fields = {"schema_version", "absent_paths", "closed_tcp", "require_pid_namespace", "require_new_session", "required_paths", "host_identities"}
    probe_require(isinstance(value, dict) and not set(value) - fields, "unknown_protect_field")
    probe_require(type(value.get("schema_version")) is int and value["schema_version"] == 1, "invalid_protect_schema")
    for key in ("absent_paths", "closed_tcp", "required_paths"):
        entries = value.setdefault(key, [])
        probe_require(isinstance(entries, list) and len(entries) <= 64 and all(isinstance(v, str) for v in entries), "invalid_or_oversized_protect_list")
        probe_require(len(set(entries)) == len(entries), "duplicate_protect_entry")
        for entry in entries:
            probe_endpoint(entry) if key == "closed_tcp" else probe_absolute(entry)
    for key in ("require_pid_namespace", "require_new_session"):
        probe_require(type(value.setdefault(key, False)) is bool, "invalid_protect_boolean")
    if not recording:
        identities = value.get("host_identities", {})
        probe_require(isinstance(identities, dict) and not set(identities) - {"absent_paths", "pid_namespace"}, "invalid_host_identities")
        paths = identities.get("absent_paths", {})
        probe_require(isinstance(paths, dict) and set(paths) == set(value["absent_paths"]), "record_host_identities_outside_fence_first")
        required = list(paths.values())
        if value["require_pid_namespace"]:
            probe_require("pid_namespace" in identities, "record_host_pid_namespace_outside_fence_first")
        if "pid_namespace" in identities:
            required.append(identities["pid_namespace"])
        for identity in required:
            probe_require(identity is None or isinstance(identity, dict) and set(identity) == {"st_dev", "st_ino"} and
                          type(identity["st_dev"]) is int and identity["st_dev"] >= 0 and
                          type(identity["st_ino"]) is int and identity["st_ino"] > 0, "invalid_host_identity")
        if value["require_pid_namespace"]:
            probe_require(identities["pid_namespace"] is not None, "host_pid_namespace_required")
    return value


def probe_checks(config):
    checks = []

    def add(check, target, passed, error=None, **facts):
        checks.append(dict(check=check, target=target, result="pass" if passed else "fail", errno=error, **facts))

    for path in config["absent_paths"]:
        baseline = config["host_identities"]["absent_paths"][path]
        try:
            identity = probe_identity(path)
            different = baseline is not None and identity != baseline
            add("absent_path", path, different, state="shadowed" if different else "violated" if baseline else "identity_unknown")
        except OSError as exc:
            add("absent_path", path, exc.errno in (errno.ENOENT, errno.EACCES), exc.errno, state="absent" if exc.errno == errno.ENOENT else "inaccessible")
    for endpoint in config["closed_tcp"]:
        family, address, port = probe_endpoint(endpoint)
        try:
            with socket.socket(family, socket.SOCK_STREAM) as connection:
                connection.settimeout(.5)
                connection.connect((address, port))
            add("closed_tcp", endpoint, False)
        except socket.timeout:
            add("closed_tcp", endpoint, True, errno.ETIMEDOUT)
        except OSError as exc:
            add("closed_tcp", endpoint, exc.errno in (errno.ECONNREFUSED, errno.ENETUNREACH), exc.errno)
    if config["require_pid_namespace"]:
        try:
            different = probe_identity("/proc/self/ns/pid") != config["host_identities"]["pid_namespace"]
            add("pid_namespace", "/proc/self/ns/pid", different)
        except OSError as exc:
            add("pid_namespace", "/proc/self/ns/pid", False, exc.errno)
    if config["require_new_session"]:
        try:
            descriptor = os.open("/dev/tty", os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            add("new_session", "/dev/tty", exc.errno == errno.ENXIO, exc.errno)
        else:
            os.close(descriptor)
            add("new_session", "/dev/tty", False)
    for path in config["required_paths"]:
        try:
            info = os.stat(path)
            if stat.S_ISSOCK(info.st_mode):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(.5)
                    connection.connect(path)  # No frame. Deliberately consumes one channel admission.
            add("required_path", path, True)
        except OSError as exc:
            add("required_path", path, False, exc.errno)
    return checks


def probe_evidence_fd(descriptor):
    # Standard streams are worker-visible, so they cannot be an evidence channel.
    probe_require(descriptor >= 3, "invalid_evidence_fd")
    info = os.fstat(descriptor)
    flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
    probe_require(stat.S_ISREG(info.st_mode) and (flags & os.O_ACCMODE) in (os.O_WRONLY, os.O_RDWR),
                  "invalid_evidence_fd")
    os.set_inheritable(descriptor, False)


def probe_publish(result, options):
    raw = json.dumps(result).encode() + b"\n"
    if options.evidence_fd is not None:
        # fdopen owns and closes the inherited descriptor, including on write failure.
        descriptor, options.evidence_fd = options.evidence_fd, None
        with os.fdopen(descriptor, "wb") as evidence:
            evidence.write(raw)
            evidence.flush()
            os.fsync(evidence.fileno())
    if not options.then:
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()


def probe_main():
    parser = argparse.ArgumentParser(prog="teerex agents fence-probe", description=(
        "Check caller-declared protected resources inside a fence; no Rex access or worker code. "
        "Record identities outside first; host dev/inode matches fail, absent/inaccessible paths or different copies pass. "
        "Linux PID namespace check compares the recorded host namespace, including with a fresh /proc mount. "
        "One-shot evidence, not monitoring or authentication against unfenced same-UID processes."))
    parser.add_argument("--protect-file", required=True, help="absolute owned regular0600 schema1 JSON, <=64KiB, <=64 entries/list")
    parser.add_argument("--record-identities", action="store_true", help="outside the fence: record current host path/PID namespace identities into --out")
    parser.add_argument("--out", help="recording only: NEW absolute output file, exclusive no-follow0600; mount it read-only inside fence")
    parser.add_argument("--evidence-fd", type=int, help="inherited writable regular file descriptor >=3; write full JSON, close before exec; caller keeps private0600 file outside fence")
    parser.add_argument("--then", action="store_true", help="only after all checks pass, exec literal argv in the same PID; silent stdout, path-free refusal stderr")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    o = parser.parse_args(sys.argv[3:])
    if o.record_identities and (o.out is None or o.then or o.argv) or not o.record_identities and o.out is not None:
        parser.error("--record-identities requires --out and forbids --then/argv; --out requires recording")
    if o.then != bool(o.argv) or o.argv and (o.argv[0] != "--" or len(o.argv) < 2 or not o.argv[1]):
        parser.error("exec requires --then -- and nonempty literal argv")
    result = dict(kind="fence_probe_result", schema_version=1, passed=False, checks=[], exec="not_started")
    if o.evidence_fd is not None:
        try:
            probe_evidence_fd(o.evidence_fd)
        except (OSError, ValueError, OverflowError):
            print("teerex agents fence-probe: refused: invalid_evidence_fd", file=sys.stderr)
            return 1
    code, reason = 0, None
    try:
        config = probe_config(o.protect_file, o.record_identities)
        if o.record_identities:
            identities = {}
            for path in config["absent_paths"]:
                try:
                    identities[path] = probe_identity(path)
                except FileNotFoundError:
                    identities[path] = None
            config["host_identities"] = dict(absent_paths=identities)
            if config["require_pid_namespace"]:
                config["host_identities"]["pid_namespace"] = probe_identity("/proc/self/ns/pid")
            raw = json.dumps(config, ensure_ascii=True).encode() + b"\n"
            probe_require(len(raw) <= 65536, "recorded_protect_file_over_64KiB")
            descriptor = os.open(probe_absolute(o.out), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            result.update(passed=True, recorded_protect_file=o.out)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        result["failure_reason"] = str(exc)
        code, reason = 3, "invalid_protect_file"
    if code == 0 and not o.record_identities:
        try:
            result["checks"] = probe_checks(config)
        except (OSError, ValueError, TypeError) as exc:
            result["failure_reason"] = str(exc)
            code, reason = 1, "check_failed"
        else:
            failed = next((check for check in result["checks"] if check["result"] == "fail"), None)
            result["passed"] = failed is None
            result["exec"] = "started" if o.then and result["passed"] else "not_started"
            if failed:
                code, reason = 1, failed["check"]
    try:
        probe_publish(result, o)
    except OSError:
        print("teerex agents fence-probe: refused: evidence_write_failed", file=sys.stderr)
        return 1
    if code:
        print("teerex agents fence-probe: refused: " + reason, file=sys.stderr)
        return code
    if o.then:
        try:
            os.execvp(o.argv[1], o.argv[1:])
        except OSError:
            print("teerex agents fence-probe: refused: exec_failed", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(probe_main())
