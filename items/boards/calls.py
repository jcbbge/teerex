"""Per-invocation foreground supervisor and private call history. No argv payloads."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import time

LIMIT = 1048576
ID = re.compile(r"^(session|block):[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
# Only known command words may enter the log. Unknown argv can be a secret.
VERBS = set("targets resolve exec surfaces open inspect rename move focus close palette boards inbox fleet probe state seat register clear append ask agents launch profiles shell ack deliver stop present exited channel spawn recovery snapshot restore update install rollback run-visible observe compare watch run offstage doctor send jobs adapters maneuver-check filter forget report remap-preview remap-apply try-route list plan apply --version --help".split())


def directory():
    path = Path(os.environ.get("TEEREX_CALL_LOG_DIR", str(Path.home() / ".local/state/teerex/calls")))
    if not path.is_absolute():
        raise ValueError("absolute call log directory required")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private(fd, True)
    except BaseException:
        os.close(fd)
        raise
    return fd


def private(fd, directory=False):
    s = os.fstat(fd)
    if (s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != (0o700 if directory else 0o600)
            or not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink == 1)):
        raise ValueError("call log requires owned private directory/files")


@contextlib.contextmanager
def locked():
    fd = directory()
    lock = None
    try:
        lock = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
        private(lock)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield fd
    finally:
        if lock is not None:
            os.close(lock)
        os.close(fd)


def append(record):
    raw = (json.dumps(record, ensure_ascii=True) + "\n").encode()
    with locked() as directory_fd:
        fd = os.open("calls.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory_fd)
        try:
            private(fd)
            if os.fstat(fd).st_size + len(raw) > LIMIT:
                # Segments are immutable; disk history is retained, never silently deleted.
                name = "calls-%020d-%d.jsonl" % (time.time_ns(), os.getpid())
                os.rename("calls.jsonl", name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                os.close(fd)
                fd = os.open("calls.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(os.dup(fd), "ab") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.fsync(directory_fd)
        finally:
            os.close(fd)


def recent(limit):
    result = []
    with locked() as directory_fd:
        names = sorted(n for n in os.listdir(directory_fd) if re.fullmatch(r"calls-[0-9]{20}-[0-9]+\.jsonl", n))
        names.append("calls.jsonl")
        for name in reversed(names):
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            except FileNotFoundError:
                continue
            try:
                private(fd)
                with os.fdopen(os.dup(fd), "rb") as f:
                    raw = f.read(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise ValueError("call segment exceeds bound")
                result.extend(json.loads(line) for line in reversed(raw.splitlines()))
            finally:
                os.close(fd)
            if len(result) >= limit:
                break
    return result[:limit]


def metadata(args):
    words, target = [], {}
    if args == ["--version"]:
        return dict(verb="--version", subverb=None, target={})
    if args == ["--help"]:
        return dict(verb="--help", subverb=None, target={})
    i = 0
    while i < len(args):
        word = args[i]
        if word == "--":
            break
        if word in ("--rex", "--config", "--host") and not words:
            i += 2
            continue
        if word.startswith("--"):
            if word in ("--session", "--block") and i + 1 < len(args) and ID.fullmatch(args[i + 1]):
                target[word[2:] + "_id"] = args[i + 1]
            if word == "--socket" and i + 1 < len(args) and os.path.isabs(args[i + 1]):
                target["server"] = "unix://" + args[i + 1]
            i += 2
            continue
        if word in VERBS and len(words) < 2:
            words.append(word)
        elif not words:
            words.append("unknown")
        i += 1
    return dict(verb=words[0] if words else "help", subverb=words[1] if len(words) > 1 else None, target=target)


def supervise(executable, version, args):
    started = time.monotonic()
    record = dict(schema_version=1, at=int(time.time()*1000), host=socket.gethostname(), version=version,
                  pid=os.getpid(), caller_pid=os.getppid(), **metadata(args))
    # Supplied names are claims; unbounded environment and parent argv never enter history.
    name = os.environ.get("AGENT_NAME", os.environ.get("LC_AGENT_NAME", ""))
    record["caller"] = name if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name) else None
    env = dict(os.environ, TEEREX_CALL_LOG_CHILD=str(os.getpid()))
    try:
        if sys.platform.startswith("linux"):
            record["parent_program"] = Path("/proc/%d/comm" % os.getppid()).read_text().strip()[:128]
        else:
            record["parent_program"] = os.path.basename(subprocess.check_output(["/bin/ps", "-p", str(os.getppid()), "-o", "comm="], timeout=1).decode().strip())[:128]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        record["parent_program"] = None
    # Only board renderers and explicit PTY transports need stdout to remain a TTY.
    # Other leaves return receipts; tee those even when called from a terminal.
    start = 0
    while start < len(args) and args[start] in ("--rex", "--config", "--host"):
        start += 2
    end = start
    while end < len(args) and not args[end].startswith("--"):
        end += 1
    leaf = tuple(args[start:end])
    interactive = (leaf in (("boards", "inbox"), ("boards", "fleet"), ("boards", "calls"), ("inbox",), ("fleet",))
                   and "--once" not in args and "--help" not in args) or "--tty" in args
    child = subprocess.Popen([executable, *args], env=env,
                             stdout=None if interactive and sys.stdout.isatty() else subprocess.PIPE)
    def forward(sig, _frame):
        try:
            child.send_signal(sig)
        except ProcessLookupError:
            pass
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, forward)
    tail = bytearray()
    if child.stdout is not None:
        while True:
            data = os.read(child.stdout.fileno(), 65536)
            if not data:
                break
            try:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except BrokenPipeError:
                pass
            tail.extend(data)
            if len(tail) > LIMIT:
                del tail[:-LIMIT]
    code = child.wait()
    code = code if code >= 0 else 128 - code
    if not tail and code in (130, 143) and child.stdout is not None:
        # A signal can arrive before an exec-based leaf installs its own handlers.
        packet = dict(schema_version=1, kind="command_result", outcome="cancelled",
                      terminal_input_attempted=None, retry_safe=False,
                      recovery="inspect_target_before_retry")
        tail.extend(json.dumps(packet).encode() + b"\n")
        try:
            sys.stdout.buffer.write(tail)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            pass
    outcome, failure = ("completed" if code == 0 else "nonzero_exit"), None
    # Only allowlisted status values are copied. Error strings can contain payloads.
    candidates = [bytes(tail), *reversed(tail.splitlines())]
    for candidate in candidates:
        try:
            receipt = json.loads(candidate)
            value = receipt.get("outcome")
            if value in ("events_acknowledged", "backend_error", "inbox_refused", "cancel_requested", "recorded", "acknowledged", "uncertain", "refused", "refused_or_unknown", "deadline_exceeded", "cancelled", "not_registered", "observed", "delivered_history_failed"):
                outcome = value
            reason = receipt.get("failure_reason", receipt.get("reason"))
            if reason is not None:
                failure = reason if reason in ("enter_call_failed", "paste_call_failed", "rex_transport_incomplete", "stdin_EOF_deadline_no_record_saved", "inbox_deadline_before_save_no_record_saved") else "reported_by_command"
            break
        except (ValueError, AttributeError):
            continue
    record["outcome_evidence"] = "receipt_or_exit" if child.stdout is not None else "exit_only"
    record.update(outcome=outcome, failure_reason=failure, elapsed_ms=round((time.monotonic()-started)*1000), exit=code)
    try:
        append(record)
    except (OSError, ValueError) as e:
        # Delivery already happened; do not turn a logging failure into permission to retry.
        print("teerex: call history unavailable (" + type(e).__name__ + "); command exit preserved", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(supervise(sys.argv[1], sys.argv[2], sys.argv[3:]))
