"""Per-pane ephemeral Markdown scratchpads. Python 3.9+ standard library."""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import textwrap
import time


class ScratchError(ValueError):
    pass


def scratch_id(value, kind):
    if not isinstance(value, str) or not re.fullmatch(kind + r":[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
        raise ScratchError("canonical_session_and_block_required")
    return value


def scratch_path(session, block):
    # Deliberately fixed: existing agents already write these paths by hand.
    return Path.home() / ".local/state/teerex/scratch" / scratch_id(session, "session") / (scratch_id(block, "block") + ".md")


def scratch_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ScratchError("owned_scratch_directory_required")
    os.chmod(path, 0o700)


@contextlib.contextmanager
def scratch_lock(path):
    scratch_directory(path.parent.parent)
    scratch_directory(path.parent)
    fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ScratchError("owned_regular_lock_required")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def scratch_line(value):
    if not value or len(value.encode()) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ScratchError("nonempty_single_line_required")
    return value


def scratch_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ScratchError("owned_regular_scratchpad_required")
        raw = stream.read(262145)
    if len(raw.encode()) > 262144:
        raise ScratchError("scratchpad_too_large")
    result = dict(name="Scratchpad", purpose="", intent="", updated="", now=None, todo=[], done=[])
    section = None
    current = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("# "):
            result["name"] = line[2:].strip()
        elif line.startswith("## "):
            section = {"Now": current, "To-do": result["todo"], "Done": result["done"]}.get(line[3:].strip())
        elif any(line.startswith(k + ":") for k in ("Purpose", "Intent", "Updated")):
            key, value = line.split(":", 1)
            result[key.lower()] = value.strip()
        elif section is not None:
            match = re.fullmatch(r"-\s+\[[ xX]\]\s+(.+)", line)
            if match:
                section.append(match.group(1))
    if current:
        result["now"] = current[0]
        result["todo"] = current[1:] + result["todo"]
    return result


def scratch_write(path, data):
    data["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    raw = (f"# {data['name']}\nPurpose: {data['purpose']}\nIntent: {data['intent']}\nUpdated: {data['updated']}\n\n## Now\n" +
           (f"- [ ] {data['now']}\n" if data["now"] else "") + "\n## To-do\n" +
           "".join(f"- [ ] {v}\n" for v in data["todo"]) + "\n## Done\n" +
           "".join(f"- [x] {v}\n" for v in data["done"]))
    if len(raw.encode()) > 262144:
        raise ScratchError("scratchpad_too_large")
    fd, stage = tempfile.mkstemp(prefix=".scratch-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(stage)


def scratch_init(session, block, name, purpose, intent):
    path = scratch_path(session, block)
    for value in (name, purpose, intent):
        scratch_line(value)
    with scratch_lock(path):
        if path.exists() or path.is_symlink():
            # Repeated init preserves the pane's working list, including hand-written notes.
            scratch_write(path, scratch_read(path))
        else:
            scratch_write(path, dict(name=name, purpose=purpose, intent=intent, now=None, todo=[], done=[]))
    return str(path)


def scratch_archive(path, session, block):
    path = Path(path)
    if path != scratch_path(session, block):
        raise ScratchError("scratchpad_path_mismatch")
    with scratch_lock(path):
        if not path.exists():
            return None
        scratch_read(path)
        target = path.parent.parent / "archive" / session
        scratch_directory(target.parent)
        scratch_directory(target)
        destination = target / path.name
        # Never overwrite an earlier archive if a pane id was reused.
        if destination.exists():
            destination = target / (path.stem + "-" + str(time.time_ns()) + ".md")
        os.replace(path, destination)
        os.chmod(destination, 0o600)
        return str(destination)


def scratch_render(data, width=40):
    width = max(12, min(width, 40))
    lines = []
    def add(value):
        # Strip controls from hand-written text before putting it on a terminal.
        value = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127)
        lines.extend(textwrap.wrap(value, width=width, subsequent_indent="  ") or [""])
    add(data["name"])
    add("Purpose: " + data["purpose"])
    add("Intent: " + data["intent"])
    try:
        updated = datetime.datetime.fromisoformat(data["updated"].replace("Z", "+00:00"))
        minutes = max(0, int((datetime.datetime.now(datetime.timezone.utc) - updated).total_seconds() // 60))
        add(f"updated {minutes} min ago")
    except (ValueError, TypeError):
        add("updated time unknown")
    lines.append("")
    if data["now"]:
        add("▶ " + data["now"])
    for item in data["todo"]:
        add("☐ " + item)
    for item in data["done"]:
        add("✓ " + item)
    return "\n".join(lines) + "\n"


def scratch_main(argv=None):
    parser = argparse.ArgumentParser(prog="teerex scratch", description="Per-pane ephemeral Markdown scratchpads; palette prepares Show scratchpad for surfaces palette install.")
    subs = parser.add_subparsers(dest="operation", required=True)
    for op in ("init", "now", "todo", "done", "show", "path", "watch"):
        p = subs.add_parser(op)
        p.add_argument("--session", default=os.environ.get("REX_SESSION") or os.environ.get("LC_REX_SESSION"))
        p.add_argument("--block", default=os.environ.get("REX_BLOCK") or os.environ.get("LC_REX_BLOCK"))
        if op == "init":
            p.add_argument("--name", default=os.environ.get("AGENT_NAME", "Scratchpad"))
            p.add_argument("--purpose", required=True)
            p.add_argument("--intent", required=True)
        if op in ("now", "todo"):
            p.add_argument("text")
        if op == "now":
            p.add_argument("--done", action="store_true", help="finish the previous Now instead of returning it to To-do")
        if op == "show":
            p.add_argument("--json", action="store_true")
        if op == "watch":
            p.add_argument("--once", action="store_true", help="render one frame and exit")
    o = parser.parse_args(argv)
    try:
        path = scratch_path(o.session, o.block)
        if o.operation == "path":
            print(path)
        elif o.operation == "init":
            print(scratch_init(o.session, o.block, o.name, o.purpose, o.intent))
        elif o.operation == "show":
            data = scratch_read(path)
            if o.json:
                print(json.dumps({k: data[k] for k in ("purpose", "intent", "now", "todo", "done", "updated")}, ensure_ascii=False))
            else:
                print(scratch_render(data), end="")
        elif o.operation == "watch":
            previous = None
            while True:
                try:
                    frame = scratch_render(scratch_read(path), shutil.get_terminal_size((40, 24)).columns)
                except FileNotFoundError:
                    frame = "Scratchpad archived or not initialized\n"
                if frame != previous:
                    print(("\x1b[2J\x1b[H" if sys.stdout.isatty() else "") + frame, end="", flush=True)
                    previous = frame
                if o.once:
                    break
                time.sleep(.25)
        else:
            with scratch_lock(path):
                data = scratch_read(path)
                if o.operation == "todo":
                    data["todo"].append(scratch_line(o.text))
                elif o.operation == "now":
                    value = scratch_line(o.text)
                    if data["now"]:
                        data["done" if o.done else "todo"].insert(0, data["now"])
                    if value in data["todo"]:
                        data["todo"].remove(value)
                    data["now"] = value
                elif data["now"]:
                    data["done"].insert(0, data["now"])
                    data["now"] = None
                scratch_write(path, data)
        return 0
    except (OSError, ValueError) as exc:
        print("teerex scratch: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__" and not globals().get("SCRATCH_LIBRARY"):
    sys.exit(scratch_main())
