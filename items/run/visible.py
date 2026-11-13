"""Foreground controller and actual in-pane runner; Python 3.9+ stdlib only."""
import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

INPUT_LIMIT = 1048576
FILE_LIMIT = 64 * 1024 * 1024
STOP = 0
RECEIPT = None
BROKER = None


def stopped(sig, unused):
    global STOP
    STOP = sig


def private_write(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(data)


def save(path, value):
    stage = str(path) + ".next"
    private_write(stage, json.dumps(value, ensure_ascii=True).encode())
    os.replace(stage, path)


def load(path):
    try:
        with open(path, "rb") as f:
            raw = f.read(262145)
        if len(raw) > 262144:
            raise ValueError("record_too_large")
        return json.loads(raw)
    except FileNotFoundError:
        return None


def machine():
    # Compare observed kernel boot identities, not configured host labels or socket paths.
    if sys.platform == "linux":
        raw = Path("/proc/sys/kernel/random/boot_id").read_bytes()
    elif sys.platform == "darwin":
        raw = subprocess.check_output(["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"], timeout=2)
    else:
        raise ValueError("unsupported_platform")
    return hashlib.sha256(raw.strip()).hexdigest()


def read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError("regular_file_required")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError("input_too_large")
    return data


def osc(state, config):
    # Rex's documented key:value OSC 7501 form; msg is base64 UTF-8.
    title = base64.b64encode(config["title"].encode()).decode()
    with contextlib.suppress(OSError):
        os.write(1, ("\x1b]7501;state=" + state + ":app=" + config["app"] + ":title=" + title + ":msg=" + title + "\x1b\\").encode())


def supervise(root):
    """Runs only as the actual attached terminal command, never from the controller."""
    root = Path(root)
    config = load(root / "request.json")
    identity = dict(machine=machine(), session_id=os.environ.get("REX_SESSION"), block_id=os.environ.get("REX_BLOCK"))
    save(root / "ready.json", identity)
    # A lost create ACK must not start argv. No permission file means no execution.
    end = time.monotonic() + config["startup_ms"] / 1000
    while not (root / "permit.json").exists():
        if STOP or (root / "cancel.json").exists() or time.monotonic() >= end:
            return 125
        time.sleep(.02)
    if load(root / "permit.json") != identity:
        return 125
    osc("working", config)
    seen = dict(stdout=0, stderr=0)
    retained = dict(stdout=0, stderr=0)
    sinks = {s: open(root / (s + ".prefix"), "wb", buffering=0) for s in seen}
    full = {s: open(root / (s + ".full"), "wb", buffering=0) for s in seen} if config["full_output"] else {}
    for f in [*sinks.values(), *full.values()]:
        os.fchmod(f.fileno(), 0o600)
    result = dict(exit_code=None, signal=None, launch_error=None, stop_reason=None,
                  stdout_seen=0, stderr_seen=0, pipes_eof=False, group_term="not_requested", group_kill="not_requested")
    child = None
    selector = selectors.DefaultSelector()
    start = time.monotonic()
    stop_at = None
    child_ended = None
    file_bytes = 0
    watcher = None
    def group(sig):
        try:
            os.killpg(child.pid, sig)
            return "sent"
        except ProcessLookupError:
            return "not_found"
        except PermissionError:
            return "permission_denied_or_zombie_only"
    def exited():
        # Do not reap the group leader before the final group signal. Its reserved PID
        # prevents reuse as an unrelated process group during output drain/cleanup.
        if hasattr(os, "waitid") and hasattr(os, "WNOWAIT"):
            return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
        return bool(watcher.control([], 1, 0))
    try:
        env = config["env"]
        env.update(REX_SESSION=identity["session_id"], REX_BLOCK=identity["block_id"])
        with open(root / "stdin", "rb") as source:
            child = subprocess.Popen(config["argv"], cwd=config["cwd"], env=env, stdin=source,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        if not (hasattr(os, "waitid") and hasattr(os, "WNOWAIT")):
            watcher = select.kqueue()  # Older Mac Python exposes kqueue, not waitid.
            watcher.control([select.kevent(child.pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE, fflags=select.KQ_NOTE_EXIT)], 0, 0)
        save(root / "started.json", dict(pid=child.pid, **identity))
        for s in seen:
            pipe = getattr(child, s)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, s)
        while True:
            now = time.monotonic()
            cancel = load(root / "cancel.json")
            reason = ("cancel_requested" if STOP or cancel else
                      "deadline_exceeded" if config["timeout_ms"] is not None and now - start >= config["timeout_ms"] / 1000 else None)
            if reason and stop_at is None:
                result["stop_reason"] = reason
                stop_at = now
                result["group_term"] = group(signal.SIGTERM)
            if child_ended is None and exited():
                child_ended = now
            if stop_at is not None and now - stop_at >= .25 and result["group_kill"] == "not_requested":
                result["group_kill"] = group(signal.SIGKILL)
            for key, unused in selector.select(.02):
                chunk = os.read(key.fileobj.fileno(), 16384)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                stream = key.data
                seen[stream] += len(chunk)
                n = min(len(chunk), config["max_bytes"] - sum(retained.values()))
                sinks[stream].write(chunk[:n])
                retained[stream] += n
                if full:
                    keep = min(len(chunk), FILE_LIMIT - file_bytes)
                    full[stream].write(chunk[:keep])
                    file_bytes += keep
                    if keep < len(chunk) and stop_at is None:
                        result["stop_reason"] = "full_output_limit_exceeded"
                        stop_at = time.monotonic()
                        result["group_term"] = group(signal.SIGTERM)
                # Rendering is best effort: a blocked/disconnected display cannot deadlock collection.
                try:
                    os.write(1, chunk)
                except (BlockingIOError, BrokenPipeError, OSError):
                    pass
            if child_ended is not None and (not selector.get_map() or now - child_ended >= .5):
                # Same-group descendants are scoped cleanup, not a whole-tree assertion.
                if result["group_term"] == "not_requested":
                    result["group_term"] = group(signal.SIGTERM)
                if result["group_kill"] == "not_requested":
                    result["group_kill"] = group(signal.SIGKILL)
                result["pipes_eof"] = not selector.get_map()
                break
    except (OSError, ValueError, TypeError) as exc:
        result["launch_error"] = str(exc)[:600]
    finally:
        if child is not None:
            if result["group_term"] == "not_requested":
                result["group_term"] = group(signal.SIGTERM)
            if result["group_kill"] == "not_requested":
                result["group_kill"] = group(signal.SIGKILL)
            try:
                code = child.wait(timeout=.5)
                result["exit_code"] = code if code >= 0 else None
                result["signal"] = -code if code < 0 else None
            except subprocess.TimeoutExpired:
                pass  # Unknown actual child exit, never synthetic signal evidence.
        if watcher is not None:
            watcher.close()
        for key in list(selector.get_map().values()):
            key.fileobj.close()
        selector.close()
        for f in [*sinks.values(), *full.values()]:
            f.close()
    result.update(stdout_seen=seen["stdout"], stderr_seen=seen["stderr"], elapsed_ms=int((time.monotonic() - start) * 1000))
    osc("done" if result["exit_code"] == 0 and not result["stop_reason"] else "error", config)
    save(root / "result.json", result)
    return 0


def invoke(runtime, pin, args, budget=5, interruptible=False):
    """Bounded receipts/diagnostics, one mutation attempt; no retry on lost evidence."""
    env = dict(os.environ)
    for key in ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT"):
        env.pop(key, None)
    command = [runtime] + (["--rex", pin] if pin else []) + args
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(command, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        end = time.monotonic() + budget
        while child.poll() is None and time.monotonic() < end and not (interruptible and STOP):
            time.sleep(.02)
        if child.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        out.seek(0)
        raw = out.read(262145)
        err.seek(0)
        diagnostics = base64.b64encode(err.read(4096)).decode()
    try:
        packet = json.loads(raw) if len(raw) <= 262144 else None
    except (ValueError, UnicodeError):
        packet = None
    return dict(code=child.returncode, receipt=packet, backend_stderr_base64=diagnostics)


def capture(root, stream, maximum, result):
    path = root / (stream + ".prefix")
    data = read_regular(path, maximum) if path.exists() else b""
    try:
        text = data.decode("utf-8")
        encoding = "utf8"
    except UnicodeError:
        text = base64.b64encode(data).decode()
        encoding = "base64"
    seen = result.get(stream + "_seen") if result else None
    return dict(encoding=encoding, content=text, retained_bytes=len(data), bytes_seen=seen,
                complete=bool(result and result["pipes_eof"] and seen == len(data)))


def forget_job(runtime, pin, packet):
    jobs = packet.get("jobs")
    if not jobs or jobs["generation"] is None or jobs["forget_outcome"] != "not_attempted":
        return
    jobs["forget_outcome"] = "uncertain"
    try:
        listing = invoke(runtime, pin, ["jobs", "list", "--registry", jobs["registry"]])
        jobs["lookup"] = listing
        if listing["code"] or not listing["receipt"] or listing["receipt"].get("kind") != "jobs_list":
            jobs["forget_outcome"] = "lookup_failed"
            return
        entry = next((e for e in listing["receipt"]["entries"] if e["socket"] == packet["server"][7:]
                      and e["session_id"] == packet["session_id"] and e["block_id"] == packet["created"]["block_id"]), None)
        if entry is None:
            jobs["forget_outcome"] = "registration_absent"
            return
        transport = invoke(runtime, pin, ["jobs", "forget", "--registry", jobs["registry"],
                           "--socket", packet["server"][7:], "--session", packet["session_id"],
                           "--block", packet["created"]["block_id"], "--owner", jobs["owner"],
                           "--generation", str(entry["generation"]), "--reason", "run-visible ended; exit evidence is separate"])
        jobs["forget"] = transport
        jobs["forget_outcome"] = "forgotten" if transport["code"] == 0 and transport["receipt"] and transport["receipt"].get("outcome") == "record_forgotten" else "failed_or_uncertain"
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        jobs.update(forget_outcome="failed_or_uncertain", failure_reason=str(exc)[:600])


class VisibleChannel(ChannelService):
    """Foreground, send-only authority; the caller owns the directory and receipts."""
    reserve_refusal = True

    def __init__(self, directory, runtime, pin, options):
        self.fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.listener = None
        self.log = None
        self.created = []
        self.closed = False
        self.count = 0
        self.next_accept = 0
        self.policy = dict(max_requests=256, grants=["send"])
        self.launch_id, self.token = secrets.token_hex(16), secrets.token_hex(32)
        self.seen = set()
        self.runtime, self.pin, self.options = runtime, pin, options
        self.path, self.handle = str(Path(directory) / "channel.sock"), str(Path(directory) / "handle.json")
        self.expires = int(time.time() * 1000) + 86400000
        self.deadline = time.monotonic() + 86400
        self.summary = dict(directory=directory, handle=self.handle, grants=["send"], expires_at=self.expires,
                            receipts_path=str(Path(directory) / "receipts.jsonl"), count=0, outcomes={}, requests=[])
        try:
            info = os.fstat(self.fd)
            channel_require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, "channel_directory_requires_owned_0700")
            channel_require(not os.listdir(self.fd), "channel_directory_must_be_empty")
            channel_require(len(os.fsencode(self.path)) < 100, "channel_socket_path_too_long")
            self.log = os.open("receipts.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.bind(self.path)
            self.created.append("channel.sock")
            os.chmod(self.path, 0o600)
            self.listener.listen(4)
            self.listener.settimeout(.05)
            handle = dict(schema_version=1, launch_id=self.launch_id, token=self.token, socket=self.path,
                          expires_at=self.expires, grants=["send"])
            descriptor = os.open("handle.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            self.created.append("handle.json")
            with os.fdopen(descriptor, "w") as f:
                json.dump(handle, f)
            current = os.stat(directory, follow_symlinks=False)
            channel_require((info.st_dev, info.st_ino) == (current.st_dev, current.st_ino), "channel_directory_replaced")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.listener is not None:
            self.listener.close()
        for name in self.created:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=self.fd)
        if self.log is not None:
            os.close(self.log)
        os.close(self.fd)

    def revoked(self):
        self.summary["status"] = "revoked"

    def dispatch(self, request):
        event_id, operation = channel_request(request, self.launch_id, self.token, ["send"])
        channel_require(event_id not in self.seen, "channel_request_already_attempted_no_retry")
        self.seen.add(event_id)  # Admission precedes the only delivery attempt; never replay after a lost ACK.
        o = self.options
        # Keep message data outside the read-only channel mount, in controller-owned storage.
        with tempfile.TemporaryDirectory(prefix="teerex-channel-send-") as temp:
            message_path = Path(temp) / "message"
            private_write(message_path, request["body"].encode())
            transport = invoke(self.runtime, self.pin, ["send", "--socket", o.socket,
                               "--session", o.report_to_session, "--block", o.report_to_block,
                               "--from", o.app, "--message-file", str(message_path)], budget=120, interruptible=True)
        packet = transport["receipt"]
        outcome = packet.get("outcome", "uncertain") if isinstance(packet, dict) else "uncertain"
        delivered = transport["code"] == 0 and outcome == "events_acknowledged"
        return transport["code"], dict(schema_version=1, kind="agent_channel_result", request_id=event_id,
                                      outcome="transport_acknowledged" if delivered else outcome,
                                      retry_safe=False, client_exit=transport["code"], receipt=packet)

    def record_request(self, request, code, result):
        # Log bounded fields only; never serialize the capability token or untrusted error text.
        packet = result.get("receipt")
        outcome = packet.get("outcome", "uncertain") if isinstance(packet, dict) else "refused" if result.get("failure_reason") else "uncertain"
        if code == 0 and outcome == "events_acknowledged":
            outcome = "delivered"
        body = request.get("body")
        body = body if isinstance(body, str) and len(body.encode("utf-8", errors="surrogatepass")) <= 32768 else None
        event_id = request.get("request_id")
        event_id = event_id if isinstance(event_id, str) and re.fullmatch(r"[0-9a-f]{32}", event_id) else None
        operation = request.get("operation")
        operation = operation if operation in ("send", "ack", "stop") else None
        to = request.get("to")
        to = "report_to" if to == "report-to" else "starter" if to == "starter" else None
        reason = result.get("failure_reason") or (packet.get("failure_reason") if isinstance(packet, dict) else None)
        line = dict(schema_version=1, at_unix_ms=int(time.time() * 1000), request_id=event_id,
                    operation=operation, to=to, body=body, outcome=outcome, failure_reason=reason)
        raw = json.dumps(line, ensure_ascii=True).encode() + b"\n"
        channel_require(os.write(self.log, raw) == len(raw), "channel_receipt_short_write")
        os.fsync(self.log)
        self.summary["count"] += 1
        totals = self.summary["outcomes"]
        totals[outcome] = totals.get(outcome, 0) + 1
        self.summary["requests"].append(dict(request_id=event_id, operation=operation, outcome=outcome))


def controller(runtime, source, args):
    global RECEIPT, BROKER
    parser = argparse.ArgumentParser(prog="teerex run-visible", description=(
        "Run literal noninteractive argv in a verified visible Rex terminal on this command host. "
        "API13 only; Python3.9+. No retries, autostart, implicit shell, hidden worker or daemon. "
        "Child stdout/stderr are pipes teed live to the terminal, not TTYs. Exact env replaces inherited env "
        "except actual REX_SESSION/REX_BLOCK and opted-in AGENT_CHANNEL/LC_AGENT_CHANNEL. Stdin is a regular file (max1MiB) or /dev/null. "
        "Closing a pane does not prove descendant/remote death; SIGKILL/controller loss cannot guarantee cleanup."))
    for name in ("socket", "session", "cwd", "env-file", "stdin-file", "app", "title"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--registry", help="opt-in existing private jobs registry; requires --owner and --purpose")
    parser.add_argument("--owner", help="jobs responsibility label (requires --registry and --purpose)")
    parser.add_argument("--purpose", help="jobs purpose text (requires --registry and --owner)")
    parser.add_argument("--channel-dir", help="opt-in caller-created empty owned0700 directory; send-only socket, handle and persistent receipts.jsonl")
    parser.add_argument("--report-to-session", help="fixed channel destination session; requires --channel-dir and --report-to-block")
    parser.add_argument("--report-to-block", help="fixed channel destination block; starter is the same address")
    parser.add_argument("--layout", choices=("tab", "tiled"), default="tab")
    parser.add_argument("--anchor")
    parser.add_argument("--direction", choices=("left", "right", "up", "down"))
    parser.add_argument("--ratio", type=float)
    deadline = parser.add_mutually_exclusive_group()
    deadline.add_argument("--timeout-ms", type=int, default=None, help="execution deadline100..86400000ms, default10000; starts after verified placement")
    deadline.add_argument("--no-deadline", action="store_true", help="wait until actual child exit or INT/TERM; startup budget unchanged")
    parser.add_argument("--startup-ms", type=int, default=10000, help="placement/identity gate1000..60000ms; separate from execution")
    parser.add_argument("--max-bytes", type=int, default=4096, help="combined raw prefix retention1..65536 bytes")
    parser.add_argument("--output-dir", help="NEW absolute private directory; retains full separate raw files up to64MiB combined, caller deletes")
    parser.add_argument("--keep-open", action="store_true", help="retain exited pane; cancellation/deadline still requests owned-pane close")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    o = parser.parse_args(args)
    o.timeout_ms = None if o.no_deadline else (o.timeout_ms if o.timeout_ms is not None else 10000)
    if not o.argv or o.argv[0] != "--" or len(o.argv) < 2 or not o.argv[1]:
        parser.error("-- and nonempty argv required")
    for name in ("socket", "cwd", "env_file", "stdin_file", "output_dir", "registry", "channel_dir"):
        path = getattr(o, name)
        if path is not None and not os.path.isabs(path):
            parser.error(name + " must be absolute")
    if any(v is not None for v in (o.registry, o.owner, o.purpose)) and not all(v is not None for v in (o.registry, o.owner, o.purpose)):
        parser.error("--registry, --owner and --purpose require all three or none")
    if any(v is not None for v in (o.channel_dir, o.report_to_session, o.report_to_block)):
        if not all(v is not None for v in (o.channel_dir, o.report_to_session, o.report_to_block)):
            parser.error("--channel-dir, --report-to-session and --report-to-block require all three or none")
        for kind, value in (("session", o.report_to_session), ("block", o.report_to_block)):
            if not re.fullmatch(kind + r":[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
                parser.error("full lowercase channel destination IDs required")
    if not re.fullmatch(r"session:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", o.session):
        parser.error("full lowercase session ID required")
    if (o.layout == "tiled") != bool(o.anchor) or (o.layout == "tab" and (o.direction or o.ratio is not None)):
        parser.error("tiled requires anchor; tab forbids anchor/direction/ratio")
    if not ((o.timeout_ms is None or 100 <= o.timeout_ms <= 86400000) and 1000 <= o.startup_ms <= 60000 and 1 <= o.max_bytes <= 65536):
        parser.error("limit out of range")
    if not re.fullmatch(r"[a-zA-Z0-9_.+-]{1,32}", o.app) or not (1 <= len(o.title.encode()) <= 128) or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in o.title):
        parser.error("invalid app or title")
    request_env = json.loads(read_regular(o.env_file, 65536))
    if not isinstance(request_env, dict) or any(not isinstance(k, str) or not k or "=" in k or "\0" in k or
            not isinstance(v, str) or "\0" in v for k, v in request_env.items()) or any(k in request_env for k in ("REX_SESSION", "REX_BLOCK")):
        parser.error("env-file must be a string map; REX_SESSION/BLOCK are reserved actual metadata")
    if not Path(o.cwd).is_dir():
        raise ValueError("cwd_not_directory_on_command_host")
    stdin = b"" if o.stdin_file == "/dev/null" else read_regular(o.stdin_file, INPUT_LIMIT)
    pin = os.environ.get("TEEREX_INTERNAL_REX") or os.environ.get("TEEREX_REX")
    # Use the public pinned Rex command for version refusal before any creation.
    rex = pin or shutil.which("rex")
    if not rex:
        raise ValueError("rex_executable_missing")
    v = invoke(rex, None, ["--autostart=false", "--server", "unix://" + o.socket, "api", "call", "server.version", "{}"])
    version = v["receipt"]
    if v["code"] or not isinstance(version, dict) or version.get("api_revision") != 13:
        raise ValueError("run_visible_requires_observed_api13")
    if STOP:
        print(json.dumps(dict(schema_version=1, kind="run_visible_result", outcome="cancel_requested",
                              success=False, cancellation_signal=STOP, retry_safe=False)), flush=True)
        return 128 + STOP
    identity = machine()
    if o.channel_dir:
        BROKER = VisibleChannel(o.channel_dir, runtime, pin, o)
        request_env.update(AGENT_CHANNEL=BROKER.handle, LC_AGENT_CHANNEL=BROKER.handle)
    if o.output_dir:
        root = Path(o.output_dir)
        root.mkdir(mode=0o700)
    else:
        root = Path(tempfile.mkdtemp(prefix="teerex-visible-"))
    config = dict(argv=o.argv[1:], cwd=o.cwd, env=request_env, timeout_ms=o.timeout_ms, startup_ms=o.startup_ms,
                  max_bytes=o.max_bytes, full_output=bool(o.output_dir), app=o.app, title=o.title)
    if len(json.dumps(config).encode()) > 131072:
        root.rmdir()
        raise ValueError("encoded_request_exceeds_128KiB")
    save(root / "request.json", config)
    private_write(root / "stdin", stdin)
    private_write(root / "runner.py", source.encode())
    common = ["--socket", o.socket, "--session", o.session]
    open_args = ["surfaces", "open", *common, "--layout", o.layout, "--label", o.title]
    if o.anchor:
        open_args += ["--anchor", o.anchor]
    if o.direction:
        open_args += ["--direction", o.direction]
    if o.ratio is not None:
        open_args += ["--ratio", str(o.ratio)]
    packet = dict(schema_version=1, kind="run_visible_result", execution_location="visible_terminal_command_host",
                  server="unix://" + o.socket, session_id=o.session, source=version, retry_safe=False,
                  painted_visibility="not_assessed", task_completion="not_assessed", all_descendants_verified_gone=False,
                  storage_dir=str(root), storage_retained=True, full_output_requested=bool(o.output_dir),
                  capture_scope="separate_raw_pipes_teed_to_terminal", retention_policy="combined_first_arrivals_per_stream_prefix",
                  exit_report=None, outcome="uncertain", success=False, created=None, placement=None,
                  cleanup=dict(scope="identified_owned_pane", attempted=False, block_absence_verified=False),
                  limits=dict(startup_ms=o.startup_ms, execution_ms=o.timeout_ms, max_bytes=o.max_bytes, full_output_bytes=FILE_LIMIT))
    if o.no_deadline:
        packet["timeout_ms"] = None
    if o.registry:
        packet["jobs"] = dict(registry=o.registry, owner=o.owner, purpose=o.purpose, track_outcome="not_attempted", generation=None, forget_outcome="not_attempted")
    if BROKER is not None:
        packet["channel"] = BROKER.summary
    RECEIPT = packet
    started = time.monotonic()
    end = started + o.startup_ms / 1000
    result = None
    bid = None
    permitted = False
    reason = None
    placement = invoke(runtime, pin, open_args + ["--", sys.executable, str(root / "runner.py"), "_supervise", str(root)])
    packet["placement"] = placement
    receipt = placement["receipt"] or {}
    created = receipt.get("created")
    if created:
        packet["created"] = created
        bid = created["block_id"]
    save(root / "controller.json", packet)
    if placement["code"] == 0 and receipt.get("outcome") == "created_and_verified" and bid:
        while time.monotonic() < end and not STOP:
            ready = load(root / "ready.json")
            if ready:
                packet["pane_identity_report"] = ready
                if ready != dict(machine=identity, session_id=o.session, block_id=bid):
                    reason = "foreign_pane_host_or_identity_refused"
                else:
                    if o.registry:
                        jobs = packet["jobs"]
                        # Jobs review is metadata only; the helper enforces its independent execution budget.
                        deadline_ms = int(time.time() * 1000) + (o.timeout_ms if o.timeout_ms is not None else 30 * 86400000)
                        jobs["track_outcome"] = "uncertain"
                        tracked = invoke(runtime, pin, ["jobs", "track", "--registry", o.registry, *common, "--block", bid,
                                         "--owner", o.owner, "--kind", "command", "--purpose", o.purpose,
                                         "--deadline-unix-ms", str(deadline_ms), "--cleanup", "manual"])
                        jobs["track"] = tracked
                        entry = tracked["receipt"].get("entry") if tracked["receipt"] else None
                        if tracked["code"] != 0 or not entry or tracked["receipt"].get("outcome") != "verified":
                            jobs["track_outcome"] = "failed_or_uncertain"
                            reason = "jobs_tracking_failed"
                        else:
                            jobs.update(track_outcome="tracked", generation=entry["generation"])
                    if not reason and not STOP:
                        save(root / "permit.json", ready)
                        permitted = True
                break
            time.sleep(.02)
        if not permitted and reason is None:
            reason = "pane_identity_unavailable_or_foreign_host"
    else:
        reason = "creation_or_placement_uncertain"
    if permitted:
        end = None if o.timeout_ms is None else time.monotonic() + o.timeout_ms / 1000 + 1
        while (end is None or time.monotonic() < end) and not STOP:
            result = load(root / "result.json")
            if result:
                break
            if BROKER is not None:
                BROKER.service()
            else:
                time.sleep(.02)
        if result is None:
            reason = "cancel_requested" if STOP else "controller_deadline_exceeded"
    if BROKER is not None:
        BROKER.close()
        BROKER.revoked()
    if STOP:
        reason = "cancel_requested"
    if reason:
        save(root / "cancel.json", dict(signal=STOP or signal.SIGTERM, reason=reason))
        # Allow in-pane scoped TERM/KILL/result collection before closing its PTY.
        drain = time.monotonic() + 1
        while permitted and result is None and time.monotonic() < drain:
            result = load(root / "result.json")
            if result is None:
                time.sleep(.02)
    if result:
        packet["exit_report"] = result
        reason = reason or result["stop_reason"]
        packet["outcome"] = reason or ("launch_error" if result["launch_error"] else "exit_reported")
    else:
        packet["outcome"] = reason or "result_unknown"
    packet["cancellation_signal"] = STOP or None
    close = not o.keep_open or reason is not None or (result and result["stop_reason"])
    if bid and close:
        packet["cleanup"]["attempted"] = True
        save(root / "controller.json", packet)
        closed = invoke(runtime, pin, ["surfaces", "close", *common, "--pane", bid])
        packet["cleanup"]["transport"] = closed
        packet["cleanup"]["block_absence_verified"] = bool(closed["code"] == 0 and closed["receipt"] and closed["receipt"].get("block_absence_verified"))
    packet["pane_retained_on_request"] = bool(bid and not close)
    for stream in ("stdout", "stderr"):
        packet[stream] = capture(root, stream, o.max_bytes, result)
        packet[stream]["full_path"] = str(root / (stream + ".full")) if o.output_dir else None
        packet[stream]["full_complete"] = bool(o.output_dir and result and result["pipes_eof"] and result["stop_reason"] != "full_output_limit_exceeded")
    cleanup_ok = packet["pane_retained_on_request"] or packet["cleanup"]["block_absence_verified"]
    packet["success"] = bool(result and packet["outcome"] == "exit_reported" and result["exit_code"] == 0 and cleanup_ok)
    forget_job(runtime, pin, packet)
    packet["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    save(root / "controller.json", packet)
    # Unknown create/close/result outcomes keep all evidence; never remove files an uncertain pane may need.
    if not o.output_dir and result and cleanup_ok:
        shutil.rmtree(root)
        packet["storage_retained"] = False
    code = 128 + STOP if STOP else 124 if "deadline" in packet["outcome"] else 0 if packet["success"] else 1
    save_receipt = json.dumps(packet, ensure_ascii=True)
    print(save_receipt, flush=True)
    return code


def main():
    signal.signal(signal.SIGINT, stopped)
    signal.signal(signal.SIGTERM, stopped)
    if len(sys.argv) == 3 and sys.argv[1] == "_supervise":
        # Set display fd nonblocking before any output; keep collection independent of client consumption.
        os.set_blocking(1, False)
        return supervise(sys.argv[2])
    try:
        return controller(sys.argv[1], sys.argv[2], sys.argv[3:])
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        if BROKER is not None:
            BROKER.close()
            BROKER.revoked()
        packet = RECEIPT or dict(schema_version=1, kind="run_visible_result", outcome="refused", retry_safe=False)
        if BROKER is not None:
            packet["channel"] = BROKER.summary
        packet.update(success=False, failure_reason=str(exc)[:600])
        if RECEIPT is not None:
            packet["outcome"] = "controller_error_unknown"
            with contextlib.suppress(OSError, ValueError):
                save(Path(packet["storage_dir"]) / "cancel.json", dict(reason="controller_error", signal=signal.SIGTERM))
            if packet["created"] and not packet["cleanup"]["attempted"]:
                packet["cleanup"]["attempted"] = True
                with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
                    pin = os.environ.get("TEEREX_INTERNAL_REX") or os.environ.get("TEEREX_REX")
                    packet["cleanup"]["transport"] = invoke(sys.argv[1], pin, ["surfaces", "close", "--socket",
                        packet["server"][7:], "--session", packet["session_id"], "--pane", packet["created"]["block_id"]])
                # Keep unknown: this exception path did not finish verifying the close receipt.
        forget_job(sys.argv[1], os.environ.get("TEEREX_INTERNAL_REX") or os.environ.get("TEEREX_REX"), packet)
        print(json.dumps(packet, ensure_ascii=True), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
