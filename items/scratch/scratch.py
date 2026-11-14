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
import shlex
import stat
import subprocess
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
    result = dict(name="Scratchpad", purpose="", intent="", updated="", now=None, todo=[], done=[], waiting="", done_when="", check="", blocked="")
    section = None
    current = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("# "):
            result["name"] = line[2:].strip()
        elif line.startswith("## "):
            section = {"Now": current, "To-do": result["todo"], "Done": result["done"]}.get(line[3:].strip())
        elif any(line.startswith(k + ":") for k in ("Purpose", "Intent", "Updated", "Waiting", "Done-when", "Check", "Blocked")):
            key, value = line.split(":", 1)
            result[key.lower().replace("-", "_")] = value.strip()
        elif section is not None:
            match = re.fullmatch(r"-\s+\[[ xX]\]\s+(.+)", line)
            if match:
                section.append(match.group(1))
    if current:
        result["now"] = current[0]
        result["todo"] = current[1:] + result["todo"]
    return result


def scratch_write(path, data):
    data["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    raw = (f"# {data['name']}\nPurpose: {data['purpose']}\nIntent: {data['intent']}\nUpdated: {data['updated']}\n\n## Now\n" +
           (f"- [ ] {data['now']}\n" if data["now"] else "") + "\n## To-do\n" +
           "".join(f"- [ ] {v}\n" for v in data["todo"]) + "\n## Done\n" +
           "".join(f"- [x] {v}\n" for v in data["done"]) +
           ("\nWaiting: " + data["waiting"] + "\n" if data.get("waiting") else ""))
    raw += "".join(f"\n{label}: {data[key]}\n" for key, label in (("done_when", "Done-when"), ("check", "Check"), ("blocked", "Blocked")) if data.get(key))
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


def scratch_init(session, block, name, purpose, intent, done_when=""):
    path = scratch_path(session, block)
    for value in (name, purpose, intent):
        scratch_line(value)
    with scratch_lock(path):
        if path.exists() or path.is_symlink():
            # Repeated init preserves the pane's working list, including hand-written notes.
            scratch_write(path, scratch_read(path))
        else:
            scratch_write(path, dict(name=name, purpose=purpose, intent=intent, now=None, todo=[], done=[], waiting="", done_when=done_when, check="", blocked=""))
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
    for key, label in (("done_when", "Done-when"), ("waiting", "Waiting"), ("check", "Check"), ("blocked", "Blocked")):
        if data.get(key):
            add(label + ": " + data[key])
    if data["now"]:
        add("▶ " + data["now"])
    for item in data["todo"]:
        add("☐ " + item)
    for item in data["done"]:
        add("✓ " + item)
    return "\n".join(lines) + "\n"


SCRATCH_REMINDER = "update your scratchpad (Now/To-do/Done) before ending the turn"


def scratch_turn(state, event, path):
    """The caller holds its private state lock; reading the Markdown needs no write lock."""
    kind = event["hook_event_name"]
    at = time.time_ns() // 1000000
    if kind == "UserPromptSubmit":
        state.update(turn_started_at=at, scratch_reminded=False, scratch_reminder_pending=False)
        return dict(status="turn_started", action="allow")
    start = state.setdefault("turn_started_at", at)
    if not path:
        return dict(status="not_checked", action="allow", reason="AGENT_SCRATCHPAD_absent")
    updated = None
    try:
        updated = scratch_read(Path(path))["updated"]
        parsed = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("scratchpad_updated_requires_timezone")
        fresh = parsed.timestamp() * 1000 >= start
        reason = "updated_this_turn" if fresh else "updated_before_turn"
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


def scratch_check_time(value):
    if re.fullmatch(r"[0-9]+m", value):
        parsed = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=int(value[:-1]))
    else:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ScratchError("check_requires_timezone")
    return parsed.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# The server checks exact block IDs and closes the viewer in the same call. A tab
# close or app close bypasses the agent supervisor, but not this foreground watch.
SCRATCH_WATCH_LUA = r"""
local a=rex.args
local sessions=rex.call('session.list')
if type(sessions)~='table' or type(sessions.sessions)~='table' then error('session_list_unavailable') end
local exists=false
for _,s in ipairs(sessions.sessions) do if s.session_id==a.session then exists=true end end
if not exists then io.write('gone'); return end
rex.call('session.attach_all',{event_scope='session'})
local blocks=rex.call('session.list_blocks',{session_id=a.session})
if type(blocks)~='table' or type(blocks.blocks)~='table' then error('block_list_unavailable') end
for _,b in ipairs(blocks.blocks) do if b.block_id==a.owner then io.write('live'); return end end
if a.viewer then rex.call('block.close',{session_id=a.session,block_id=a.viewer,keep_last=false}) end
io.write('gone')
"""


def scratch_watch_owner(socket, session, owner):
    viewer = os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK')
    own_session = os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION')
    if own_session != session or viewer == owner:
        viewer = None
    if viewer is not None:
        scratch_id(viewer, 'block')
    args = dict(session=session, owner=owner, viewer=viewer)
    command = [os.environ.get('TEEREX_INTERNAL_REX') or 'rex', '--autostart=false',
               '--server', 'unix://' + socket, '--timeout', '1s', '--color', 'never',
               'do', '-e', SCRATCH_WATCH_LUA, '--args', json.dumps(args)]
    environment = dict(os.environ)
    for key in ('REX_SERVER', 'REX_SESSION', 'REX_BLOCK', 'REX_CLIENT', 'LC_REX_SESSION', 'LC_REX_BLOCK'):
        environment.pop(key, None)
    # Closing this viewer must not interrupt the server-side close request.
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=1.5, start_new_session=True)
    if result.returncode or result.stdout not in ('live', 'gone'):
        raise ScratchError('owner_check_unavailable: ' + result.stderr.strip())
    return result.stdout == 'live'


def scratch_main(argv=None):
    parser = argparse.ArgumentParser(prog="teerex scratch", description="Per-pane ephemeral Markdown scratchpads; palette prepares Show scratchpad for surfaces palette install.")
    subs = parser.add_subparsers(dest="operation", required=True)
    for op in ("init", "now", "todo", "done", "show", "path", "watch", "flag"):
        p = subs.add_parser(op)
        p.add_argument("--session", default=os.environ.get("REX_SESSION") or os.environ.get("LC_REX_SESSION"))
        p.add_argument("--block", default=os.environ.get("REX_BLOCK") or os.environ.get("LC_REX_BLOCK"))
        if op == "init":
            p.add_argument("--name", default=os.environ.get("AGENT_NAME", "Scratchpad"))
            p.add_argument("--purpose", required=True)
            p.add_argument("--intent", required=True)
        if op in ("now", "todo", "flag"):
            p.add_argument("text")
        if op == "now":
            p.add_argument("--check", help="waiting check time: Nm or ISO UTC time")
            p.add_argument("--waiting", help="scratchpad Waiting text; empty text clears it")
            p.add_argument("--done", action="store_true", help="finish the previous Now instead of returning it to To-do")
        if op in ("done", "now"):
            p.add_argument("--proof", help="completion evidence: command, path or short result")
        if op == "show":
            p.add_argument("--json", action="store_true")
        if op == "watch":
            p.add_argument("--once", action="store_true", help="render one frame and exit")
            p.add_argument("--socket", help="owner Rex socket; close this viewer when its exact owner block disappears")
    subs.add_parser("hook", help="Claude seat UserPromptSubmit/Stop stdin hook; stale scratchpad blocks once per turn; AGENT_SCRATCHPAD required")
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
        path = scratch_path(o.session, o.block)
        if o.operation == "path":
            print(path)
        elif o.operation == "init":
            print(scratch_init(o.session, o.block, o.name, o.purpose, o.intent))
        elif o.operation == "show":
            data = scratch_read(path)
            if o.json:
                print(json.dumps({k: data[k] for k in ("purpose", "intent", "now", "todo", "done", "updated", "waiting", "done_when", "check", "blocked")}, ensure_ascii=False))
            else:
                print(scratch_render(data), end="")
        elif o.operation == "watch":
            if o.socket and not os.path.isabs(o.socket):
                raise ScratchError('absolute_socket_required')
            previous = None
            owner_error = None
            next_owner_check = 0
            while True:
                if o.socket and not o.once and time.monotonic() >= next_owner_check:
                    next_owner_check = time.monotonic() + 1
                    try:
                        if not scratch_watch_owner(o.socket, o.session, o.block):
                            break
                        owner_error = None
                    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                        # An unavailable server is not evidence that the owner is gone.
                        message = str(exc)
                        if message != owner_error:
                            print('Scratchpad owner check unavailable: ' + message, file=sys.stderr, flush=True)
                        owner_error = message
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
            proof = scratch_line(o.proof) if getattr(o, "proof", None) is not None else None
            completion = " — proof: " + proof if proof else " — unproven"
            with scratch_lock(path):
                data = scratch_read(path)
                if o.operation == "todo":
                    data["todo"].append(scratch_line(o.text))
                elif o.operation == "flag":
                    data["blocked"] = scratch_line(o.text) if o.text else ""
                elif o.operation == "now":
                    value = scratch_line(o.text)
                    data["blocked"] = ""
                    if o.check is not None:
                        data["check"] = scratch_check_time(o.check)
                    if data["now"]:
                        data["done" if o.done else "todo"].insert(0, data["now"] + completion if o.done else data["now"])
                    if value in data["todo"]:
                        data["todo"].remove(value)
                    data["now"] = value
                    if o.waiting is not None:
                        data["waiting"] = scratch_line(o.waiting) if o.waiting else ""
                        if not o.waiting:
                            data["check"] = ""
                elif data["now"]:
                    data["done"].insert(0, data["now"] + completion)
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
