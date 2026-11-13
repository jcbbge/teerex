"""Plan/apply cleanup of released clutch records; never remove a held or uncertain record."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


def private(info, directory=False):
    return (info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
            and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1))


def read_record(root, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
    try:
        info = os.fstat(fd)
        if not private(info) or info.st_size > 8192:
            raise ValueError("unsafe_record")
        raw = os.read(fd, 8193)
        value = json.loads(raw)
        if (set(value) != {"schema_version", "socket", "session", "pane", "held", "at_unix_ms", "reason"}
                or value["schema_version"] != 1 or type(value["held"]) is not bool
                or not isinstance(value["socket"], str) or not os.path.isabs(value["socket"]) or "\x00" in value["socket"]
                or not re.fullmatch(r"session:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value["session"])
                or not re.fullmatch(r"block:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value["pane"])
                or type(value["at_unix_ms"]) is not int or value["at_unix_ms"] <= 0
                or not isinstance(value["reason"], str) or len(value["reason"].encode()) > 512):
            raise ValueError("invalid_record")
        key = "\0".join(value[k] for k in ("socket", "session", "pane"))
        if hashlib.sha256(key.encode()).hexdigest() + ".json" != name:
            raise ValueError("record_key_mismatch")
        return value, (info.st_dev, info.st_ino, raw)
    finally:
        os.close(fd)


class Liveness:
    def __init__(self):
        self.cache = {}

    def query(self, socket, method, args):
        key = (socket, method, json.dumps(args, sort_keys=True))
        if key not in self.cache:
            command = [os.environ.get("TEEREX_INTERNAL_REX", "rex"), "--autostart=false", "--server", "unix://" + socket,
                       "--timeout", "2s", "api", "call", method, json.dumps(args)]
            # Bound retained responses and time; no shell, autostart, input or attachment.
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                try:
                    child = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, timeout=3)
                    output.seek(0)
                    raw = output.read(1048577)
                    self.cache[key] = json.loads(raw) if child.returncode == 0 and len(raw) <= 1048576 else None
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    self.cache[key] = None
        return self.cache[key]

    def gone(self, record):
        try:
            info = os.stat(record["socket"])
        except FileNotFoundError:
            return "socket_absent"
        except OSError:
            return None
        if not stat.S_ISSOCK(info.st_mode):
            return None
        sessions = self.query(record["socket"], "session.list", {})
        if not isinstance(sessions, dict) or not isinstance(sessions.get("sessions"), list):
            return None
        if not all(isinstance(s, dict) and isinstance(s.get("session_id"), str) for s in sessions["sessions"]):
            return None
        if record["session"] not in [s["session_id"] for s in sessions["sessions"]]:
            return "session_absent"
        blocks = self.query(record["socket"], "session.list_blocks", dict(session_id=record["session"]))
        if not isinstance(blocks, dict) or not isinstance(blocks.get("blocks"), list):
            return None
        if not all(isinstance(b, dict) and isinstance(b.get("block_id"), str) for b in blocks["blocks"]):
            return None
        return "pane_absent" if record["pane"] not in [b["block_id"] for b in blocks["blocks"]] else None


def main():
    parser = argparse.ArgumentParser(prog="teerex clutch prune", description=__doc__)
    parser.add_argument("--apply", action="store_true", help="remove eligible records; omit to plan")
    args = parser.parse_args()
    path = Path(os.environ.get("TEEREX_CLUTCH_DIR") or str(Path.home() / ".local/state/teerex/clutch"))
    if not path.is_absolute():
        parser.error("absolute TEEREX_CLUTCH_DIR required")
    result = dict(schema_version=1, kind="clutch_prune", mode="apply" if args.apply else "plan", directory=str(path), selected=[], removed=[], skipped=[])
    try:
        root = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        print(json.dumps(result)); return
    try:
        if not private(os.fstat(root), True):
            raise ValueError("unsafe_directory")
        names = sorted(n for n in os.listdir(root) if re.fullmatch(r"[a-f0-9]{64}\.json", n))
        if not names:
            print(json.dumps(result)); return
        # Never replace/unlink the stable mutation lock. Plan creates nothing.
        lock = os.open("clutch.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        try:
            if not private(os.fstat(lock)):
                raise ValueError("unsafe_lock")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            live = Liveness()
            for name in names:
                try:
                    value, identity = read_record(root, name)
                    reason = None if value["held"] else live.gone(value)
                    if reason is None:
                        result["skipped"].append(dict(file=name, reason="held" if value["held"] else "live_or_unknown")); continue
                    result["selected"].append(dict(file=name, reason=reason))
                    if args.apply:
                        current, same = read_record(root, name)
                        if current["held"] or same != identity:
                            result["skipped"].append(dict(file=name, reason="changed")); continue
                        os.unlink(name, dir_fd=root)
                        result["removed"].append(name)
                except (OSError, ValueError, TypeError, KeyError):
                    result["skipped"].append(dict(file=name, reason="unsafe_or_invalid_record"))
            if args.apply and result["removed"]:
                os.fsync(root)
        finally:
            os.close(lock)
    finally:
        os.close(root)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(json.dumps(dict(kind="clutch_prune", outcome="refused", failure_reason=type(error).__name__)))
        raise SystemExit(1)
