"""Acknowledged input events, consumed by the destination's in-pane supervisor."""
import contextlib
import fcntl
import json
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile


def agent_input_path(socket, session, block):
    for kind, value in (("session", session), ("block", block)):
        if not isinstance(value, str) or not re.fullmatch(kind + r":[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
            raise ValueError("canonical_agent_input_target_required")
    if not os.path.isabs(socket):
        raise ValueError("absolute_agent_input_socket_required")
    key = hashlib.sha256((os.path.realpath(socket) + "\n" + session + "\n" + block).encode()).hexdigest()
    return Path.home() / ".local/state/teerex/agent-input" / (key + ".json")


def agent_input_write(socket, session, block, at_ns, reminder=False, sender=None):
    path = agent_input_path(socket, session, block)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("private_agent_input_directory_required")
    lock = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = agent_input_read(socket, session, block) or {}
        event = dict(at_ns=at_ns, reminder=reminder)
        first = previous.get("first_work_sender")
        if first is None and sender and sender.get("name") and sender.get("session") and sender.get("block") and not reminder and not sender["name"].startswith("teerex-"):
            first = sender
        if first:
            event["first_work_sender"] = first
        return agent_input_replace(path, event)
    finally:
        os.close(lock)


def agent_input_replace(path, event):
    fd, stage = tempfile.mkstemp(dir=path.parent, prefix=".input-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(event, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
    finally:
        if os.path.exists(stage):
            os.unlink(stage)
    return "agent_turn_start_recorded"


def agent_input_read(socket, session, block):
    path = agent_input_path(socket, session, block)
    for attempt in range(3):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink > 1:
                raise ValueError("private_agent_input_event_required")
            if info.st_nlink == 0:
                continue  # Atomic replacement retired this inode; reopen the current path.
            raw = stream.read(4097)
        break
    else:
        return None  # A continuously replacing writer will be observed on the next poll.
    if len(raw) > 4096:
        raise ValueError("agent_input_event_too_large")
    event = json.loads(raw)
    if not isinstance(event, dict) or type(event.get("at_ns")) is not int or event["at_ns"] <= 0 or type(event.get("reminder", False)) is not bool:
        raise ValueError("invalid_agent_input_event")
    return event
