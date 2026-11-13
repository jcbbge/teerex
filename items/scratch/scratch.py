"""Per-pane ephemeral Markdown scratchpads. Python 3.9+ standard library."""
import argparse
import contextlib
import datetime
import errno
import fcntl
import hashlib
import json
import os
import select
from pathlib import Path
import re
import shutil
import shlex
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
    result = dict(name="Scratchpad", purpose="", intent="", updated="", now=None, todo=[], done=[], waiting=None)
    section = None
    current = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("# "):
            result["name"] = line[2:].strip()
        elif line.startswith("## "):
            section = {"Now": current, "To-do": result["todo"], "Done": result["done"]}.get(line[3:].strip())
        elif line.startswith("Waiting:"):
            parts = line[8:].strip().split(" · ", 2)
            if len(parts) == 3 and parts[0] and parts[1] and parts[2].startswith("since "):
                result["waiting"] = dict(on=parts[0], what=parts[1], since=parts[2][6:])
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


def scratch_step(value, state):
    parts = value.split(" · ")
    step = dict(state=state, text=parts[0], by=None, outcome=None, handoff=None)
    for part in parts[1:]:
        if part.startswith("■ "):
            step["outcome"] = part[2:]
        elif part.startswith("⇥ "):
            step["handoff"] = part[2:]
        elif step["by"] is None:
            step["by"] = part
        else:
            step["text"] += " · " + part
    return step


def scratch_steps(data):
    return ([scratch_step(v, "done") for v in reversed(data["done"])] +
            ([scratch_step(data["now"], "now")] if data["now"] else []) +
            [scratch_step(v, "todo") for v in data["todo"]])


def scratch_annotate(value, by=None, outcome=None, handoff=None):
    step = scratch_step(scratch_line(value), "now")
    for key, val in (("by", by), ("outcome", outcome), ("handoff", handoff)):
        if val is not None:
            scratch_line(val)
            if " · " in val:
                raise ScratchError("annotation_separator_reserved")
            step[key] = val
    return " · ".join([step["text"]] + ([step["by"]] if step["by"] else []) +
                      (["■ " + step["outcome"]] if step["outcome"] else []) +
                      (["⇥ " + step["handoff"]] if step["handoff"] else []))


def scratch_write(path, data):
    data["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    waiting = data.get("waiting")
    wait_line = ("Waiting: {on} · {what} · since {since}\n".format(**waiting) if waiting else "")
    raw = (f"# {data['name']}\nPurpose: {data['purpose']}\nIntent: {data['intent']}\nUpdated: {data['updated']}\n{wait_line}\n## Now\n" +
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
            scratch_write(path, dict(name=name, purpose=purpose, intent=intent, now=None, todo=[], done=[], waiting=None))
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
    if data.get("waiting"):
        add("⧗ {on} · {what} · since {since}".format(**data["waiting"]))
    lines.append("")
    if data["now"]:
        add("▶ " + data["now"])
    for item in data["todo"]:
        add("☐ " + item)
    for item in data["done"]:
        add("✓ " + item)
    return "\n".join(lines) + "\n"


SCRATCH_REMINDER = "say what you are waiting on: teerex scratch wait --on … --what …"


def scratch_progress(data):
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()
    return dict(now=digest(data["now"]), done=digest(data["done"]), done_count=len(data["done"]))


def scratch_turn(state, event, path):
    """The caller holds its private state lock; reading the Markdown needs no write lock."""
    kind = event["hook_event_name"]
    at = time.time_ns() // 1000000
    if kind == "UserPromptSubmit":
        state.update(turn_started_at=at, scratch_reminded=False, scratch_reminder_pending=False)
        try:
            state["scratch_start"] = scratch_progress(scratch_read(Path(path))) if path else None
        except (OSError, ValueError):
            state["scratch_start"] = None
        return dict(status="turn_started", action="allow")
    start = state.setdefault("turn_started_at", at)
    if not path:
        return dict(status="not_checked", action="allow", reason="AGENT_SCRATCHPAD_absent")
    updated = None
    try:
        data = scratch_read(Path(path))
        updated = data["updated"]
        baseline = state.get("scratch_start")
        progress = scratch_progress(data)
        fresh = bool(data.get("waiting")) or (baseline is not None and
                (baseline["now"] != progress["now"] or
                 (not data["now"] and baseline["done"] != progress["done"] and
                  progress["done_count"] > baseline.get("done_count", 0))))
        # Older managed callers have only a turn time, until their next prompt snapshot.
        if baseline is None:
            try:
                parsed = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                fresh = fresh or bool(data["now"] and parsed.tzinfo is not None and parsed.timestamp() * 1000 >= start)
            except ValueError:
                pass
        reason = "progress_or_waiting" if fresh else "no_progress_or_waiting"
    except (OSError, ValueError) as exc:
        fresh, reason = False, type(exc).__name__
    previous = bool(state.get("scratch_reminded"))
    action = "allow" if fresh or previous or kind == "StopFailure" or (event.get("scratch_harness") == "pi" and kind == "Stop") else "block"
    if action == "block":
        state["scratch_reminded"] = True
    return dict(status="fresh" if fresh else "stale", action=action, already_reminded=previous,
                turn_started_at=start, updated=updated, reason=reason)


def scratch_hook_settings(executable):
    if not os.path.isabs(executable) or any(ord(c) < 32 for c in executable):
        raise ScratchError("absolute_teerex_required")
    command = shlex.join([executable, "scratch", "hook"])
    return {"hooks": {kind: [{"hooks": [{"type": "command", "command": command, "timeout": 10}]}]
                      for kind in ("UserPromptSubmit", "Stop")}}


def scratch_seat_hook():
    raw = sys.stdin.buffer.read(32769)
    if len(raw) > 32768:
        raise ScratchError("hook_event_too_large")
    event = json.loads(raw)
    if not isinstance(event, dict) or event.get("hook_event_name") not in ("UserPromptSubmit", "Stop"):
        raise ScratchError("unsupported_scratch_hook_event")
    path = os.environ.get("AGENT_SCRATCHPAD") or os.environ.get("LC_AGENT_SCRATCHPAD")
    if not path:
        print(json.dumps(dict(scratchpad_check=dict(status="not_checked", action="allow"))))
        return
    path = Path(path)
    if not path.is_absolute():
        raise ScratchError("absolute_scratchpad_required")
    state_path = Path(str(path) + ".turn.json")
    with scratch_lock(path):
        state = {}
        try:
            fd = os.open(state_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(fd) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise ScratchError("owned_regular_turn_state_required")
                raw_state = stream.read(8193)
            if len(raw_state) > 8192:
                raise ScratchError("turn_state_too_large")
            state = json.loads(raw_state)
            if not isinstance(state, dict):
                raise ScratchError("invalid_turn_state")
        check = scratch_turn(state, event, str(path))
        state["scratchpad_check"] = check
        fd, stage = tempfile.mkstemp(prefix=".scratch-turn-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(stage, state_path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(stage)
    if check["action"] == "block":
        print(json.dumps(dict(decision="block", reason=SCRATCH_REMINDER)))
    else:
        print(json.dumps(dict(scratchpad_check=check)))


def scratch_set_wait(data, options):
    if options.clear:
        if options.what or options.until or options.timeout_ms is not None:
            raise ScratchError("clear_takes_no_wait_options")
        data["waiting"] = None
        return
    on, what = scratch_line(options.on), scratch_line(options.what)
    if " · " in on or " · " in what:
        raise ScratchError("waiting_separator_reserved")
    if options.timeout_ms is not None and (not options.until or options.timeout_ms < 0):
        raise ScratchError("nonnegative_timeout_requires_until")
    data["waiting"] = dict(on=on, what=what, since=datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))


def scratch_waiters(on):
    scratch_line(on)
    root = Path.home() / ".local/state/teerex/scratch"
    entries = []
    for path in sorted(root.glob("session:*/block:*.md")):
        try:
            session = scratch_id(path.parent.name, "session")
            block = scratch_id(path.stem, "block")
            data = scratch_read(path)
        except (OSError, ValueError):
            continue
        if data.get("waiting") and data["waiting"]["on"] == on:
            entries.append(dict(session=session, block=block, name=data["name"]))
    return entries


def scratch_wake(path, event="report"):
    """Nonblocking notification; absence means no one-shot waiter. No Rex contact."""
    if event not in ("done", "report"):
        raise ScratchError("invalid_wait_event")
    try:
        fd = os.open(str(path) + ".wait.fifo", os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENXIO):  # absent FIFO or no reader
            return False
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ScratchError("owned_wait_fifo_required")
        os.write(fd, (event + "\n").encode())
        return True
    finally:
        os.close(fd)


def scratch_wait_once(path, options):
    fifo = str(path) + ".wait.fifo"
    fd = None
    with scratch_lock(path):
        data = scratch_read(path)
        scratch_set_wait(data, options)
        # Exclusive creation refuses concurrent or abandoned waits instead of stealing them.
        os.mkfifo(fifo, 0o600)
        try:
            fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
            scratch_write(path, data)
        except BaseException:
            if fd is not None:
                os.close(fd)
            os.unlink(fifo)
            raise
    try:
        deadline = None if options.timeout_ms is None else time.monotonic() + options.timeout_ms / 1000
        pending = b""
        while True:
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            if not select.select([fd], [], [], remaining)[0]:
                print(json.dumps(dict(outcome="timeout", until=options.until)))
                return 1
            pending += os.read(fd, 4096)
            if len(pending) > 8192:
                raise ScratchError("wait_notification_too_large")
            while b"\n" in pending:
                event, pending = pending.split(b"\n", 1)
                if event == b"report" or (event == b"done" and options.until == "done"):
                    print(json.dumps(dict(outcome="notified", event=event.decode())))
                    return 0
    finally:
        os.close(fd)
        os.unlink(fifo)


def scratch_main(argv=None):
    parser = argparse.ArgumentParser(prog="teerex scratch", description="Per-pane ephemeral Markdown scratchpads; palette prepares Show scratchpad for surfaces palette install.")
    subs = parser.add_subparsers(dest="operation", required=True)
    for op in ("init", "now", "todo", "done", "show", "path", "watch", "wait"):
        p = subs.add_parser(op)
        p.add_argument("--session", default=os.environ.get("REX_SESSION") or os.environ.get("LC_REX_SESSION"))
        p.add_argument("--block", default=os.environ.get("REX_BLOCK") or os.environ.get("LC_REX_BLOCK"))
        if op == "init":
            p.add_argument("--name", default=os.environ.get("AGENT_NAME", "Scratchpad"))
            p.add_argument("--purpose", required=True)
            p.add_argument("--intent", required=True)
        if op in ("now", "todo"):
            p.add_argument("text")
            p.add_argument("--by", help="step executor (computer, model and effort, or agent)")
            p.add_argument("--handoff", help="agent this step waits on")
        if op in ("done", "now"):
            p.add_argument("--outcome", help="outcome of the completed Now; with now, requires --done")
        if op == "wait":
            g = p.add_mutually_exclusive_group(required=True)
            g.add_argument("--on", help="agent or thing awaited")
            g.add_argument("--clear", action="store_true")
            p.add_argument("--what", help="exact answer or event awaited")
            p.add_argument("--until", choices=("done", "report"), help="block once on a notifier FIFO")
            p.add_argument("--timeout-ms", type=int, default=None)
        if op == "now":
            p.add_argument("--done", action="store_true", help="finish the previous Now instead of returning it to To-do")
        if op == "show":
            p.add_argument("--json", action="store_true")
        if op == "watch":
            p.add_argument("--once", action="store_true", help="render one frame and exit")
    waiters = subs.add_parser("waiters", help="list local scratchpads waiting on a name")
    waiters.add_argument("--on", required=True)
    waiters.add_argument("--json", action="store_true")
    subs.add_parser("hook", help="Claude seat UserPromptSubmit/Stop stdin hook; no progress or Waiting blocks once per turn; AGENT_SCRATCHPAD required")
    settings = subs.add_parser("hook-settings", help="print installable Claude seat hook settings; does not modify configuration")
    settings.add_argument("--teerex", required=True, help="absolute stable teerex executable")
    o = parser.parse_args(argv)
    try:
        if o.operation == "hook-settings":
            print(json.dumps(scratch_hook_settings(o.teerex)))
            return 0
        if o.operation == "hook":
            scratch_seat_hook()
            return 0
        if o.operation == "waiters":
            entries = scratch_waiters(o.on)
            print(json.dumps(entries, ensure_ascii=False) if o.json else "\n".join(
                "{name} · {session} · {block}".format(**v) for v in entries))
            return 0
        path = scratch_path(o.session, o.block)
        if o.operation == "path":
            print(path)
        elif o.operation == "init":
            print(scratch_init(o.session, o.block, o.name, o.purpose, o.intent))
        elif o.operation == "show":
            data = scratch_read(path)
            if o.json:
                result = {k: data[k] for k in ("purpose", "intent", "now", "todo", "done", "updated", "waiting")}
                result["steps"] = scratch_steps(data)
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(scratch_render(data), end="")
        elif o.operation == "watch":
            previous = None
            existed = False
            while True:
                try:
                    frame = scratch_render(scratch_read(path), shutil.get_terminal_size((40, 24)).columns)
                    existed = True
                except FileNotFoundError:
                    if existed:
                        return 0
                    frame = "Scratchpad archived or not initialized\n"
                if frame != previous:
                    print(("\x1b[2J\x1b[H" if sys.stdout.isatty() else "") + frame, end="", flush=True)
                    previous = frame
                if o.once:
                    break
                time.sleep(.25)
        elif o.operation == "wait" and o.until:
            return scratch_wait_once(path, o)
        else:
            with scratch_lock(path):
                data = scratch_read(path)
                if o.operation == "todo":
                    data["todo"].append(scratch_annotate(o.text, by=o.by, handoff=o.handoff))
                elif o.operation == "now":
                    if o.outcome and not o.done:
                        raise ScratchError("outcome_requires_now_done")
                    value = scratch_annotate(o.text, by=o.by, handoff=o.handoff)
                    data["waiting"] = None
                    if data["now"]:
                        data["done" if o.done else "todo"].insert(0, scratch_annotate(data["now"], outcome=o.outcome) if o.done else data["now"])
                    match = next((v for v in data["todo"] if scratch_step(v, "todo")["text"] == scratch_step(value, "now")["text"]), None)
                    if match:
                        data["todo"].remove(match)
                        value = scratch_annotate(match, by=o.by, handoff=o.handoff)
                    data["now"] = value
                elif o.operation == "wait":
                    scratch_set_wait(data, o)
                elif data["now"]:
                    data["done"].insert(0, scratch_annotate(data["now"], outcome=o.outcome))
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
