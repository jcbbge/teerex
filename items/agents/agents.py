"""Visible agent lifecycle. Python 3.9+ stdlib; embedded by the native CLI.

Only the in-pane supervisor waits for an agent. No daemon, screen-based ACK,
implicit endpoint, hidden fallback, creation retry or notification retry exists.
"""
import argparse
import base64
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time

LIMIT = 262144
RUNTIME = sys.argv[1] if __name__ == "__main__" else None


class Refusal(Exception):
    pass


class Cancelled(BaseException):
    pass


def terminate(sig, unused):
    raise Cancelled(sig)


def require(test, reason):
    if not test:
        raise Refusal(reason)


def now():
    return int(time.time() * 1000)


def text(value, maximum=128):
    require(isinstance(value, str) and 0 < len(value.encode()) <= maximum and
            all(ord(c) >= 32 and ord(c) != 127 for c in value), "invalid_text")
    return value


def address_id(value, kind):
    require(isinstance(value, str) and re.fullmatch(kind + r":[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value),
            "canonical_full_address_required")
    return value


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute() and "\0" not in value, "absolute_path_required")
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{32}", value), "invalid_launch_id")
    return value


def message(raw):
    value = raw.decode("utf-8")
    require(0 < len(raw) <= 32768 and all(ord(c) >= 32 or c in "\n\t" for c in value) and "\x7f" not in value,
            "invalid_or_oversized_message")
    return value


def read_file(path, limit=LIMIT, private=False):
    fd = os.open(absolute(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        s = os.fstat(f.fileno())
        require(stat.S_ISREG(s.st_mode), "regular_file_required")
        if private:
            require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o600 and s.st_nlink == 1,
                    "private_owned_file_required")
        data = f.read(limit + 1)
    require(len(data) <= limit, "file_too_large")
    return data


class Registry:
    """Stable advisory lock and per-launch durable intent, on a trusted local filesystem."""
    def __init__(self, root):
        self.root = absolute(root)

    def __enter__(self):
        import fcntl
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            s = os.fstat(self.fd)
            require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, "private_owned_registry_required")
            self.lock = os.open("agents.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                0o600, dir_fd=self.fd)
            s = os.fstat(self.lock)
            require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and
                    stat.S_IMODE(s.st_mode) == 0o600 and s.st_nlink == 1, "private_owned_lock_required")
            end = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic() < end, "registry_busy_after_2s_lock_wait")
                    time.sleep(.005)
        except BaseException:
            if hasattr(self, "lock"):
                os.close(self.lock)
            os.close(self.fd)
            raise
        return self

    def __exit__(self, *unused):
        os.close(self.lock)
        os.close(self.fd)

    def name(self, launch_id):
        return "agents-" + identifier(launch_id) + ".json"

    def read(self, launch_id):
        data = read_file(str(Path(self.root) / self.name(launch_id)), private=True)
        state = json.loads(data)
        require(state["schema_version"] == 1 and state["launch_id"] == launch_id, "invalid_lifecycle_record")
        return state

    def save(self, state, new=False):
        name = self.name(state["launch_id"])
        if new:
            require(len([n for n in os.listdir(self.fd) if re.fullmatch(r"agents-[0-9a-f]{32}\.json", n)]) < 32,
                    "registry_full")
            require(not os.path.lexists(str(Path(self.root) / name)), "launch_already_exists")
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True).encode()
        require(len(raw) <= LIMIT, "record_too_large")
        stage = name + ".next"
        fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        renamed = False
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.rename(stage, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            renamed = True
            os.fsync(self.fd)
        finally:
            if not renamed:
                os.unlink(stage, dir_fd=self.fd)

    def write_message(self, launch_id, suffix, value):
        name = "agents-" + identifier(launch_id) + "-" + suffix + ".txt"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        with os.fdopen(fd, "wb") as f:
            f.write(value.encode())
            f.flush()
            os.fsync(f.fileno())
        os.fsync(self.fd)
        return str(Path(self.root) / name)


def update(root, launch_id, change):
    with Registry(root) as registry:
        state = registry.read(launch_id)
        change(state)
        registry.save(state)
        return state


def load(root, launch_id):
    with Registry(root) as registry:
        return registry.read(launch_id)


def receipt(state, outcome, **extra):
    # Tokens, full argv, briefs and reports stay private; state files are the recovery interface.
    result = {k: state.get(k) for k in ("launch_id", "name", "owner", "purpose", "review_at", "profile", "target",
                                        "starter", "report_to", "phase", "tracked", "protocol_acknowledged",
                                        "brief_attempted", "brief_outcome", "immediate_child_term", "remote_child_term", "notifications")}
    result["execution_host"] = state.get("execution", {}).get("host") if state.get("execution") else None
    result["immediate_child_role"] = "ssh_transport" if state.get("execution") else "agent_program"
    result.update(schema_version=1, kind="agents_result", outcome=outcome, agent_readiness="not_assessed",
                  task_completion="not_assessed", all_processes_verified_gone=False, exclusive_input_lease=False,
                  retry_safe=False, **extra)
    return result


def invoke(arguments, timeout=10, client_path=None, rex_executable=None, input_bytes=None):
    """Bounded foreground client, never the agent. Retain diagnostics without treating exit as ACK."""
    import tempfile
    # Output sinks are private regular files, not pipes that a failed descendant can hold open.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as source:
        environment = dict(os.environ)
        if client_path is not None:
            environment["PATH"] = client_path
        if rex_executable is not None:
            environment["TEEREX_INTERNAL_REX"] = absolute(rex_executable)
        if input_bytes is not None:
            require(len(input_bytes) <= 32768, "callback_input_too_large")
            source.write(input_bytes)
            source.seek(0)
        p = subprocess.Popen([RUNTIME, *arguments], stdin=source if input_bytes is not None else subprocess.DEVNULL, stdout=out, stderr=err,
                             start_new_session=True, env=environment)
        try:
            code = p.wait(timeout=timeout)
        except BaseException:
            # The native client supervises its own Rex process group. Give it time to perform
            # its bounded cleanup instead of SIGKILLing the controller and orphaning that group.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            raise
        out.seek(0)
        raw = out.read(LIMIT + 1)
        require(len(raw) <= LIMIT, "child_receipt_too_large")
        err.seek(0)
        diagnostics = err.read(4096)
        if diagnostics:
            sys.stderr.buffer.write(diagnostics)
            sys.stderr.buffer.flush()
    try:
        packet = json.loads(raw)
    except (ValueError, UnicodeError):
        packet = None
    return code, packet


def succeeded(code, packet, *outcomes):
    return code == 0 and isinstance(packet, dict) and packet.get("outcome") in outcomes


def send(root, state, destination, body, label):
    with Registry(root) as registry:
        path = registry.write_message(state["launch_id"], label, body)
    return invoke(["send", "--socket", state["socket"], "--session", destination["session_id"],
                   "--block", destination["block_id"], "--from", state["name"], "--message-file", path, *send_options(state)],
                  client_path=state["client_path"], rex_executable=state["rex_executable"])


def transport_ack(code, packet):
    return succeeded(code, packet, "events_acknowledged", "recorded")


def send_options(state):
    # Root send routes registered seats before terminal input; a failed store never falls back to paste.
    return ["--store", absolute(state["store"]), "--host", state["target"]["host"]] if state["store"] else []


def execution_config(profile):
    execution, callbacks = profile.get("execution"), profile.get("callbacks")
    if execution is None:
        require(callbacks is None, "callbacks_require_execution")
        return None, None
    require(isinstance(execution, dict) and set(execution) == {"config", "host", "cwd"}, "invalid_execution_config")
    require(isinstance(callbacks, dict) and set(callbacks) == {"config", "host"}, "explicit_compute_callbacks_required")
    for route in (execution, callbacks):
        absolute(route["config"])
        require(isinstance(route["host"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", route["host"]),
                "invalid_configured_route")
    absolute(execution["cwd"])
    code, packet = invoke(["targets", "resolve", "--config", execution["config"], "--host", execution["host"]])
    require(code == 0 and isinstance(packet, dict) and isinstance(packet.get("host"), dict), "compute_route_resolution_failed")
    require(packet["host"].get("transport") == "ssh", "execution_requires_distinct_ssh_compute_host")
    # Callback paths belong to compute; they must not be opened on the pane host.
    return dict(execution), dict(callbacks)


def callback_command(callbacks, arguments):
    return [RUNTIME, "--config", callbacks["config"], "--host", callbacks["host"], "agents", *arguments]


def remote_exec(o):
    # Trusted operator argv, not a channel method. All SSH serialization belongs to targets exec.
    require(len(o.payload) <= 98304, "compute_payload_too_large")
    payload = json.loads(base64.b64decode(o.payload, validate=True))
    require(isinstance(payload, dict) and set(payload) == {"argv", "cwd", "metadata", "protocol", "registry", "launch_id",
                                                          "token", "callbacks", "hook_events", "pane", "store"}, "invalid_compute_payload")
    argv = payload["argv"]
    require(isinstance(argv, list) and argv and all(isinstance(v, str) and "\0" not in v for v in argv), "invalid_compute_argv")
    absolute(argv[0])
    absolute(payload["cwd"])
    identifier(payload["launch_id"])
    token = text(payload["token"], 64)
    require(re.fullmatch(r"[0-9a-f]{64}", token), "invalid_compute_token")
    metadata = payload["metadata"]
    require(isinstance(metadata, dict) and set(metadata) == {"AGENT_SESSION", "AGENT_PANE", "REX_SESSION", "REX_BLOCK",
                                                           "AGENT_NAME", "AGENT_STARTER", "AGENT_REPORT_TO", "AGENT_LAUNCH_ID",
                                                           "AGENT_REGISTRY"}, "invalid_compute_metadata")
    require(all(isinstance(v, str) and "\0" not in v for v in metadata.values()), "invalid_compute_metadata")
    require(metadata["AGENT_LAUNCH_ID"] == payload["launch_id"], "compute_launch_mismatch")
    sid, bid = address_id(metadata["AGENT_SESSION"], "session"), address_id(metadata["AGENT_PANE"], "block")
    require(metadata["REX_SESSION"] == sid and metadata["REX_BLOCK"] == bid, "compute_address_mismatch")
    callbacks = payload["callbacks"]
    require(isinstance(callbacks, dict) and set(callbacks) == {"config", "host"}, "invalid_compute_callbacks")
    absolute(callbacks["config"])
    absolute(payload["registry"])
    # Resolve on THIS host before starting any program: path identity is never assumed across SSH.
    code, resolved = invoke(["targets", "resolve", "--config", callbacks["config"], "--host", callbacks["host"]])
    require(code == 0 and isinstance(resolved, dict) and isinstance(resolved.get("host"), dict), "callback_route_resolution_failed")
    pane = payload["pane"]
    require(isinstance(pane, dict) and pane == dict(host=resolved["host"]["host_id"], server="unix://" + resolved["host"]["socket"],
                                                   session_id=sid, block_id=bid), "callback_must_route_to_pane_registry_host")
    ack_args = ["ack", "--registry", payload["registry"], "--launch-id", payload["launch_id"],
                "--token", token, "--session", sid, "--block", bid]
    protocol = message(payload["protocol"].encode())
    report_sid, report_bid = metadata["AGENT_REPORT_TO"].split(" ")
    report_args = ["send", "--session", address_id(report_sid, "session"), "--block", address_id(report_bid, "block"),
                   "--from", metadata["AGENT_NAME"], "--message-file", "-"]
    if payload["store"] is not None:
        report_args += ["--store", absolute(payload["store"])]
    # Replace only routing command lines. All protocol text/whitespace remains literal.
    for marker, command in (("Acknowledge this protocol now by running:\n", callback_command(callbacks, ack_args)),
                            ("Supply report bytes on stdin then EOF using:\n", [RUNTIME, "--config", callbacks["config"],
                                                                                "--host", callbacks["host"], *report_args])):
        require(protocol.count(marker) == 1, "invalid_compute_protocol")
        before, after = protocol.split(marker, 1)
        unused, tail = after.split("\n", 1)
        protocol = before + marker + shlex.join(command) + "\n" + tail
    if payload["hook_events"]:
        require("--settings" not in argv, "profile_settings_conflict")
        hook = shlex.join([RUNTIME, "agents", "stop", "--registry", payload["registry"],
                           "--launch-id", payload["launch_id"], "--event-file", "-", "--callback-config", callbacks["config"],
                           "--callback-host", callbacks["host"]])
        # The compute-side adapter reads its own transcript, then forwards only bounded event bytes.
        settings = {"hooks": {k: [{"hooks": [{"type": "command", "command": hook, "timeout": 15}]}]
                              for k in ("Stop", "StopFailure")}}
        argv = argv + ["--settings", json.dumps(settings)]
    env = dict(os.environ)
    for key in ("AGENT_CHANNEL", "LC_AGENT_CHANNEL"):
        env.pop(key, None)
    env.update(metadata)
    env.update({"LC_" + k: v for k, v in metadata.items()})
    env.pop("TEEREX_INTERNAL_REX", None)
    child = subprocess.Popen(argv + [protocol], env=env, cwd=payload["cwd"])
    def forward(sig, unused):
        with contextlib.suppress(ProcessLookupError):
            child.send_signal(sig)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    code = child.wait()
    term = {"Exited": code} if code >= 0 else {"Signal": -code}
    # A separate callback records measured remote-child evidence. SSH's own exit never substitutes for it.
    args = callback_command(callbacks, ["exited", "--registry", payload["registry"], "--launch-id", payload["launch_id"],
                                       "--token", token, "--session", sid, "--block", bid, "--term-json", json.dumps(term)])
    callback_code, result = invoke(args[1:])
    if callback_code:
        print(json.dumps(dict(kind="compute_exit_callback", outcome="uncertain", receipt=result, retry_safe=False)), file=sys.stderr)
    return (code if code >= 0 else min(255, 128 - code)), None


def exited(o):
    term = json.loads(o.term_json)
    require(isinstance(term, dict) and len(term) == 1 and
            ((set(term) == {"Exited"} and type(term["Exited"]) is int and 0 <= term["Exited"] <= 255) or
             (set(term) == {"Signal"} and type(term["Signal"]) is int and 1 <= term["Signal"] <= 127)), "invalid_compute_term")
    def record(s):
        require(s.get("execution") is not None, "compute_exit_not_expected")
        require(secrets.compare_digest(text(o.token, 64), s["token"]), "compute_exit_token_mismatch")
        require(s["target"]["session_id"] == address_id(o.session, "session") and
                s["target"]["block_id"] == address_id(o.block, "block"), "compute_exit_address_mismatch")
        require(s.get("remote_child_term") is None, "compute_exit_already_recorded")
        s["remote_child_term"] = term
    state = update(o.registry, o.launch_id, record)
    return 0, receipt(state, "remote_child_exit_reported")


def delivery_config(value):
    if value is None:
        return None
    require(isinstance(value, dict) and set(value) == {"directory", "grants", "max_requests", "lifetime_ms"},
            "invalid_delivery_config")
    absolute(value["directory"])
    grants = value["grants"]
    require(isinstance(grants, list) and grants and all(g in ("send", "ack", "stop") for g in grants)
            and len(set(grants)) == len(grants), "explicit_delivery_grants_required")
    require(type(value["max_requests"]) is int and 1 <= value["max_requests"] <= 64, "invalid_delivery_count")
    require(type(value["lifetime_ms"]) is int and 1000 <= value["lifetime_ms"] <= 86400000, "invalid_delivery_lifetime")
    # Validate the parent before creation, without putting a registry or lock inside the grant.
    fd = os.open(value["directory"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        s = os.fstat(fd)
        require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, "private_delivery_parent_required")
    finally:
        os.close(fd)
    return dict(value)


def source_bytes(path):
    if path != "-":
        return read_file(path, 32768)
    end = time.monotonic() + 2
    raw = bytearray()
    while True:
        remaining = end - time.monotonic()
        require(remaining > 0 and select.select([sys.stdin.fileno()], [], [], max(0, remaining))[0], "input_eof_deadline_2s")
        part = os.read(sys.stdin.fileno(), min(4096, 32769 - len(raw)))
        if not part:
            return bytes(raw)
        raw.extend(part)
        require(len(raw) <= 32768, "input_too_large")


def frame_read(connection, budget=.5):
    raw = bytearray()
    end = time.monotonic() + budget
    # One bounded JSON line per connection. Newlines inside strings are JSON escaped.
    while b"\n" not in raw:
        remaining = end - time.monotonic()
        require(remaining > 0, "channel_frame_deadline")
        connection.settimeout(remaining)
        part = connection.recv(min(4096, 49153 - len(raw)))
        require(part, "incomplete_channel_frame")
        raw.extend(part)
        require(len(raw) <= 49152, "channel_frame_too_large")
    require(raw.endswith(b"\n") and raw.count(b"\n") == 1, "one_channel_frame_required")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate_channel_field")
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(value, dict), "invalid_channel_frame")
    return value


def channel_failure(reason, outcome="refused_or_uncertain"):
    return dict(schema_version=1, kind="agent_channel_result", outcome=outcome,
                failure_reason=str(reason), retry_safe=False)


class Channel:
    """A launch-owned socket; the visible supervisor is its only servicing process.

    The directory is the only fence mount. No filesystem paths supplied by a peer are opened.
    Bearer authority is cooperative outside a fence, not authentication against the same account.
    """
    def __init__(self, root, state):
        self.root, self.state = root, state
        self.policy = state["delivery"]
        self.directory = str(Path(self.policy["directory"]) / state["launch_id"])
        self.path = str(Path(self.directory) / "channel.sock")
        self.handle = str(Path(self.directory) / "handle.json")
        self.count = 0
        self.next_accept = 0
        self.closed = False
        self.token = secrets.token_hex(32)
        self.expires = min(state["review_at"], now() + self.policy["lifetime_ms"])
        self.deadline = time.monotonic() + max(0, (self.expires - now()) / 1000)
        require(len(os.fsencode(self.path)) < 100, "channel_socket_path_too_long")
        self.parent = os.open(self.policy["directory"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.fd = None
        self.listener = None
        try:
            os.mkdir(state["launch_id"], 0o700, dir_fd=self.parent)
            self.fd = os.open(state["launch_id"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.parent)
            self.identity = os.fstat(self.fd)
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.bind(self.path)
            os.chmod(self.path, 0o600)
            self.listener.listen(4)
            self.listener.settimeout(.05)
            handle = dict(schema_version=1, launch_id=state["launch_id"], token=self.token, socket=self.path,
                          expires_at=self.expires, grants=self.policy["grants"])
            fd = os.open("handle.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            with os.fdopen(fd, "w") as f:
                json.dump(handle, f)
            update(root, state["launch_id"], lambda s: s.update(channel_status="active", channel_expires_at=self.expires))
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.listener is not None:
            self.listener.close()
        if self.fd is not None:
            for name in ("channel.sock", "handle.json"):
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(name, dir_fd=self.fd)
            os.close(self.fd)
            # Never follow a peer's substitution while removing our own directory.
            with contextlib.suppress(FileNotFoundError, OSError):
                s = os.stat(self.state["launch_id"], dir_fd=self.parent, follow_symlinks=False)
                if (s.st_dev, s.st_ino) == (self.identity.st_dev, self.identity.st_ino):
                    os.rmdir(self.state["launch_id"], dir_fd=self.parent)
        os.close(self.parent)

    def dispatch(self, request):
        require(set(request) <= {"launch_id", "token", "request_id", "operation", "to", "body", "session", "block", "event"},
                "unknown_channel_field")
        require(request.get("launch_id") == self.state["launch_id"], "channel_launch_mismatch")
        require(isinstance(request.get("token"), str) and secrets.compare_digest(request["token"], self.token),
                "channel_token_mismatch")
        event_id = identifier(request.get("request_id"))
        operation = request.get("operation")
        require(operation in self.policy["grants"], "channel_operation_not_granted")
        required = {"launch_id", "token", "request_id", "operation"}
        required |= {"send": {"to", "body"}, "ack": {"session", "block"}, "stop": {"event"}}[operation]
        require(set(request) == required, "invalid_channel_operation_fields")
        if operation == "send":
            require(request["to"] in ("starter", "report-to"), "fixed_channel_destination_required")
            message(request["body"].encode())
        elif operation == "ack":
            address_id(request["session"], "session")
            address_id(request["block"], "block")
        else:
            validate_hook_event(request["event"], allow_transcript=False)
        def intent(s):
            require(s["immediate_child_term"] is None, "channel_child_already_exited")
            history = s.setdefault("channel_requests", {})
            require(event_id not in history, "channel_request_already_attempted_no_retry")
            require(len(history) < self.policy["max_requests"], "channel_request_limit")
            history[event_id] = dict(operation=operation, outcome="uncertain", attempted_at=now())
        update(self.root, self.state["launch_id"], intent)
        if operation == "send":
            state = load(self.root, self.state["launch_id"])
            destination = state["starter" if request["to"] == "starter" else "report_to"]
            code, packet = send(self.root, state, destination, request["body"], "channel-" + event_id)
            result = dict(schema_version=1, kind="agent_channel_result", request_id=event_id, retry_safe=False,
                          outcome="transport_acknowledged" if transport_ack(code, packet) else "uncertain",
                          client_exit=code, receipt=packet, target=destination)
        elif operation == "ack":
            state = load(self.root, self.state["launch_id"])
            code, result = ack(argparse.Namespace(registry=self.root, launch_id=state["launch_id"], token=state["token"],
                                                 session=request["session"], block=request["block"]))
        else:
            code, result = report_stop(self.root, self.state["launch_id"], event_id, request["event"], allow_transcript=False)
        update(self.root, self.state["launch_id"], lambda s: s["channel_requests"][event_id].update(
            outcome=result["outcome"], client_exit=code, receipt=result.get("receipt") if operation == "send" else None))
        return code, result

    def service(self):
        if self.closed:
            time.sleep(.05)
            return
        if time.monotonic() >= self.deadline or self.count >= self.policy["max_requests"]:
            self.close()
            update(self.root, self.state["launch_id"], lambda s: s.update(channel_status="revoked"))
            return
        remaining = self.next_accept - time.monotonic()
        if remaining > 0:
            time.sleep(min(.05, remaining))
            return
        try:
            connection, unused = self.listener.accept()
        except socket.timeout:
            return
        except OSError:
            if self.closed:  # INT/TERM can revoke while accept is waiting.
                return
            raise
        self.count += 1
        self.next_accept = time.monotonic() + .05
        with connection:
            connection.settimeout(.5)
            try:
                request = frame_read(connection)
                # Recheck after the bounded read, not just at accept.
                require(time.monotonic() < self.deadline, "channel_expired")
                code, result = self.dispatch(request)
            except (Refusal, OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, subprocess.SubprocessError) as exc:
                code, result = 1, channel_failure(exc)
            response = json.dumps(dict(code=code, result=result), ensure_ascii=False).encode() + b"\n"
            if len(response) > 49152:
                response = json.dumps(dict(code=1, result=channel_failure("receipt_too_large_inspect_registry", "delivery_uncertain_no_retry"))).encode() + b"\n"
            with contextlib.suppress(OSError):
                connection.sendall(response)


def channel(o):
    handle = json.loads(read_file(o.handle, 4096, private=True))
    require(handle["schema_version"] == 1 and now() < handle["expires_at"], "channel_expired_or_invalid")
    operation = o.channel_operation
    allowed = {"send": {"to", "message_file"}, "ack": {"session", "block"}, "stop": {"event_file"}}[operation]
    require(all(getattr(o, key) is None or key in allowed for key in ("to", "message_file", "session", "block", "event_file")),
            "irrelevant_channel_argument")
    require(operation in handle["grants"], "channel_operation_not_granted")
    request = dict(launch_id=identifier(handle["launch_id"]), token=text(handle["token"], 64),
                   request_id=identifier(o.request_id), operation=operation)
    if operation == "send":
        require(o.to in ("starter", "report-to") and o.message_file is not None, "fixed_channel_destination_and_message_required")
        raw = source_bytes(o.message_file)
        request.update(to=o.to, body=message(raw))
    elif operation == "ack":
        request.update(session=address_id(o.session, "session"), block=address_id(o.block, "block"))
    else:
        require(o.event_file is not None, "hook_event_required")
        raw = source_bytes(o.event_file)
        require(len(raw) <= 32768, "hook_event_too_large")
        event = json.loads(raw)
        # Read any transcript inside the worker's own fence. The outside authority never opens its paths.
        validate_hook_event(event)
        if event["hook_event_name"] == "Stop" and not event.get("last_assistant_message"):
            try:
                event["last_assistant_message"] = transcript_last_text(event.get("transcript_path"))[:1500]
            except (OSError, Refusal, ValueError):
                event["last_assistant_message"] = "(last words unavailable inside worker)"
        event.pop("transcript_path", None)
        request["event"] = event
    raw = json.dumps(request, ensure_ascii=False).encode() + b"\n"
    require(len(raw) <= 49152, "channel_frame_too_large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(12)
        try:
            client.connect(absolute(handle["socket"]))
            client.sendall(raw)
            packet = frame_read(client, budget=12)
            require(set(packet) == {"code", "result"}, "invalid_channel_receipt")
            return packet["code"], packet["result"]
        except (OSError, ValueError, Refusal) as exc:
            # Even a failed response can follow applied input. Never reconnect or replay.
            return 1, channel_failure(exc, "delivery_uncertain_no_retry")


def config(path):
    value = json.loads(read_file(path))
    require(value.get("schema_version") == 1 and isinstance(value.get("profiles"), dict), "invalid_profiles_config")
    require(isinstance(value.get("defaults", {}), dict), "invalid_profile_defaults")
    return value


def launch(o):
    cfg = config(o.config)
    profile = cfg["profiles"].get(o.profile)
    require(isinstance(profile, dict), "unknown_profile")
    argv = profile.get("argv")
    require(isinstance(argv, list) and argv and all(isinstance(v, str) and "\0" not in v for v in argv), "invalid_profile_argv")
    absolute(argv[0])
    argv = list(argv)
    require(isinstance(profile.get("standing_flags", []), list), "invalid_standing_flags")
    for flag in profile.get("standing_flags", []):
        text(flag, 256)
        if flag not in argv:
            argv.append(flag)
    require(len(json.dumps(argv).encode()) <= 12000, "profile_argv_too_large")
    require(profile.get("protocol_mode") == "argument", "profile_must_explicitly_support_protocol_as_final_prompt_argument")
    require(type(profile.get("hook_events", False)) is bool, "invalid_hook_events")
    if profile.get("hook_events"):
        require(profile.get("harness", o.profile) == "claude" and "--settings" not in argv, "unsupported_or_conflicting_hook_adapter")
    execution, callbacks = execution_config(profile)
    delivery = delivery_config(profile.get("delivery"))
    require(not (delivery is not None and execution is not None), "remote_fenced_delivery_not_yet_supported")
    if execution is None:
        require(Path(argv[0]).name not in ("ssh", "mosh"), "use_execution_route_for_lossless_remote_protocol")
    if delivery is not None:
        require("ack" in delivery["grants"], "managed_delivery_requires_ack_grant")
        require(not profile.get("hook_events") or "stop" in delivery["grants"], "hooks_require_stop_grant")
    # Explicit defaults replace personal/global shell edits; command-line options override them.
    for key in ("registry", "socket", "session", "cwd", "starter_session", "starter_block", "report_to_session",
                "report_to_block", "host", "owner", "purpose", "store"):
        if getattr(o, key, None) is None:
            setattr(o, key, cfg.get("defaults", {}).get(key))
    root, socket = absolute(o.registry), absolute(o.socket)
    if o.store is not None:
        absolute(o.store)
    if profile.get("resume_session_id") is not None:
        text(profile["resume_session_id"], 256)
    if os.environ.get("TEEREX_INTERNAL_REX") is not None:
        absolute(os.environ["TEEREX_INTERNAL_REX"])
    session, ss, sb = address_id(o.session, "session"), address_id(o.starter_session, "session"), address_id(o.starter_block, "block")
    rs = address_id(o.report_to_session or ss, "session")
    rb = address_id(o.report_to_block or sb, "block")
    name, owner, purpose = text(o.name or o.profile), text(o.owner), text(o.purpose, 256)
    host = text(o.host)
    cwd = absolute(o.cwd)
    review = o.review_at or now() + cfg.get("defaults", {}).get("review_after_ms", 3600000)
    require(type(review) is int and now() < review <= now() + 30 * 86400000, "invalid_review_at")
    brief = message(read_file(o.brief_file, 32768)) if o.brief_file else None
    launch_id, token = secrets.token_hex(16), secrets.token_hex(32)
    target = dict(host=host, server="unix://" + socket, session_id=session, block_id=None)
    starter = dict(host=host, server="unix://" + socket, session_id=ss, block_id=sb)
    report_to = dict(host=host, server="unix://" + socket, session_id=rs, block_id=rb)
    state = dict(schema_version=1, launch_id=launch_id, token=token, name=name, owner=owner, purpose=purpose,
                 review_at=review, target=target, starter=starter, report_to=report_to, profile=o.profile, argv=argv,
                 cwd=cwd, harness=text(profile.get("harness", o.profile)), resume_session_id=profile.get("resume_session_id"),
                 store=o.store, created_at=now(), socket=socket, registry=root, phase="creation_uncertain", tracked=False,
                 protocol_acknowledged=False, protocol_outcome=None, brief_attempted=False, brief_outcome=None,
                 immediate_child_term=None, notifications={}, brief_file=None, protocol_file=None,
                 hook_events=profile.get("hook_events", False), client_path=os.environ.get("PATH", os.defpath),
                 rex_executable=os.environ.get("TEEREX_INTERNAL_REX"), delivery=delivery, execution=execution,
                 callbacks=callbacks, remote_child_term=None)
    with Registry(root) as registry:
        if brief is not None:
            state["brief_file"] = registry.write_message(launch_id, "brief", brief)
        registry.save(state, new=True)
    command = [RUNTIME, "agents", "supervise", "--registry", root, "--launch-id", launch_id]
    code, packet = invoke(["spawn", "--socket", socket, "--session", session, "--name", name, "--cwd", cwd,
                           "--report-to-session", rs, "--report-to-block", rb, "--", *command])
    def created(s):
        s["spawn_receipt"] = packet
        if isinstance(packet, dict) and packet.get("created"):
            s["target"]["block_id"] = address_id(packet["created"]["block_id"], "block")
    state = update(root, launch_id, created)
    if not succeeded(code, packet, "created_and_attached"):
        return 1, receipt(state, "creation_uncertain", client_exit=code)
    block = state["target"]["block_id"]
    code, packet = invoke(["jobs", "track", "--registry", root, "--socket", socket, "--session", session, "--block", block,
                           "--owner", owner, "--kind", "agent", "--purpose", purpose,
                           "--deadline-unix-ms", str(review), "--cleanup", "manual"])
    def tracked(s):
        s["track_receipt"] = packet
        s["tracked"] = succeeded(code, packet, "verified")
        s["phase"] = "protocol_pending" if s["tracked"] else "tracking_uncertain"
    state = update(root, launch_id, tracked)
    if not state["tracked"]:
        return 1, receipt(state, "tracking_uncertain", client_exit=code)
    if publish_fleet(root, state, "launch", "unknown", "Visible agent registered; protocol not acknowledged; readiness not assessed"):
        return 1, receipt(load(root, launch_id), "fleet_report_uncertain")
    # The first harness prompt is an explicit profile-supported argv argument. Sending terminal input
    # immediately after creation would race shell/harness startup and silently lose the protocol.
    ack_command = [RUNTIME, "agents", "ack", "--registry", root, "--launch-id", launch_id,
                   "--token", token, "--session", session, "--block", block]
    if delivery is not None:
        ack_command = [RUNTIME, "agents", "channel", "--handle", str(Path(delivery["directory"]) / launch_id / "handle.json"),
                       "--request-id", secrets.token_hex(16), "--operation", "ack", "--session", session, "--block", block]
    report_command = [RUNTIME, "send", "--socket", socket, "--session", rs, "--block", rb, "--from", name,
                      "--message-file", "-", *send_options(state)]
    if delivery is not None:
        report_command = [RUNTIME, "agents", "channel", "--handle", str(Path(delivery["directory"]) / launch_id / "handle.json"),
                          "--request-id", "NEW_HEX32", "--operation", "send", "--to", "report-to", "--message-file", "-"]
    protocol = ("Messaging protocol (not a task brief):\n"
                f"Your name is {name}; your pane is {session} {block}.\n"
                f"Your starter is {ss} {sb}; report-to is {rs} {rb}.\n"
                "Report stops, results, blockers and questions directly to report-to; never type into a registered human seat.\n"
                "A finished turn is idle, not process death. Supply report bytes on stdin then EOF using:\n" +
                shlex.join(report_command) + "\n" +
                ("Replace NEW_HEX32 with a fresh 32-lowercase-hex request id for each NEW message; never retry uncertain input.\n"
                 if delivery is not None else "Never retry uncertain input.\n") +
                "Do not begin a task or launch another agent before the brief. Acknowledge this protocol now by running:\n" +
                shlex.join(ack_command) +
                "\nThis ACK records protocol acknowledgment only, not readiness, authorization or exclusive input control.")
    with Registry(root) as registry:
        state = registry.read(launch_id)
        state["protocol_file"] = registry.write_message(launch_id, "protocol", protocol)
        state["phase"] = "awaiting_protocol_ack"
        registry.save(state)
    end = time.monotonic() + o.ack_timeout_ms / 1000
    while time.monotonic() < end:
        state = load(root, launch_id)
        if state["protocol_acknowledged"] and state["protocol_outcome"] == "argument_supplied":
            return deliver(root, launch_id)
        if state["immediate_child_term"] is not None:
            return 1, receipt(state, "child_exited_before_ack")
        time.sleep(.05)
    return 124, receipt(state, "protocol_ack_timeout", automatic_close=False,
                        next_action="inspect_the_visible_pane_then_explicitly_deliver_only_if_acknowledged")


def ack(o):
    def acknowledge(s):
        require(secrets.compare_digest(text(o.token, 64), s["token"]), "ack_token_mismatch")
        require(s["target"]["session_id"] == address_id(o.session, "session") and
                s["target"]["block_id"] == address_id(o.block, "block"), "ack_address_mismatch")
        require(s["phase"] == "awaiting_protocol_ack" and s["immediate_child_term"] is None, "ack_not_expected")
        require(not s["protocol_acknowledged"], "protocol_already_acknowledged")
        s["protocol_acknowledged"] = True
        s["protocol_ack_at"] = now()
    state = update(o.registry, o.launch_id, acknowledge)
    return 0, receipt(state, "protocol_acknowledged")


def deliver(root, launch_id):
    with Registry(root) as registry:
        state = registry.read(launch_id)
        require(state["tracked"] and state["protocol_acknowledged"] and
                state["protocol_outcome"] == "argument_supplied", "protocol_gate_not_satisfied")
        require(state["immediate_child_term"] is None, "child_already_exited")
        require(not state["brief_attempted"], "brief_already_attempted_inspect_before_any_new_request")
        if state["brief_file"] is None:
            state["phase"] = "protocol_acknowledged_no_brief"
            registry.save(state)
            return 0, receipt(state, "protocol_acknowledged_no_brief")
        state["brief_attempted"] = True
        state["brief_outcome"] = "uncertain"
        state["phase"] = "brief_attempt_uncertain"
        registry.save(state)
    code, packet = invoke(["send", "--socket", state["socket"], "--session", state["target"]["session_id"],
                           "--block", state["target"]["block_id"], "--from", state["name"], "--message-file", state["brief_file"]],
                          client_path=state["client_path"], rex_executable=state["rex_executable"])
    def delivered(s):
        s["brief_receipt"] = packet
        s["brief_outcome"] = "events_acknowledged" if transport_ack(code, packet) else "uncertain"
        s["phase"] = "brief_submitted" if transport_ack(code, packet) else "brief_uncertain"
    state = update(root, launch_id, delivered)
    return (0 if transport_ack(code, packet) else 1), receipt(state, state["phase"])


def publish_fleet(root, state, event_id, reported_state, detail):
    if state["store"] is None:
        return 0
    def intent(s):
        history = s.setdefault("fleet_reports", {})
        require(event_id not in history, "fleet_report_already_attempted")
        require(len(history) < 65, "fleet_report_history_full")
        history[event_id] = dict(outcome="uncertain", attempted_at=now())
    update(root, state["launch_id"], intent)
    code, packet = invoke(["fleet", "report", "--store", state["store"], "--host", state["target"]["host"],
                           "--socket", state["socket"], "--session", state["target"]["session_id"],
                           "--block", state["target"]["block_id"], "--owner", state["owner"], "--purpose", state["purpose"],
                           "--state", reported_state, "--detail", detail[:512]], client_path=state["client_path"],
                          rex_executable=state["rex_executable"])
    update(root, state["launch_id"], lambda s: s["fleet_reports"][event_id].update(
        outcome="reported" if code == 0 else "uncertain", client_exit=code, receipt=packet))
    return code


def notify(root, launch_id, event_id, body, evidence, reported_state="unknown"):
    with Registry(root) as registry:
        state = registry.read(launch_id)
        require(event_id not in state["notifications"], "notification_already_attempted")
        require(len(state["notifications"]) < 64, "notification_history_full")
        state["notifications"][event_id] = dict(outcome="uncertain", evidence=evidence, attempted_at=now())
        registry.save(state)
    # Starter and report-to can differ; notify both, deduplicating the exact tuple.
    destinations = [state["starter"]]
    if state["report_to"] != state["starter"]:
        destinations.append(state["report_to"])
    results = []
    for i, destination in enumerate(destinations):
        code, packet = send(root, state, destination, body, "notice-" + event_id + "-" + str(i))
        results.append(dict(target=destination, client_exit=code, receipt=packet,
                            outcome="transport_acknowledged" if transport_ack(code, packet) else "uncertain"))
    def reported(s):
        s["notifications"][event_id]["results"] = results
        s["notifications"][event_id]["outcome"] = ("transport_acknowledged" if all(r["outcome"] == "transport_acknowledged"
                                                                                   for r in results) else "uncertain")
    state = update(root, launch_id, reported)
    fleet_code = publish_fleet(root, state, event_id, reported_state, body.replace("\n", " "))
    ok = state["notifications"][event_id]["outcome"] == "transport_acknowledged" and fleet_code == 0
    return (0 if ok else 1), receipt(state, "notification_acknowledged" if ok else "notification_uncertain")


def transcript_last_text(path):
    if not path:
        return ""
    fd = os.open(absolute(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        s = os.fstat(f.fileno())
        require(stat.S_ISREG(s.st_mode), "regular_transcript_required")
        f.seek(max(0, s.st_size - LIMIT))
        lines = f.read(LIMIT).splitlines()[-200:]
    for line in reversed(lines):
        try:
            event = json.loads(line)
            content = event.get("message", {}).get("content", [])
            if event.get("type") == "assistant" and isinstance(content, list):
                value = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text").strip()
                if value:
                    return value
        except (ValueError, AttributeError, TypeError):
            continue
    return ""


def stop(o):
    raw = source_bytes(o.event_file)
    require(len(raw) <= 32768, "hook_event_too_large")
    event = json.loads(raw)
    require(isinstance(event, dict), "invalid_hook_event")
    event_id = identifier(o.event_id) if o.event_id else secrets.token_hex(16)
    require((o.callback_config is None) == (o.callback_host is None), "both_callback_route_fields_required")
    if o.callback_config is not None:
        validate_hook_event(event)
        if event["hook_event_name"] == "Stop" and not event.get("last_assistant_message"):
            try:
                event["last_assistant_message"] = transcript_last_text(event.get("transcript_path"))[:1500]
            except (OSError, Refusal, ValueError):
                event["last_assistant_message"] = "(last words unavailable on compute host)"
        event.pop("transcript_path", None)
        args = callback_command(dict(config=absolute(o.callback_config), host=o.callback_host),
                                ["stop", "--registry", o.registry, "--launch-id", o.launch_id, "--event-file", "-", "--event-id", event_id])
        return invoke(args[1:], input_bytes=json.dumps(event, ensure_ascii=False).encode())
    return report_stop(o.registry, o.launch_id, event_id, event)


def validate_hook_event(event, allow_transcript=True):
    require(isinstance(event, dict), "invalid_hook_event")
    require(event.get("hook_event_name") in ("Stop", "StopFailure"), "unsupported_hook_event")
    require(isinstance(event.get("last_assistant_message", "") or "", str), "invalid_last_words")
    require(len(json.dumps(event).encode()) <= 32768, "hook_event_too_large")
    require(allow_transcript or "transcript_path" not in event, "channel_transcript_path_forbidden")


def report_stop(root, launch_id, event_id, event, allow_transcript=True):
    validate_hook_event(event, allow_transcript)
    kind = event["hook_event_name"]
    last = event.get("last_assistant_message", "") or ""
    if allow_transcript and kind == "Stop" and not last:
        try:
            last = transcript_last_text(event.get("transcript_path"))
        except (OSError, Refusal, ValueError):
            last = "(last words unavailable: transcript could not be read)"
    error = str(event.get("error") or event.get("error_details") or event.get("message") or "unknown error")
    details = (last[:1500] or "(no last words supplied)") if kind == "Stop" else error[:600]
    state = load(root, launch_id)
    # Hook metadata reports a turn, never process death; only invocation IDs deduplicate.
    title = "IDLE (harness turn-stop report)" if kind == "Stop" else "ERROR (harness failure report, death not verified)"
    body = f"{title}: {state['name']}\n{details}"
    def remembered(s):
        s["last_hook"] = dict(kind=kind, at=now(), text=details, evidence="harness_report_not_process_death")
    update(root, launch_id, remembered)
    return notify(root, launch_id, event_id, body, "harness_report_not_process_death",
                  reported_state="idle" if kind == "Stop" else "unknown")


def supervise(o):
    # This command is launched ONLY as the actual retained visible Rex terminal program.
    state = load(o.registry, o.launch_id)
    sid, bid = os.environ.get("REX_SESSION"), os.environ.get("REX_BLOCK")
    address_id(sid, "session")
    address_id(bid, "block")
    require(sid == state["target"]["session_id"], "supervisor_session_mismatch")
    end = time.monotonic() + 12
    while (not state["tracked"] or not state["protocol_file"]) and time.monotonic() < end:
        time.sleep(.05)
        state = load(o.registry, o.launch_id)
    require(state["tracked"] and state["protocol_file"] and state["target"]["block_id"] == bid,
            "supervisor_requires_verified_tracked_pane_and_protocol")
    def claim(s):
        require(not s.get("supervisor_claimed"), "supervisor_already_claimed")
        require(s["immediate_child_term"] is None, "child_already_exited")
        s["supervisor_claimed"] = True
        s["supervisor_pid"] = os.getpid()
    update(o.registry, o.launch_id, claim)
    env = dict(os.environ)
    for key in ("AGENT_CHANNEL", "LC_AGENT_CHANNEL"):
        env.pop(key, None)  # A new launch never inherits its parent's capability implicitly.
    metadata = dict(AGENT_SESSION=sid, AGENT_PANE=bid, REX_SESSION=sid, REX_BLOCK=bid, AGENT_NAME=state["name"],
                    AGENT_STARTER=state["starter"]["session_id"] + " " + state["starter"]["block_id"],
                    AGENT_REPORT_TO=state["report_to"]["session_id"] + " " + state["report_to"]["block_id"],
                    AGENT_LAUNCH_ID=o.launch_id, AGENT_REGISTRY=o.registry)
    broker = Channel(o.registry, state) if state.get("delivery") is not None else None
    if broker is not None:
        metadata.pop("AGENT_REGISTRY")
        env.pop("AGENT_REGISTRY", None)
        env.pop("LC_AGENT_REGISTRY", None)
        metadata["AGENT_CHANNEL"] = broker.handle
    env.update(metadata)
    env.update({"LC_" + k: v for k, v in metadata.items()})
    argv = state["argv"]
    if state.get("hook_events") and state.get("execution") is None:
        require(state["harness"] == "claude", "automatic_hook_adapter_not_supported_for_harness")
        hook = shlex.join([RUNTIME, "agents", "stop", "--registry", o.registry, "--launch-id", o.launch_id, "--event-file", "-"])
        if broker is not None:
            # Each hook invocation creates its own request ID inside the worker, never a static per-launch ID.
            hook = (shlex.join([RUNTIME, "agents", "channel", "--handle", broker.handle, "--operation", "stop",
                               "--event-file", "-"]) + " --request-id \"$(python3 -c 'import secrets; print(secrets.token_hex(16))')\"")
        require("--settings" not in argv, "profile_settings_conflict")
        settings = {"hooks": {k: [{"hooks": [{"type": "command", "command": hook, "timeout": 15}]}]
                              for k in ("Stop", "StopFailure")}}
        argv = argv + ["--settings", json.dumps(settings)]
    protocol = message(read_file(state["protocol_file"], 32768, private=True))
    if state.get("execution") is None:
        argv = argv + [protocol]
    else:
        execution = state["execution"]
        payload = dict(argv=argv, cwd=execution["cwd"], metadata=metadata, protocol=protocol, registry=o.registry,
                       launch_id=o.launch_id, token=state["token"], callbacks=state["callbacks"], hook_events=state["hook_events"],
                       pane=state["target"], store=state["store"])
        encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
        require(len(encoded) <= 98304, "compute_payload_too_large")
        argv = [RUNTIME, "targets", "exec", "--config", execution["config"], "--host", execution["host"], "--tty",
                "--", "agents", "exec", "--payload", encoded]
    # No output pipe: agent, supervisor and real pointer/keyboard input share the visible terminal.
    def osc(status, detail):
        sys.stdout.write("\x1b]7501;" + json.dumps(dict(state=status, title=state["name"], msg=detail)) + "\x07")
        sys.stdout.flush()
    osc("working", "visible agent process starting; readiness not assessed")
    child = None
    term = None
    try:
        child = subprocess.Popen(argv, env=env, cwd=state["cwd"])
        update(o.registry, o.launch_id, lambda s: s.update(immediate_child_started_at=now(), protocol_outcome="argument_supplied"))
        def forward(sig, unused):
            # Revoke on cancellation even if the child ignores its forwarded signal.
            if broker is not None:
                broker.close()
                update(o.registry, o.launch_id, lambda s: s.update(channel_status="revoked"))
            # Only our still-unreaped immediate child. Not a process-tree stop guarantee.
            with contextlib.suppress(ProcessLookupError):
                child.send_signal(sig)
        signal.signal(signal.SIGTERM, forward)
        signal.signal(signal.SIGINT, forward)
        if broker is None:
            code = child.wait()
        else:
            while child.poll() is None:
                broker.service()
            code = child.returncode
        term = {"Exited": code} if code >= 0 else {"Signal": -code}
    except OSError as exc:
        term = {"launch_error": str(exc)[:600]}
        code = 125
    finally:
        if broker is not None:
            broker.close()
            update(o.registry, o.launch_id, lambda s: s.update(channel_status="revoked"))
        if term is not None:
            update(o.registry, o.launch_id, lambda s: s.update(immediate_child_term=term, immediate_child_ended_at=now()))
    osc("done" if term == {"Exited": 0} else "error", "immediate child terminated; descendants not verified")
    state = load(o.registry, o.launch_id)
    last = state.get("last_hook", {}).get("text", "(no harness last words supplied)")
    role = "SSH transport" if state.get("execution") else "Immediate child"
    remote = (f"Remote child: {json.dumps(state['remote_child_term']) if state.get('remote_child_term') else 'unknown; no measured exit callback'}\n"
              if state.get("execution") else "")
    notice_code, result = notify(o.registry, o.launch_id, "child-exit",
                                f"PROCESS EXIT: {state['name']}\n{role}: {json.dumps(term)}\n" + remote +
                                f"Last harness report: {last}\nDescendants are not verified gone.", "waited_immediate_child")
    if notice_code:
        print(json.dumps(result), file=sys.stderr)
    return (code if code >= 0 else min(255, 128 - code)), None


def present(o):
    state = load(o.registry, o.launch_id)
    require(state["tracked"] and state["target"]["block_id"] is not None, "tracked_target_required")
    text(o.owner)
    text(o.reason, 256)
    address_id(o.anchor, "block")
    require(o.generation > 0, "positive_generation_required")
    event_id = str(o.generation)
    def intent(s):
        history = s.setdefault("presentations", {})
        require(event_id not in history and len(history) < 32, "presentation_already_attempted_or_history_full")
        history[event_id] = dict(outcome="uncertain", owner=o.owner, reason=o.reason, anchor=o.anchor, focus=o.focus, at=now())
    update(o.registry, o.launch_id, intent)
    # Jobs holds its own owner/generation/identity lock through durable intent and relocation.
    args = ["jobs", "present", "--registry", o.registry, "--socket", state["socket"],
            "--session", state["target"]["session_id"], "--block", state["target"]["block_id"], "--owner", o.owner,
            "--generation", event_id, "--reason", o.reason, "--anchor", o.anchor, "--focus", o.focus, "--relocate", "yes"]
    code, packet = invoke(args, client_path=state["client_path"], rex_executable=state["rex_executable"])
    state = update(o.registry, o.launch_id, lambda s: s["presentations"][event_id].update(
        outcome="verified" if succeeded(code, packet, "verified") else "uncertain_or_refused", receipt=packet))
    return code, receipt(state, "presentation_verified" if succeeded(code, packet, "verified") else "presentation_uncertain_or_refused",
                         presentation=state["presentations"][event_id])


def profiles(o):
    cfg = config(o.config)
    return 0, dict(schema_version=1, kind="agent_profiles", profiles=cfg["profiles"], defaults=cfg.get("defaults", {}),
                   security_settings_changed=False, config_source=o.config)


def shell(o):
    cfg = config(o.config)
    print("# Opt-in shell functions; inspect before sourcing. No personal settings are edited.")
    for name in cfg["profiles"]:
        require(re.fullmatch(r"[a-z][a-z0-9_-]*", name), "profile_not_shell_identifier")
        print(f"if typeset -f {name} >/dev/null 2>&1; then")
        print(f"  printf '%s\\n' 'teerex: preserved existing {name} function; profile wrapper not installed' >&2")
        print("else")
        print(f"  {name}() {{ {shlex.join([RUNTIME, 'agents', 'launch', '--config', o.config, '--profile', name])} \"$@\"; }}")
        print("fi")
    return 0, None


def parser():
    p = argparse.ArgumentParser(prog="teerex agents", description=(
        "Visible profiles, protocol ACK-before-one-brief, optional named SSH compute and opt-in bounded local fence channel. "
        "Python3.9+. API13 jobs. Creation, transport ACK, agent ACK, idle and child exit are distinct. "
        "No readiness claim, input lease, hidden agent, daemon, automatic retry/close or whole-tree death guarantee."))
    sub = p.add_subparsers(dest="operation", required=True)
    for op in ("profiles", "shell"):
        q = sub.add_parser(op, help="inspect profiles" if op == "profiles" else "print opt-in shell functions; never edits shell files")
        q.add_argument("--config", required=True)
    q = sub.add_parser("exec", help="compute-host adapter for an explicit managed execution route; never a channel method")
    q.add_argument("--payload", required=True, help="bounded base64 JSON literal argv/cwd/protocol and callback route")
    q = sub.add_parser("channel", help="one bounded launch-scoped request; no Rex socket, registry or arbitrary destination")
    q.add_argument("--handle", required=True)
    q.add_argument("--request-id", required=True, help="32 lowercase hex; reuse refuses, never resends")
    q.add_argument("--operation", dest="channel_operation", required=True, choices=("send", "ack", "stop"))
    q.add_argument("--to", choices=("starter", "report-to"))
    q.add_argument("--message-file", help="send only: absolute UTF-8 file or -; <=32KiB/EOF within 2s")
    q.add_argument("--event-file", help="stop only: absolute JSON file or -; <=32KiB/EOF within 2s")
    q.add_argument("--session", help="ack only: exact own session:UUID, not a destination selector")
    q.add_argument("--block", help="ack only: exact own block:UUID, not a destination selector")
    q = sub.add_parser("launch", help="create visible pane, track jobs, send protocol, await agent ACK, attempt brief once")
    q.add_argument("--config", required=True)
    q.add_argument("--profile", required=True)
    for key in ("registry", "socket", "session", "name", "cwd", "starter-session", "starter-block", "report-to-session",
                "report-to-block", "host", "owner", "purpose", "store", "brief-file"):
        q.add_argument("--" + key)
    q.add_argument("--review-at", type=int, help="absolute future Unix milliseconds, <=30 days; default config review_after_ms")
    q.add_argument("--ack-timeout-ms", type=int, default=10000, choices=range(100, 60001), metavar="100..60000")
    for op in ("ack", "deliver", "inspect", "present", "stop", "supervise", "exited"):
        q = sub.add_parser(op, help={"ack": "record agent protocol ACK; token plus exact pane required",
                                    "deliver": "explicitly attempt a not-yet-attempted brief after ACK",
                                    "inspect": "offline lifecycle metadata; not live liveness",
                                    "present": "explicit relocation beside anchor through jobs owner/generation checks",
                                    "stop": "submit a harness Stop/StopFailure report, never death proof",
                                    "supervise": "internal retained visible in-pane program; waits immediate child",
                                    "exited": "compute adapter measured-child-exit callback, distinct from SSH exit"}[op])
        q.add_argument("--registry", required=True)
        q.add_argument("--launch-id", required=True)
        if op in ("ack", "exited"):
            for key in ("token", "session", "block"):
                q.add_argument("--" + key, required=True)
        if op == "exited":
            q.add_argument("--term-json", required=True)
        if op == "stop":
            q.add_argument("--callback-config", help="compute-local named-host config; paired with callback-host")
            q.add_argument("--callback-host", help="explicit registry-host route; never inferred from pane label")
            q.add_argument("--event-file", required=True, help="absolute JSON file or - for <=32KiB stdin/EOF within 2s")
            q.add_argument("--event-id", help="optional stable 32-lowercase-hex hook invocation ID; duplicate attempts refuse")
        if op == "present":
            for key in ("owner", "reason", "anchor"):
                q.add_argument("--" + key, required=True)
            q.add_argument("--generation", required=True, type=int)
            q.add_argument("--focus", required=True, choices=("yes", "no"))
    return p


def main():
    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGTERM, terminate)
    o = parser().parse_args(sys.argv[2:])
    try:
        if o.operation == "deliver":
            code, result = deliver(o.registry, o.launch_id)
        elif o.operation == "inspect":
            code, result = 0, receipt(load(o.registry, o.launch_id), "saved_metadata_not_live_evidence")
        elif o.operation == "exec":
            code, result = remote_exec(o)
        else:
            code, result = globals()[o.operation](o)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False))
        return code
    except (KeyboardInterrupt, Cancelled) as exc:
        sig = exc.args[0] if isinstance(exc, Cancelled) else signal.SIGINT
        print(json.dumps(dict(schema_version=1, kind="agents_result", outcome="cancelled_uncertain", retry_safe=False)))
        return 128 + sig
    except (Refusal, OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as exc:
        print(json.dumps(dict(schema_version=1, kind="agents_result", outcome="refused_or_uncertain", failure_reason=str(exc),
                              retry_safe=False, agent_readiness="not_assessed", all_processes_verified_gone=False)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
