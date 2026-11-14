"""Private start/end history; helpers log in their existing process. No supervisor."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

LIMIT = 1048576


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
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        if lock is not None:
            os.close(lock)
        os.close(fd)


def append(record):
    # No arbitrary caller strings survive the append boundary, even for helper callers.
    record = json.loads(json.dumps(record))
    caller = record.get("caller")
    if isinstance(caller, dict):
        for key in ("via", "agent_name"):
            value = caller.get(key)
            if isinstance(value, str) and re.match(r"(?:sk-|gh[pousr]_|github_pat_|xox[abprs]-|ey[jJ])", value) and len(value) >= 20:
                caller[key] = None
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
            os.write(fd, raw)  # one O_APPEND write, never replay an uncertain write

        finally:
            os.close(fd)



def recent(limit):
    starts, ends = {}, {}
    with locked() as directory_fd:
        names = sorted(n for n in os.listdir(directory_fd) if re.fullmatch(r"calls-[0-9]{20}-[0-9]+\.jsonl", n))
        names.append("calls.jsonl")
        # Bound work as well as output. Older starts outside the last 8 MiB remain historical.
        for name in reversed(names[-8:]):
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            except FileNotFoundError:
                continue
            try:
                private(fd)
                with os.fdopen(os.dup(fd), "rb") as f:
                    raw = f.read()
                for line in reversed(raw.splitlines()):
                    try:
                        record = json.loads(line)
                        key = (record["pid"], record["start_at"])
                        if record.get("phase") == "start":
                            starts.setdefault(key, record)
                        elif record.get("phase") == "end":
                            ends.setdefault(key, record)
                    except (ValueError, KeyError, TypeError):
                        continue  # A failed partial append is unknown, never an invented end.
            finally:
                os.close(fd)
    rows = []
    for key, record in starts.items():
        end = ends.get(key)
        code = end.get("exit") if end else None
        rows.append(dict(record, exit=code, elapsed_ms=end.get("elapsed_ms") if end else None,
                         outcome="unknown" if end is None else "completed" if code == 0 else "nonzero_exit"))
    rows.sort(key=lambda row: row["start_at"], reverse=True)
    return rows[:limit]


def resolved_target(server):
    """Complete the existing native shape with the resolver's selected endpoint.

    No new shape or value is collected here. Failed/unfinished resolution stays
    explicitly unknown, and never changes the selected command's behavior.
    """
    try:
        import teerex_friction as friction
        import hashlib
        import hmac
        ident = globals().get("_active_call_id")
        if ident is None:
            return
        with locked() as fd:
            c = friction.consent(fd)
            now = int(time.time()*1000)
            if not c or not c["enabled_at"] <= now < c["expires_at"]:
                return
            salt = friction.read(fd,"friction-salt",32)
            if len(salt) != 32:
                return
            for name,raw in friction.segments(fd):
                lines=[];changed=False
                for line in raw.splitlines(keepends=True):
                    try:
                        record=json.loads(line)
                        if record["call_id"]==ident and record["context"].get("target_unknown"):
                            via=record["caller"].get("via")
                            if c["scope"]!="all" and via not in c["scope"][8:].split(","):
                                return
                            record["context"]["server_key"]="k:"+hmac.new(salt,server.encode(),hashlib.sha256).hexdigest()[:16]
                            record["context"]["target_unknown"]=False
                            line=friction.encode(record);changed=True
                    except (ValueError,KeyError,TypeError,AttributeError):
                        pass
                    lines.append(line)
                if changed:
                    rewritten=b"".join(lines)
                    friction.atomic(fd,name,rewritten)
    except (OSError,ValueError,TypeError,KeyError,ImportError):
        pass


def run_helper(source, pid, start_at, call_id=None):
    # An existing native controller may launch this helper as a child; its own
    # exact exit remains the native controller's responsibility.
    owned = os.getpid() == pid and start_at > 0
    if owned:
        globals()["_active_call_id"] = call_id
        os.environ["TEEREX_CALL_START"] = str(pid) + ":" + str(start_at) + (":" + call_id if call_id else "")
    started = time.monotonic()
    elapsed_before_helper = max(0, (time.time_ns() - start_at) // 1000000)
    def finish(code):
        if not owned:
            return
        try:
            append(dict(schema_version=1, call_id=call_id, phase="end", at=int(time.time()*1000), pid=pid,
                        start_at=start_at, exit=code, elapsed_ms=elapsed_before_helper + round((time.monotonic()-started)*1000)))
        except (OSError, ValueError):
            pass  # History must never alter stdout, stderr, exit, or signals.
    try:
        exec(compile(source, "<string>", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
    except SystemExit as e:
        if e.code is None:
            finish(0)
        elif isinstance(e.code, int):
            if -255 <= e.code <= 255:
                finish(int(e.code) & 255)
        else:
            finish(1)
        raise
    except BaseException:
        # In particular, uncaught KeyboardInterrupt can terminate as SIGINT;
        # Python owns that final exit, so there is no exact end to report here.
        raise
    else:
        finish(0)
