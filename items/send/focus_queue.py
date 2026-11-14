"""Private clutch delivery queue. Only claimed files may dispatch; uncertain claims never replay."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid

ENTRY = re.compile(r"([0-9]{20}-[0-9a-f]{32})\.(pending|inflight)\.json\Z")


def private(fd, directory=False):
    info = os.fstat(fd)
    expected = stat.S_IFDIR if directory else stat.S_IFREG
    if (info.st_uid != os.getuid() or stat.S_IFMT(info.st_mode) != expected or
            stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or
            (not directory and info.st_nlink != 1)):
        raise ValueError("queue_not_private_owned")


@contextlib.contextmanager
def directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private(fd, True)
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def lock(root, name):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root)
    try:
        private(fd)
        deadline = time.monotonic() + 1
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("queue_lock_busy")
                time.sleep(.005)
        yield
    finally:
        os.close(fd)


def read(root, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        private(stream.fileno())
        raw = stream.read()
    return json.loads(raw)


def names(root):
    return sorted(name for name in os.listdir(root) if ENTRY.fullmatch(name))


def rename(root, source, target):
    os.rename(source, target, src_dir_fd=root, dst_dir_fd=root)
    os.fsync(root)


def enqueue(path, request):
    with directory(path.parent) as root, lock(root, "clutch.lock"):
        try:
            held = read(root, path.name)
        except FileNotFoundError:
            return dict(outcome="released")
        if not held.get("held"):
            return dict(outcome="released")
        if any(held.get(k) != request[k] for k in ("socket", "session", "pane")):
            raise ValueError("queue_target_mismatch")
        qname = path.stem + ".queue"
        try:
            os.mkdir(qname, 0o700, dir_fd=root)
        except FileExistsError:
            pass
        with directory(path.parent / qname) as queue:
            existing = names(queue)
            serial = max(time.time_ns(), max((int(n[:20]) + 1 for n in existing), default=0))
            identity = f"{serial:020d}-{uuid.uuid4().hex}"
            record = dict(request, schema_version=1, id=identity, created_at_unix_ms=time.time_ns() // 1000000)
            validate(record, identity)
            # A complete flushed record becomes visible in one rename, under the clutch mutation lock.
            stage = identity + ".next"
            fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=queue)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(record, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                rename(queue, stage, identity + ".pending.json")
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(stage, dir_fd=queue)
            os.fsync(root)
            return dict(outcome="queued", id=identity)


def validate(value, identity):
    if (not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("id") != identity or
            value.get("draft") not in ("guard", "ignore") or
            not isinstance(value.get("draft_wait_ms"), int) or not 0 <= value["draft_wait_ms"] <= 55000 or
            not isinstance(value.get("timeout_ms"), int) or not 100 <= value["timeout_ms"] <= 115000 or
            not isinstance(value.get("created_at_unix_ms"), int) or value["created_at_unix_ms"] <= 0):
        raise ValueError("invalid_queue_record")
    for key, limit, multiline in (("sender", 128, False), ("body", 65536, True)):
        text = value.get(key)
        if (not isinstance(text, str) or not 1 <= len(text.encode()) <= limit or
                any((ord(c) < 32 and not (multiline and c in "\n\t")) or ord(c) == 127 for c in text)):
            raise ValueError("invalid_queue_text")
    if (not isinstance(value.get("socket"), str) or not os.path.isabs(value["socket"]) or
            not re.fullmatch(r"session:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value.get("session", "")) or
            not re.fullmatch(r"block:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value.get("pane", ""))):
        raise ValueError("invalid_queue_target")
    for key in ("status_id", "status_state", "status_message"):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise ValueError("invalid_queue_status")


def inspect(path, show):
    try:
        with directory(path.parent), directory(path.with_suffix(".queue")) as queue:
            messages = []
            for name in names(queue):
                match = ENTRY.fullmatch(name)
                value = read(queue, name)
                validate(value, match[1])
                item = dict(id=match[1], state=match[2], sender=value["sender"],
                            age_ms=max(0, time.time_ns() // 1000000 - value["created_at_unix_ms"]),
                            first_line=value["body"].splitlines()[0] if value["body"].splitlines() else "")
                if show:
                    item["body"] = value["body"]
                messages.append(item)
            return dict(outcome="inspected", messages=messages)
    except FileNotFoundError:
        return dict(outcome="inspected", messages=[])


def drain(path, executable, receipt):
    result = dict(delivered=[], pending=0, inflight=0, stopped=None)
    receipt["queue"] = result
    queue_path = path.with_suffix(".queue")
    try:
        queue_context = directory(queue_path)
        queue = queue_context.__enter__()
    except FileNotFoundError:
        return receipt, 0
    try:
        # One release owns the drain. Taking the clutch stays independent of delivery waits.
        with lock(queue, "drain.lock"):
            for name in names(queue):
                match = ENTRY.fullmatch(name)
                if match[2] == "inflight":
                    result["stopped"] = dict(id=match[1], reason="delivery_uncertain")
                    break
                record = read(queue, name)
                validate(record, match[1])
                if any(record.get(k) != receipt["target"][k] for k in ("socket", "session", "pane")):
                    raise ValueError("queue_target_mismatch")
                inflight = match[1] + ".inflight.json"
                rename(queue, name, inflight)
                # Message bytes stay on disk/stdin, never in the child command line or receipts.
                command = [executable, "send", "--socket", record["socket"], "--session", record["session"],
                           "--block", record["pane"], "--from", record["sender"], "--message-file", "-",
                           "--no-queue", "--draft", record["draft"], "--draft-wait-ms", str(record["draft_wait_ms"]),
                           "--timeout-ms", str(record["timeout_ms"])]
                for key in ("status_id", "status_state", "status_message"):
                    if record.get(key) is not None:
                        command.extend(["--" + key.replace("_", "-"), record[key]])
                try:
                    sent = subprocess.run(command, input=record["body"], text=True, capture_output=True,
                                          timeout=record["timeout_ms"] / 1000 + 5)
                    packet = json.loads(sent.stdout)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    result["stopped"] = dict(id=match[1], reason="delivery_uncertain")
                    break
                if sent.returncode == 0 and packet.get("outcome") == "events_acknowledged":
                    os.unlink(inflight, dir_fd=queue)
                    os.fsync(queue)
                    result["delivered"].append(match[1])
                    continue
                # No input attempted is replayable. Any partial/uncertain input keeps the claim.
                safe = (packet.get("paste", {}).get("attempted") is False and
                        packet.get("enter", {}).get("attempted") is False and
                        packet.get("draft", {}).get("cleared") is None)
                if safe:
                    rename(queue, inflight, name)
                result["stopped"] = dict(id=match[1], reason=packet.get("failure_reason") or packet.get("outcome"),
                                         retry_safe=safe)
                break
            remaining = names(queue)
            result["pending"] = sum(".pending." in n for n in remaining)
            result["inflight"] = sum(".inflight." in n for n in remaining)
        return receipt, 1 if result["stopped"] else 0
    finally:
        queue_context.__exit__(None, None, None)


def main():
    operation, path = sys.argv[1], Path(sys.argv[2])
    if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
        raise ValueError("invalid_queue_state_path")
    if operation == "enqueue":
        request_path = Path(sys.argv[3])
        if request_path.parent != path.parent or not re.fullmatch(r"[0-9a-f]{32}\.request", request_path.name):
            raise ValueError("invalid_queue_request_path")
        with directory(path.parent) as root:
            request = read(root, request_path.name)
        value = enqueue(path, request)
        code = 0
    elif operation == "inspect":
        value = inspect(path, "--show" in sys.argv[3:])
        code = 0
    elif operation == "drain":
        with directory(path.parent):
            value, code = drain(path, sys.argv[3], json.loads(sys.argv[4]))
    else:
        raise ValueError("invalid_queue_operation")
    print(json.dumps(value, ensure_ascii=False))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        failure = dict(outcome="refused", failure_reason=reason)
        if len(sys.argv) > 4 and sys.argv[1] == "drain":
            failure = json.loads(sys.argv[4])
            failure.update(outcome="refused", failure_reason=reason,
                           queue=dict(delivered=None, pending=None, inflight=None, stopped=dict(reason=reason)))
        print(json.dumps(failure))
        sys.exit(1)
