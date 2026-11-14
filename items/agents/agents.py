"""Visible agent lifecycle. Python 3.9+ stdlib; embedded by the native CLI.

Only the in-pane supervisor waits for an agent. No daemon, screen-based ACK,
implicit endpoint, hidden fallback, creation retry or notification retry exists.
"""
import argparse
import base64
import contextlib
import datetime
import hashlib
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
import tempfile

class ActionParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n" + (f"next: {self.prog} --help\n" if (sys.stdin.isatty() and sys.stderr.isatty()) else ""))


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
        data = f.read() if limit is None else f.read(limit + 1)
    require(limit is None or len(data) <= limit, "file_too_large")
    return data


def lifecycle_events(state):
    """Only timestamped evidence; legacy records cannot reconstruct overwritten turns."""
    rows = []
    def add(at, event, **details):
        if type(at) is int and at > 0:
            rows.append(dict(at=at, event=event, **details))
    add(state.get("created_at"), "launched", evidence="launch_intent_not_creation_proof")
    add(state.get("protocol_ack_at"), "protocol_ack")
    if state.get("brief_attempted"):
        add(state.get("brief_attempt_at") or (state.get("brief_receipt") or {}).get("started_at_unix_ms"), "brief_attempted")
    hook = state.get("last_hook") or {}
    if hook.get("kind") in ("Stop", "StopFailure"):
        first = (hook.get("text") or "").splitlines()
        # Terminal output is data: never allow a report to inject terminal controls.
        line = "".join(c for c in (first[0] if first else "") if ord(c) >= 32 and not 127 <= ord(c) <= 159)[:180]
        add(hook.get("at"), hook["kind"], text=line, event_id=hook.get("event_id"), **({"delivery_rule": hook["delivery_rule"]} if hook.get("delivery_rule") else {}))
    if state.get("immediate_child_term") is not None:
        add(state.get("immediate_child_ended_at"), "child_exit", term=state["immediate_child_term"])
    acceptance = state.get("starter_acceptance") or {}
    add(acceptance.get("accepted_at"), "report_accepted", **acceptance)
    retired = state.get("retired") or {}
    add(retired.get("at"), "pruned", reason=retired.get("reason"))
    return rows


def history_add(history, event_id, entry, keep, duplicate_reason):
    require(event_id not in history, duplicate_reason)
    while len(history) >= keep:
        oldest = min(history, key=lambda key: (history[key].get("attempted_at", history[key].get("at", 0)), key))
        del history[oldest]
    history[event_id] = entry


def record_bytes(state):
    raw = json.dumps(state, ensure_ascii=False, sort_keys=True).encode()
    # This is a compaction target, never a limit on live metadata or work.
    while len(raw) > LIMIT:
        candidates = []
        for field in ("timeline", "notifications", "fleet_reports", "presentations"):
            history = state.get(field, [])
            if len(history) <= 1:
                continue
            if isinstance(history, list):
                key = min(range(len(history)), key=lambda i: history[i].get("at", 0))
                candidates.append((history[key].get("at", 0), field, key))
            else:
                key = min(history, key=lambda k: (history[k].get("attempted_at", history[k].get("at", 0)), k))
                candidates.append((history[key].get("attempted_at", history[key].get("at", 0)), field, key))
        if not candidates:
            break
        _, field, key = min(candidates)
        del state[field][key]
        if field == "timeline":
            state["timeline_partial"] = True
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True).encode()
    return raw


class Registry:
    """Stable advisory lock and per-launch durable intent, on a trusted local filesystem."""
    def __init__(self, root, lock_name="agents.lock", wait_ms=2000):
        self.root = absolute(root)
        self.lock_name, self.wait_ms = lock_name, wait_ms

    def __enter__(self):
        import fcntl
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            s = os.fstat(self.fd)
            require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, "private_owned_registry_required")
            # macOS can report ENOENT when several processes create the same lock file at once; retry briefly.
            for attempt in range(200):
                try:
                    self.lock = os.open(self.lock_name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                        0o600, dir_fd=self.fd)
                    break
                except FileNotFoundError:
                    if attempt == 199:
                        raise
                    time.sleep(.005)
            s = os.fstat(self.lock)
            require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and
                    stat.S_IMODE(s.st_mode) == 0o600 and s.st_nlink == 1, "private_owned_lock_required")
            end = time.monotonic() + self.wait_ms / 1000
            while True:
                try:
                    fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic() < end, "prune_in_progress" if self.lock_name == "prune.lock" else "registry_busy_after_2s_lock_wait")
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

    def read(self, launch_id, name=None):
        data = read_file(str(Path(self.root) / (name or self.name(launch_id))), limit=None, private=True)
        state = json.loads(data)
        require(state["schema_version"] == 1 and state["launch_id"] == launch_id, "invalid_lifecycle_record")
        return state

    def save(self, state, new=False, name=None):
        name = name or self.name(state["launch_id"])
        if new:
            require(not os.path.lexists(str(Path(self.root) / name)), "launch_already_exists")
        previous = {} if new else self.read(state["launch_id"], name)
        # The board's contract projection follows every starter rebind/fall-up.
        if isinstance(state.get("contract"), dict):
            state["contract"]["starter"] = state.get("starter")
        old_events = lifecycle_events(previous)
        state["timeline_partial"] = not new and ("timeline" not in previous or previous.get("timeline_partial", False))
        state["timeline"] = list(previous.get("timeline", old_events))
        state["timeline"].extend(event for event in lifecycle_events(state) if event not in old_events)
        raw = record_bytes(state)
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

    def write_message(self, launch_id, suffix, value, extension="txt"):
        name = "agents-" + identifier(launch_id) + "-" + suffix + "." + extension
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


RECORD = re.compile(r"agents-([0-9a-f]{32})\.json")
SETTLE_MS = 120000  # A launch still inside its queue/spawn/track window is never judged.


DETACHED_LUA = r'''local a=rex.args
local function call(method,args)
 local v,e=rex.call(method,args); if not v then error(e) end
 if #rex.json.encode(v)>262144 then error("response_exceeds_bound") end
 return v
end
local version=call("server.version")
if version.api_revision~=13 then error("detached_requires_API13") end
call("session.attach",{session_id=a.session_id})
if a.operation=="create" then
 local command={"/bin/sh","-c",'cd -- "$1" || exit 125\nshift\nexec "$@"',"teerex-agent",a.cwd}
 for _,v in ipairs(a.argv) do command[#command+1]=v end
 local made=call("session.new_block",{session_id=a.session_id,flavor="com.superlogical.terminal.shell",label=a.name,
  options={shell="none",login=false,interactive=false,cwd=a.cwd,command=command,exit={on_completion=false}}})
 a.block_id=made.block_id
end
local blocks=call("session.list_blocks",{session_id=a.session_id}).blocks or {}
local target
for _,b in ipairs(blocks) do if b.block_id==a.block_id then target=b end end
local result={placement=target and target.placement or "absent",block_id=a.block_id,focus_requested=false}
if a.operation=="forward" and target and target.placement=="detached" then
 local view=call("session.view",{session_id=a.session_id})
 local anchor
 for _,w in ipairs(view.windows or {}) do
  if w.window_id==view.active_window_id and not w.zoomed_block_id then anchor=w.focused_block_id end
 end
 if not anchor then error("no_focused_anchor") end
 call("session.move_block",{session_id=a.session_id,block_id=a.block_id,anchor_block_id=anchor,
  direction="horizontal",side="after",ratio=2/3})
 local after=call("session.view",{session_id=a.session_id})
 if after.active_window_id~=view.active_window_id then error("focus_changed") end
 for _,old in ipairs(view.windows) do for _,new in ipairs(after.windows or {}) do
  if old.window_id==new.window_id and old.focused_block_id~=new.focused_block_id then error("focus_changed") end
 end end
 result.placement="placed"
end
io.write(rex.json.encode(result),"\n")
'''


def detached_operation(state, operation, argv=None):
    """One bounded read/create/move on this launch's own exact pane; never retry."""
    target = state['target']
    request = dict(operation=operation, session_id=target['session_id'], block_id=target.get('block_id'),
                   cwd=state.get('cwd'), name=state.get('name'), argv=argv)
    command = [state.get('rex_executable') or 'rex', '--autostart=false', '--server', 'unix://' + state['socket'],
               '--timeout', '3s', '--color', 'never', 'do', '-e', __import__('teerex_pane_guard').prelude('unix://' + state['socket'], human_launch=state.get('human', False)) + DETACHED_LUA, '--args', json.dumps(request)]
    env = dict(os.environ, PATH=state.get('client_path') or os.defpath)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, timeout=5)
        output.seek(0)
        raw = output.read(262145)
    require(result.returncode == 0 and len(raw) <= 262144, 'detached_operation_unavailable_or_uncertain')
    return json.loads(raw)


def come_forward(state, event):
    if not state.get('come_forward'):
        return
    try:
        packet = detached_operation(state, 'forward')
        update(state['registry'], state['launch_id'], lambda s: s.update(come_forward_last=dict(event=event, at=now(), **packet)))
    except (OSError, ValueError, Refusal, subprocess.TimeoutExpired) as error:
        update(state['registry'], state['launch_id'], lambda s: s.update(come_forward_last=dict(event=event, at=now(), outcome='unknown', reason=str(error)[:160])))


def pane_absent(state):
    """True only on explicit absence from the complete block inventory; unavailable reads remain unknown."""
    t = state.get("target") or {}
    if not t.get("block_id"):
        return None
    try:
        packet = detached_operation(state, 'inspect')
        return packet['placement'] == 'absent'
    except (OSError, ValueError, Refusal, subprocess.TimeoutExpired):
        return None


def retirement(state, check_panes=True):
    """Why a record may leave the live registry, or None. Evidence first from the record, then one live pane read."""
    if check_panes and pane_absent(state) is True:
        return "pane_gone", dict(pane=state["target"]["block_id"], basis="session_list_blocks_absent")
    age = now() - int(state.get("created_at") or 0)
    if age < SETTLE_MS:
        return None, None
    if state.get("immediate_child_term") is not None:
        return "agent_exited", dict(immediate_child_term=state["immediate_child_term"])
    if state.get("phase") in ("creation_uncertain", "tracking_uncertain", "launch_failed"):
        return "never_started", dict(phase=state["phase"])
    return None, None


def archive_dir(registry):
    try:
        os.mkdir("archive", 0o700, dir_fd=registry.fd)
    except FileExistsError:
        pass
    fd = os.open("archive", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=registry.fd)
    s = os.fstat(fd)
    if not (s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700):
        os.close(fd)
        raise Refusal("private_owned_archive_required")
    return fd


def forget_job(root, state):
    """The pane is gone, so its jobs registration is history too. Local record only; never closes anything."""
    t = state["target"]
    code, listed = invoke(["jobs", "list", "--registry", root])
    entry = next((e for e in (listed or {}).get("entries", []) if isinstance(listed, dict)
                  and e.get("block_id") == t["block_id"] and e.get("session_id") == t["session_id"]), None)
    if entry is None:
        return "no_jobs_record"
    code, packet = invoke(["jobs", "forget", "--registry", root, "--socket", state["socket"], "--session", t["session_id"],
                           "--block", t["block_id"], "--owner", entry["owner"], "--generation", str(entry["generation"]),
                           "--reason", "agents prune: pane gone"])
    return packet.get("outcome", "uncertain") if isinstance(packet, dict) else "uncertain"


def forget_fleet(state):
    """Release only a verified absent pane's report, using the board's generation guard."""
    if not state.get("store"):
        return dict(outcome="not_requested")
    code, packet = invoke(["boards", "state", "inspect", "--store", state["store"]])
    if code or not isinstance(packet, dict):
        return dict(outcome="uncertain", client_exit=code, receipt=packet)
    board = packet["state"]
    if not any(row["target"] == state["target"] for row in board["fleet"]):
        return dict(outcome="no_fleet_record")
    t = state["target"]
    code, packet = invoke(["fleet", "forget", "--store", state["store"], "--host", t["host"],
                           "--socket", state["socket"], "--session", t["session_id"], "--block", t["block_id"],
                           "--generation", str(board["generation"]), "--reason", "agents prune: pane gone"])
    return dict(outcome="cleared" if code == 0 else "uncertain", client_exit=code, receipt=packet)



def retire_record(root, state, reason, evidence):
    launch_id = state["launch_id"]
    item = dict(launch_id=launch_id, name=state.get("name"), owner=state.get("owner"), phase=state.get("phase"),
                reason=reason, evidence=evidence)
    if reason == "pane_gone" or pane_absent(state) is True:
        for field, action in (("fleet_report", lambda: forget_fleet(state)), ("jobs", lambda: forget_job(root, state)),
                              ("scratchpad_archive", lambda: scratch_archive(state["scratchpad"], state["target"]["session_id"],
                                                                            state["target"]["block_id"]) if state.get("scratchpad") else None)):
            try:
                item[field] = action()
            except Exception as exc:
                item[field] = dict(outcome="uncertain", failure_reason=str(exc))
    with Registry(root) as registry:
        fd = archive_dir(registry)
        try:
            os.mkdir(launch_id, 0o700, dir_fd=fd)
            state = registry.read(launch_id)
            state["retired"] = dict(at=now(), reason=reason, evidence=evidence, by="teerex agents prune", cleanup=item)
            raw = json.dumps(state, ensure_ascii=False, sort_keys=True).encode()
            out = os.open(launch_id + "/retired.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(out, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            prefix = "agents-" + launch_id
            for n in os.listdir(registry.fd):
                if n.startswith(prefix):
                    os.rename(n, launch_id + "/" + n, src_dir_fd=registry.fd, dst_dir_fd=fd)
            os.fsync(fd)
            os.fsync(registry.fd)
        finally:
            os.close(fd)
    return item


def prune_records(root, apply):
    """Move retired launch records (and their message files) to ROOT/archive/<launch_id>/; history is kept, never deleted."""
    with Registry(root) as registry:
        names = sorted(n for n in os.listdir(registry.fd))
    ids = [m.group(1) for m in map(RECORD.fullmatch, names) if m]
    result = dict(live_before=len(ids), retired=[], kept=0, unknown=0, orphans=[], applied=apply)
    for launch_id in ids:
        try:
            state = load(root, launch_id)
        except (Refusal, OSError, ValueError, KeyError):
            result["unknown"] += 1
            continue
        reason, evidence = retirement(state)
        if reason is None:
            result["kept"] += 1
            continue
        item = dict(launch_id=launch_id, name=state.get("name"), owner=state.get("owner"), phase=state.get("phase"),
                    reason=reason, evidence=evidence)
        if apply:
            item = retire_record(root, state, reason, evidence)
        result["retired"].append(item)
    # Message files whose record is gone (crash residue) are archived too, after the settle window.
    live = set(ids) - {r["launch_id"] for r in result["retired"]} if apply else set(ids)
    with Registry(root) as registry:
        for n in sorted(os.listdir(registry.fd)):
            m = re.fullmatch(r"agents-([0-9a-f]{32})(-.+\.(?:txt|ts)|\.json\.next)", n)
            if not m or m.group(1) in live:
                continue
            st = os.stat(n, dir_fd=registry.fd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or (time.time() - st.st_mtime) * 1000 < SETTLE_MS:
                continue
            result["orphans"].append(n)
            if apply:
                fd = archive_dir(registry)
                try:
                    try:
                        os.mkdir("orphans", 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    os.rename(n, "orphans/" + n, src_dir_fd=registry.fd, dst_dir_fd=fd)
                finally:
                    os.close(fd)
    # A child may exit while its retained pane stays open. Its record is already
    # history when that pane eventually closes, so revisit only its remaining pad.
    result["archived_scratchpads"] = []
    history = Path(root) / "archive"
    if history.is_dir():
        for entry in history.iterdir():
            if not re.fullmatch("[0-9a-f]{32}", entry.name) or entry.is_symlink() or not entry.is_dir():
                continue
            try:
                old = json.loads(read_file(str(entry / "retired.json"), limit=None, private=True))
                pad = old.get("scratchpad")
                target = old.get("target") or {}
                if pane_absent(old) is not True:
                    continue
                if apply and old.get("store"):
                    forget_fleet(old)
                if not pad or not Path(pad).exists():
                    continue
                archived = scratch_archive(pad, target["session_id"], target["block_id"]) if apply else pad
                result["archived_scratchpads"].append(archived)
            except (Refusal, OSError, ValueError, KeyError):
                result["unknown"] += 1
    result["live_after"] = result["live_before"] - (len(result["retired"]) if apply else 0)
    return result


def prune(o):
    root = absolute(o.registry)
    with Registry(root, lock_name="prune.lock", wait_ms=o.launch_wait_ms):
        result = prune_records(root, o.apply)
    return 0, dict(schema_version=1, kind="agents_result", outcome="pruned" if o.apply else "prune_plan", **result,
                   archive=str(Path(root) / "archive"), process_lifetime="unchanged_not_verified", panes_closed=False)


def receipt(state, outcome, **extra):
    # Tokens, full argv, briefs and reports stay private; state files are the recovery interface.
    result = {k: state.get(k) for k in ("launch_id", "name", "owner", "purpose", "review_at", "profile", "target",
                                        "starter", "report_to", "human", "human_creator", "phase", "tracked", "protocol_acknowledged",
                                        "brief_attempted", "brief_outcome", "immediate_child_term", "remote_child_term", "notifications",
                                        "auto_prune", "failure_reason", "scratchpad_failure_reason", "fleet_report", "layout", "placement", "come_forward", "come_forward_last", "scratchpad", "scratch_pane_opened", "scratch_pane_receipt")}
    result["execution_host"] = state.get("execution", {}).get("host") if state.get("execution") else None
    result["immediate_child_role"] = "ssh_transport" if state.get("execution") else "agent_program"
    result.update(schema_version=1, kind="agents_result", outcome=outcome, agent_readiness="not_assessed",
                  task_completion="not_assessed", all_processes_verified_gone=False, exclusive_input_lease=False,
                  retry_safe=False, **extra)
    return result


def invoke(arguments, timeout=10, client_path=None, rex_executable=None, input_bytes=None, human_launch=False):
    """Bounded foreground client, never the agent. Retain diagnostics without treating exit as ACK."""
    import tempfile
    if arguments and arguments[0] == "send":
        # Native send can spend 55s guarding a draft plus a 60s transport budget.
        timeout = max(timeout, 120)
    if arguments and arguments[0] == "jobs":
        execution_ms = int(arguments[arguments.index("--timeout-ms") + 1]) if "--timeout-ms" in arguments else 5000
        timeout = max(timeout, 15 + execution_ms / 1000)  # 10s lock wait + live budget and cleanup.
    # Output sinks are private regular files, not pipes that a failed descendant can hold open.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as source:
        environment = dict(os.environ)
        if human_launch:
            environment["TEEREX_HUMAN_LAUNCH"] = "1"
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


def pane_presence(state, destination):
    code, packet = invoke(["boards", "probe", "--socket", destination.get("server", "unix://" + state["socket"])[7:]],
                          client_path=state["client_path"], rex_executable=state["rex_executable"])
    require(code == 0 and isinstance(packet, dict) and isinstance(packet.get("rows"), list),
            "destination_presence_unknown_no_reroute")
    return any(row["session"] == destination["session_id"] and row["block"] == destination["block_id"]
               for row in packet["rows"])


def registered_seat(state, destination):
    if destination.get("role") == "seat":
        return True
    if any(state.get(field) == destination and role == "seat"
           for field, role in state.get("destination_roles", {}).items()):
        return True
    if not state.get("store"):
        return False
    code, packet = invoke(["boards", "state", "inspect", "--store", absolute(state["store"])],
                          client_path=state["client_path"], rex_executable=state["rex_executable"])
    require(code == 0 and isinstance(packet, dict) and isinstance(packet.get("state"), dict),
            "seat_registration_lookup_failed")
    return any(seat["target"] == destination for seat in packet["state"]["seats"])


def seat_address(state):
    return dict(role="seat", host=state["target"]["host"], server="unix://" + state["socket"],
                session_id="seat", block_id="seat")


def delivery_destination(root, state, destination):
    """Fall up only after fresh absence evidence; unknown is never absence."""
    visited, absent = [], []
    while destination and destination not in visited:
        visited.append(destination)
        if registered_seat(state, destination):
            destination = seat_address(state)
            break
        if pane_presence(state, destination):
            break
        absent.append(destination)
        with Registry(root) as registry:
            parent = None
            for path in list(Path(root).glob("agents-*.json")) + list(Path(root).glob("archive/*/agents-*.json")):
                if not RECORD.fullmatch(path.name):
                    continue
                candidate = json.loads(read_file(str(path), limit=None, private=True))
                if candidate.get("target") == destination:
                    parent = candidate.get("starter")
                    break
        destination = parent
    else:
        require(state.get("store"), "no_live_starter_or_seat_store")
        destination = seat_address(state)
    if absent:
        def rerouted(s):
            s.setdefault("starter_faults", []).append(dict(at=now(), absent=absent, rerouted_to=destination))
            if s.get("contract"):
                s["contract"].update(stalled=False, lapses=0, last_contact_at=now())
        update(root, state["launch_id"], rerouted)
    return destination


def send(root, state, destination, body, label):
    if destination != state["target"]:
        destination = delivery_destination(root, state, destination)
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


# Contract

CONTRACT_REFUSE = 'Turn not ended: declare one — finished: every step checked off, To-do empty (teerex scratch done) | blocked: teerex scratch flag "what is stuck; what you tried; what you need" | waiting: teerex scratch now STEP --waiting "on what" --check 10m'


def contract_active(state):
    return bool(state.get("brief_attempted"))


def contract_turn(state):
    if not contract_active(state):
        return dict(status="not_applicable", action="allow")
    c = state["contract"]
    try:
        snapshot = contract_snapshot(state)
    except (OSError, ValueError):
        snapshot = dict(steps_total=0, step_n=0, now=None, declared=None, check_at=None, flag=None)
    c.update(snapshot)
    # The first empty turn can be the protocol ACK even if the brief arrived mid-turn.
    if not state.get("contract_turn_ended") and snapshot["steps_total"] == 0:
        return dict(status="protocol_ack", action="allow")
    needs_steps = snapshot["steps_total"] == 0 and not state.get("contract_turn_reported") and not state.get("contract_reminded")
    if snapshot["declared"] and not needs_steps:
        c["declared_at"] = now()
        return dict(status="declared", action="allow", declared=snapshot["declared"])
    previous = state.get("contract_reminded", False)
    state["contract_reminded"] = True
    reason = CONTRACT_REFUSE + ("; write your steps first" if snapshot["steps_total"] == 0 else "")
    return dict(status="undeclared", action="allow" if previous else "block", already_reminded=previous, reason=reason, contract=True)


def contract_init(state, profile, brief_text, done_when_arg, interval_arg):
    interval = interval_arg if interval_arg is not None else profile.get("contract_interval_s", 600)
    require(type(interval) is int and interval > 0, "invalid_contract_interval_s")
    fallback = next((m.group(1).strip(" :*—-\t") for line in (brief_text or "").splitlines()
                     if (m := re.match(r"^\s*(?:done when|done-when)\b(.*)", line, re.I))), "")
    done_when = done_when_arg if done_when_arg is not None else fallback or state.get("intent", state["purpose"])
    scratch_line(done_when)
    return dict(starter=state.get("starter"), task=state["purpose"], done_when=done_when, interval_s=interval,
                steps_total=0, step_n=0, now=None, last_contact_at=0, last_contact="",
                declared=None, declared_at=None, check_at=None, flag=None, lapses=0, stalled=False,
                awaiting_starter=None, starter_lapses=0)


def contract_snapshot(state):
    data = scratch_read(Path(state["scratchpad"]))
    total = bool(data["now"]) + len(data["todo"]) + len(data["done"])
    check_at = None
    if data.get("check"):
        try:
            parsed = datetime.datetime.fromisoformat(data["check"].replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                check_at = int(parsed.timestamp() * 1000)
        except ValueError:
            pass
    flag = None
    if data.get("blocked"):
        sha = hashlib.sha256(data["blocked"].encode()).hexdigest()
        previous = (state.get("contract") or {}).get("flag") or {}
        flag = dict(previous) if previous.get("sha") == sha else dict(text=data["blocked"], sha=sha, delivered_at=None)
    declarations = [name for name, holds in (("done", not data["now"] and not data["todo"] and bool(data["done"])),
                    ("blocked", bool(flag)), ("waiting", bool(data.get("waiting")) and check_at is not None and check_at > now())) if holds]
    return dict(steps_total=int(total), step_n=len(data["done"]) + bool(data["now"]), now=data["now"],
                declared=declarations[0] if len(declarations) == 1 else None, check_at=check_at, flag=flag)


def contract_seat(state):
    """Resolve only an explicitly registered seat on this launch's server."""
    if not state.get("store"):
        return None
    code, packet = invoke(["seat", "resolve", "--store", absolute(state["store"]),
                           "--host", state["target"]["host"], "--socket", state["socket"], "--json"],
                          client_path=state["client_path"], rex_executable=state["rex_executable"])
    require(code == 0 and isinstance(packet, dict) and packet.get("outcome") in ("resolved", "no_seat"),
            "contract_seat_lookup_failed")
    return packet.get("target")


def contract_tell(root, launch_id, kind, line, to="starter", last_message=None, turn_report=None):
    state = load(root, launch_id)
    if kind == "flag" and to == "starter":
        with Registry(root) as registry:
            state = registry.read(launch_id)
            flag = contract_snapshot(state)["flag"]
            require(flag is not None, "contract_flag_required")
            previous = state["contract"].get("flag") or {}
            if previous.get("sha") == flag["sha"] and (previous.get("attempt") or previous.get("delivered_at") is not None):
                return 0, dict(outcome="already_attempted", sha=flag["sha"])
            flag["attempt"] = now()
            state["contract"]["flag"] = flag
            registry.save(state)
    require(to in ("starter", "seat", "self"), "invalid_contract_destination")
    scratch_line(line)
    # Preserve the specified STEP/DONE/etc. prefix while ensuring every line identifies its worker.
    if state["name"] not in line:
        line = state["name"] + ": " + line
    destinations = [state["target"]] if to == "self" else [state.get("starter"), state.get("report_to")]
    if to == "seat":
        destinations = [seat_address(state)]
    destinations = [d for i, d in enumerate(destinations) if d and d not in destinations[:i]]
    sent_at = now()
    results = []
    for i, destination in enumerate(destinations):
        if turn_report is not None:
            claimed = False
            def claim(s):
                nonlocal claimed
                reports = s["contract"].setdefault("turn_reports", {})
                key = destination["session_id"] + "/" + destination["block_id"]
                previous = reports.get(key)
                expired = previous and previous.get("check_at") is not None and previous["at"] < previous["check_at"] <= sent_at
                if previous and previous["answer"] == turn_report and not expired and kind != "done":
                    return
                # Claim before input: an uncertain attempt must never be retried.
                reports[key] = dict(answer=turn_report, line=line, at=sent_at,
                                    check_at=state["contract"].get("check_at"))
                claimed = True
            update(root, launch_id, claim)
            if not claimed:
                continue
        sender = dict(state, name="teerex-scratchpad" if to == "self" else "teerex-contract")
        code, packet = send(root, sender, destination, line + ("\n" + last_message if last_message else ""), "contract-" + secrets.token_hex(16) + "-" + str(i))
        results.append(dict(client_exit=code, receipt=packet))
    if turn_report is not None and not results and destinations:
        return 0, dict(outcome="unchanged_turn_suppressed", results=[])
    queued = any(succeeded(r["client_exit"], r["receipt"], "queued") for r in results)
    ok = bool(results) and all(transport_ack(r["client_exit"], r["receipt"]) or
                               succeeded(r["client_exit"], r["receipt"], "queued") for r in results)
    if to == "starter":
        def told(s):
            c = s["contract"]
            if ok and kind != "lapse":
                c.update(last_contact_at=sent_at, last_contact=line, lapses=0, stalled=False)
            elif not ok:
                c["last_contact_failed"] = dict(at=sent_at, line=line, receipt=results)
            if kind == "flag" and c.get("flag", {}).get("sha") == flag["sha"]:
                c["flag"].update(delivered_at=now() if ok else None, receipt=results)
            if ok and kind in ("done", "flag") and s.get("last_input_at_ns", 0) < sent_at * 1000000:
                c.update(awaiting_starter=dict(kind=kind, at=sent_at), starter_lapses=0)
        update(root, launch_id, told)
    return (0 if ok else 1), dict(outcome=("queued" if queued else "transport_acknowledged") if ok else "uncertain", results=results)


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


def validate_adapter(harness, argv):
    require(harness in ("claude", "codex", "pi"), "unsupported_hook_harness")
    if harness == "claude":
        require(not any(a == "--settings" or a.startswith("--settings=") for a in argv), "profile_settings_conflict")
    if harness == "codex":
        require(not any(re.match(r"(?:(?:--config|-c)=?)?notify\s*=", a.strip()) for a in argv), "profile_notify_conflict")


def adapter_argv(argv, harness, command, root, launch_id, broker=None, tint_enabled=True):
    """Per-launch hooks only. The common adapter forwards one bounded event to stop/channel."""
    validate_adapter(harness, argv)
    if harness == "claude":
        hook = shlex.join([RUNTIME, "agents", "hook", "--harness", "claude", "--command-json", json.dumps(command), "--event-file", "-"])
        settings = {"hooks": {k: [{"hooks": [{"type": "command", "command": hook, "timeout": 250}]}]
                              for k in ("Stop", "StopFailure", "UserPromptSubmit")}}
        return argv + ["--settings", json.dumps(settings)]
    if harness == "codex":
        callback = [RUNTIME, "agents", "hook", "--harness", "codex", "--command-json", json.dumps(command), "--payload"]
        # JSON arrays/strings are also TOML arrays/basic strings.
        result = argv + ["-c", "notify=" + json.dumps(callback, ensure_ascii=True)]
        # No per-launch Codex hooks: review can prevent protocol ACK. Use notify's guarded reminder fallback.
        return result
    # Pi's explicit -e loads even with --no-extensions. Use settled, not agent_end:
    # retries/queued continuations can follow agent_end (installed Pi extension contract).
    source = """import { spawnSync } from 'node:child_process';
export default function(pi) {
  let outcome = 'completed';
  const call = (payload) => {
    const args = HOOK;
    const result = spawnSync(args[0], args.slice(1), {input: JSON.stringify(payload), encoding: 'utf8', timeout: 250000});
    if (result.error || result.status !== 0) throw new Error('teerex hook failed: ' + (result.error?.message ?? result.stderr));
    return JSON.parse(result.stdout);
  };
  pi.on('before_agent_start', async (event) => {
    call({hook_event_name: 'UserPromptSubmit', prompt: event.prompt ?? ''});
  });
  pi.on('agent_before_settle', async (event) => {
    outcome = event.outcome;
    if (event.outcome !== 'completed') return;
    const result = call({hook_event_name: 'ScratchCheck'});
    if (result.scratchpad_check?.action === 'block') return {continue: true, entries: [...(event.entries ?? []), {type: 'custom_message', customType: 'teerex-scratchpad', content: result.scratchpad_check?.contract ? result.scratchpad_check.reason : REMINDER, display: true}]};
  });
  pi.on('agent_settled', async (event, ctx) => {
    const messages = ctx.sessionManager.getBranch().filter(e => e.type === 'message').map(e => e.message);
    const last = [...messages].reverse().find(m => m.role === 'assistant');
    const text = (last?.content ?? []).filter(c => c.type === 'text').map(c => c.text).join('\\n');
    const failed = outcome === 'error';
    const payload = {hook_event_name: failed ? 'StopFailure' : 'Stop',
      last_assistant_message: text, error: (last?.errorMessage ?? 'Pi run failed').slice(0,600)};
    const args = HOOK;
    const result = spawnSync(args[0], args.slice(1), {input: JSON.stringify(payload), encoding: 'utf8', timeout: 250000});
    if (result.error || result.status !== 0) throw new Error('teerex stop report failed: ' + (result.error?.message ?? result.stderr));
  });
}
""".replace("HOOK", json.dumps([RUNTIME, "agents", "hook", "--harness", "pi", "--command-json", json.dumps(command), "--event-file", "-"], ensure_ascii=True)).replace("REMINDER", json.dumps(SCRATCH_REMINDER))
    if broker is None:
        with Registry(root) as registry:
            path = registry.write_message(launch_id, "pi-stop", source, extension="ts")
    else:
        # A fence exposes only the grant directory, never the lifecycle registry.
        fd = os.open("pi-stop.ts", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=broker.fd)
        with os.fdopen(fd, "w") as f:
            f.write(source)
            f.flush()
            os.fsync(f.fileno())
        path = str(Path(broker.handle).parent / "pi-stop.ts")
    return argv + ["--extension", path]


def hook(o):
    raw = o.payload.encode() if o.payload is not None else source_bytes(o.event_file)
    require(len(raw) <= 32768, "hook_event_too_large")
    event = json.loads(raw)
    require(isinstance(event, dict), "invalid_hook_event")
    scratch_enabled = bool(os.environ.get("AGENT_SCRATCHPAD") or os.environ.get("LC_AGENT_SCRATCHPAD"))
    if o.harness == "codex" and o.payload is not None:
        require(event.get("type") == "agent-turn-complete", "unsupported_codex_notification")
        last = event.get("last-assistant-message")
        if last is None:
            last = ""
        require(isinstance(last, str), "invalid_last_words")
        normalized = dict(hook_event_name="Stop", last_assistant_message=last)
        if scratch_enabled:
            inputs = event.get("input-messages", [])
            require(isinstance(inputs, list) and all(isinstance(v, str) for v in inputs), "invalid_codex_input_messages")
            turn_id = event.get("turn-id")
            require(turn_id is None or isinstance(turn_id, str) and 0 < len(turn_id) <= 128, "invalid_codex_turn_id")
            normalized.update(codex_notify=True, codex_turn_id=turn_id,
                              scratch_reminder_turn=any(SCRATCH_REMINDER in v or CONTRACT_REFUSE in v for v in inputs))
        event = normalized
    else:
        validate_hook_event(event)
    command = json.loads(o.command_json)
    require(isinstance(command, list) and command and all(isinstance(v, str) and "\0" not in v for v in command), "invalid_hook_command")
    absolute(command[0])
    if command[1:3] == ["agents", "channel"]:
        command += ["--request-id", secrets.token_hex(16)]
    if scratch_enabled:
        event["scratch_harness"] = o.harness
    result = subprocess.run(command, input=json.dumps(event).encode(), stdout=subprocess.PIPE, timeout=250)
    if result.returncode:
        sys.stdout.buffer.write(result.stdout)
        return result.returncode, None
    try:
        packet = json.loads(result.stdout)
    except ValueError:
        raise Refusal("hook_callback_invalid_receipt")
    require(isinstance(packet, dict), "hook_callback_invalid_receipt")
    check = packet.get("scratchpad_check", {})
    if o.harness == "claude" and check.get("action") == "block":
        print(json.dumps(dict(decision="block", reason=check["reason"] if check.get("contract") else SCRATCH_REMINDER)))
        return 0, None
    if o.harness == "claude":
        claude_stop_status(event, check, os.environ.get("AGENT_SCRATCHPAD") or os.environ.get("LC_AGENT_SCRATCHPAD"))
    return 0, packet


def tint_config(value):
    if value is False:
        return False
    require(value is None or isinstance(value, dict), "invalid_tint")
    defaults = dict(idle="#2a2013", error="#2a1414", done="#142a1a")
    if value is not None:
        require(set(value) <= set(defaults), "invalid_tint_key")
        require(all(isinstance(c, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) for c in value.values()), "invalid_tint_colour")
        defaults.update(value)
    return defaults


def program_status(state, status, detail, starting=False):
    try:
        # Rex OSC7501 is colon-separated key=value, NOT JSON; text fields are base64.
        def encoded(value):
            clean = "".join(c if ord(c) >= 32 and not 127 <= ord(c) <= 159 else " " for c in value)
            return base64.b64encode(" ".join(clean.split()).encode()).decode()
        tint = state.get("tint", tint_config(None))
        record_id = "teerex/tint" if tint is not False else "teerex"
        if tint is not False:
            sys.stdout.write("\x1b]11;" + tint[status] + "\x1b\\" if status in tint else "\x1b]111\x1b\\")
        title = state["name"]
        flourish = state.get("launch_flourish", "✦ ")
        if starting and flourish is not False:
            title, detail = flourish + title, "starting"
        app = state.get("harness", state.get("profile", "teerex-agent"))
        sys.stdout.write("\x1b]7501;state=" + status + ":id=" + record_id + ":app=" + app + ":title=" + encoded(title) +
                         ":msg=" + encoded(detail) + "\x07")
        sys.stdout.flush()
    except OSError as exc:
        with contextlib.suppress(Exception):
            update(state["registry"], state["launch_id"], lambda s: s.update(status_failure_reason=str(exc)[:600]))


def remote_exec(o):
    # Trusted operator argv, not a channel method. All SSH serialization belongs to targets exec.
    require(len(o.payload) <= 98304, "compute_payload_too_large")
    payload = json.loads(base64.b64decode(o.payload, validate=True))
    require(isinstance(payload, dict) and set(payload) - {"tint_enabled"} == {"argv", "cwd", "metadata", "protocol", "registry", "launch_id",
                                                          "token", "callbacks", "hook_events", "harness", "pane", "store"}, "invalid_compute_payload")
    require(type(payload.get("tint_enabled", True)) is bool, "invalid_compute_tint")
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
                                                           "AGENT_REGISTRY", "AGENT_SCRATCHPAD"}, "invalid_compute_metadata")
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
        command = [RUNTIME, "agents", "stop", "--registry", payload["registry"],
                   "--launch-id", payload["launch_id"], "--event-file", "-", "--callback-config", callbacks["config"],
                   "--callback-host", callbacks["host"]]
        # Pi needs a local extension file; use a private temporary directory on compute.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="teerex-hook-") as hook_root:
            argv = adapter_argv(argv, payload["harness"], command, hook_root, payload["launch_id"], tint_enabled=payload.get("tint_enabled", True))
            return run_remote_child(o, payload, metadata, callbacks, sid, bid, token, argv, protocol)
    return run_remote_child(o, payload, metadata, callbacks, sid, bid, token, argv, protocol)


def run_remote_child(o, payload, metadata, callbacks, sid, bid, token, argv, protocol):
    env = dict(os.environ)
    for key in ("AGENT_CHANNEL", "LC_AGENT_CHANNEL", "TEEREX_OPERATOR", "LC_TEEREX_OPERATOR", "TEEREX_OPERATOR_ACTIVE", "LC_TEEREX_OPERATOR_ACTIVE"):
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
    # Legacy field is accepted for profile compatibility; request counts never revoke a live channel.
    require(type(value["max_requests"]) is int, "invalid_delivery_count")
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


class Channel(ChannelService):
    """A launch-owned socket; the visible supervisor is its only servicing process.

    The directory is the only fence mount. No filesystem paths supplied by a peer are opened.
    Bearer authority is cooperative outside a fence, not authentication against the same account.
    """
    errors = ChannelService.errors + (Refusal,)
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
            for name in ("channel.sock", "handle.json", "pi-stop.ts"):
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
        event_id, operation = channel_request(request, self.state["launch_id"], self.token, self.policy["grants"])
        if operation == "ack":
            address_id(request["session"], "session")
            address_id(request["block"], "block")
        elif operation == "stop":
            validate_hook_event(request["event"], allow_transcript=False)
        def intent(s):
            require(s["immediate_child_term"] is None, "channel_child_already_exited")
            history = s.setdefault("channel_requests", {})
            require(event_id not in history, "channel_request_already_attempted_no_retry")
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

    def revoked(self):
        update(self.root, self.state["launch_id"], lambda s: s.update(channel_status="revoked"))


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
                event["last_assistant_message"] = transcript_last_text(event.get("transcript_path"))
            except (OSError, Refusal, ValueError):
                event["last_assistant_message"] = "(last words unavailable inside worker)"
        event.pop("transcript_path", None)
        request["event"] = event
    raw = json.dumps(request, ensure_ascii=False).encode() + b"\n"
    require(len(raw) <= 49152, "channel_frame_too_large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(250)
        try:
            client.connect(absolute(handle["socket"]))
            client.sendall(raw)
            packet = frame_read(client, budget=250)
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


def launch_failed(root, launch_id, reason):
    reason = " ".join(str(reason).split())[:600]
    return update(root, launch_id, lambda s: s.update(phase="launch_failed", failure_reason=reason))


def supervisor_launch_failed(o, reason):
    if getattr(o, "launch_failure_displayed", False):
        return
    reason = " ".join(str(reason).split())[:600]
    print(f"teerex: launch failed before the agent started: {reason} (launch {o.launch_id})", flush=True)
    o.launch_failure_displayed = True
    with contextlib.suppress(Exception):
        launch_failed(o.registry, o.launch_id, reason)
        update(o.registry, o.launch_id, lambda s: s.update(launch_failure_displayed_at=now()))


def launch(o):
    try:
        return launch_agent(o)
    except BaseException as exc:
        if getattr(o, "launch_id", None):
            with contextlib.suppress(Exception):
                state = load(o.registry, o.launch_id)
                if not state.get("protocol_file"):
                    launch_failed(o.registry, o.launch_id, str(exc) or type(exc).__name__)
        raise


def write_project_trust(path, result, mode):
    """Caller holds the sibling config lock; replace only after a complete write."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as out:
            temporary = out.name
            os.fchmod(out.fileno(), mode)
            out.write(result.encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def ensure_project_trust_json(profile, cwd, execution):
    if "project_trust_json" not in profile:
        return
    require(execution is None, "project_trust_json_requires_local_execution_host")
    path = Path(absolute(profile["project_trust_json"]))
    import fcntl
    cwd = str(Path(cwd).resolve(strict=True))

    def invalid_constant(value):
        raise ValueError("non-JSON numeric constant")

    def read():
        try:
            data = json.loads(path.read_bytes(), parse_constant=invalid_constant)
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            data, mode = {}, 0o600
        require(isinstance(data, dict), "invalid_project_trust_json_object")
        projects = data.setdefault("projects", {})
        require(isinstance(projects, dict), "invalid_project_trust_json_projects")
        project = projects.setdefault(cwd, {})
        require(isinstance(project, dict), "invalid_project_trust_json_project")
        return data, project, mode

    try:
        data, project, mode = read()
        if project.get("hasTrustDialogAccepted") is True:
            return
        with open(str(path) + ".lock", "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data, project, mode = read()
            if project.get("hasTrustDialogAccepted") is True:
                return
            project["hasTrustDialogAccepted"] = True
            write_project_trust(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", mode)
    except (OSError, ValueError) as exc:
        raise Refusal("project_trust_json_update_failed: " + type(exc).__name__) from exc


def project_trust_lines(source, cwd):
    """Conservative editor for canonical single-line tables without tomllib."""
    reason = "project_trust_toml_unsupported_without_tomllib"
    header = '[projects.' + json.dumps(cwd, ensure_ascii=False) + ']'
    lines = source.splitlines(keepends=True)
    target = trust = None
    in_target = False
    table = []
    multiline = None
    depth = 0
    projects_inline = False

    def tokens(line):
        # Only lex strings/comments and punctuation; do not validate unrelated values.
        nonlocal multiline
        result = []
        balance = 0
        pos = 0
        while pos < len(line):
            if multiline is not None:
                end = line.find(multiline, pos)
                while end >= 0 and multiline == '"' * 3 and (len(line[:end]) - len(line[:end].rstrip("\\"))) % 2:
                    end = line.find(multiline, end + 1)
                if end < 0:
                    return result, balance
                pos, multiline = end + 3, None
                continue
            char = line[pos]
            if char.isspace():
                pos += 1
            elif char == '#':
                break
            elif line[pos:pos + 3] in ('"' * 3, "'" * 3):
                multiline = line[pos:pos + 3]
                result.append('<multiline>')
                pos += 3
            elif char in ('"', "'"):
                match = re.match(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'", line[pos:])
                if match is None:
                    # Unrelated malformed content is not ours to repair.
                    result.append('<unparseable>')
                    break
                raw = match[0]
                try:
                    result.append(json.loads(raw) if char == '"' else raw[1:-1])
                except ValueError:
                    result.append('<unparseable>')
                pos += len(raw)
            elif char in '[]=.,{}':
                balance += (char in '[{') - (char in ']}')
                result.append(char)
                pos += 1
            else:
                match = re.match(r"[^\s\[\]=.,{}#\"']+", line[pos:])
                if match is None:
                    result.append('<unparseable>')
                    break
                result.append(match[0])
                pos += len(match[0])
        return result, balance

    for i, line in enumerate(lines):
        was_multiline = multiline is not None
        parts, balance = tokens(line)
        if not parts:
            continue
        if not was_multiline and depth == 0 and line.lstrip().startswith('['):
            table = parts[1:-1:2] if parts[-1] == ']' else []
            if 'projects' in parts and cwd in parts:
                require(line.strip() == header and target is None, reason)
                target, in_target = i, True
            else:
                in_target = False
            projects_inline = False
            continue
        if not was_multiline and depth == 0:
            equal = parts.index('=') if '=' in parts else -1
            keys = parts[:equal:2] if equal >= 0 else []
            if table == [] and keys[:1] == ['projects']:
                require(cwd not in keys[1:], reason)
                projects_inline = keys == ['projects']
            elif table == ['projects']:
                require(keys[:1] != [cwd], reason)
            if in_target:
                require(equal >= 1 and '<unparseable>' not in parts, reason)
                if keys[:1] == ['trust_level']:
                    require(keys == ['trust_level'] and trust is None, reason)
                    require(re.fullmatch(r"trust_level\s*=\s*(\"[^\"\\]*\"|'[^']*')(?:\s*#.*)?", line.strip()), reason)
                    trust = i
        if projects_inline:
            require(not any(value == cwd and parts[j + 1:j + 2] == ['='] for j, value in enumerate(parts)), reason)
        depth += balance
        if depth == 0:
            projects_inline = False
    require(not in_target or (multiline is None and depth == 0), reason)
    if trust is not None:
        value = lines[trust].split('=', 1)[1].strip()
        if re.fullmatch(r'''(?:"trusted"|'trusted')(?:\s*#.*)?''', value):
            return source
        lines[trust] = 'trust_level = "trusted"\n'
    elif target is not None:
        if not lines[target].endswith(('\n', '\r')):
            lines[target] += '\n'
        lines.insert(target + 1, 'trust_level = "trusted"\n')
    else:
        lines.append('\n' + header + '\ntrust_level = "trusted"\n')
    return ''.join(lines)


def ensure_project_trust(profile, cwd, execution):
    """Opt-in, execution-local TOML edit before any launch objects are created."""
    if "project_trust_toml" not in profile:
        return
    require(execution is None, "project_trust_toml_requires_local_execution_host")
    path = Path(absolute(profile["project_trust_toml"]))
    try:
        import fcntl
    except ImportError:
        raise Refusal("project_trust_toml_requires_file_locking")
    try:
        import tomllib
    except ImportError:
        tomllib = None
    cwd = str(Path(cwd).resolve(strict=True))

    def read():
        try:
            raw = path.read_bytes()
            data = tomllib.loads(raw.decode("utf-8")) if tomllib else None
            return raw, data, stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            return b"", {}, 0o600

    def trusted(data):
        projects = data.get("projects", {})
        require(isinstance(projects, dict), "invalid_project_trust_projects")
        project = projects.get(cwd, {})
        require(isinstance(project, dict), "invalid_project_trust_project")
        return project.get("trust_level") == "trusted"

    try:
        # Refuse unreadable/invalid input before even creating the lock file.
        raw, data, mode = read()
        if tomllib is None:
            already_trusted = project_trust_lines(raw.decode("utf-8"), cwd) == raw.decode("utf-8")
        else:
            already_trusted = trusted(data)
        if already_trusted:
            return
        with open(str(path) + ".lock", "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            raw, data, mode = read()
            if tomllib is None:
                result = project_trust_lines(raw.decode("utf-8"), cwd)
                if result != raw.decode("utf-8"):
                    write_project_trust(path, result, mode)
                return
            if trusted(data):
                return
            source = raw.decode("utf-8")
            lines = source.splitlines(keepends=True)
            headers = []
            offset = 0
            for line in lines:
                if line.lstrip().startswith("["):
                    try:
                        # A header-looking line inside a multiline string is not a boundary.
                        tomllib.loads(source[:offset])
                        header = tomllib.loads(line + "\n__teerex_probe__ = true\n")
                        headers.append((offset, offset + len(line), header))
                    except tomllib.TOMLDecodeError:
                        pass
                offset += len(line)
            target = None
            for i, (start, body, header) in enumerate(headers):
                if header == {"projects": {cwd: {"__teerex_probe__": True}}}:
                    target = (start, body, headers[i + 1][0] if i + 1 < len(headers) else len(source))
                    break
            if target is None:
                addition = '\n[projects.' + json.dumps(cwd, ensure_ascii=False) + ']\ntrust_level = "trusted"\n'
                result = source + addition
            else:
                start, body, end = target
                table = source[start:end]
                previous = len(source[start:body])
                changed = False
                pos = 0
                for line in table.splitlines(keepends=True):
                    pos += len(line)
                    try:
                        partial = tomllib.loads(table[:pos])["projects"][cwd]
                    except (tomllib.TOMLDecodeError, KeyError):
                        continue
                    if "trust_level" in partial:
                        result = source[:start + previous] + 'trust_level = "trusted"\n' + source[start + pos:]
                        changed = True
                        break
                    previous = pos
                if not changed:
                    result = source[:body] + 'trust_level = "trusted"\n' + source[body:]
            # Also catches unsupported inline/dotted table shapes without touching the file.
            require(trusted(tomllib.loads(result)), "project_trust_update_failed")
            write_project_trust(path, result, mode)
    except (OSError, ValueError) as exc:
        raise Refusal("project_trust_toml_update_failed: " + type(exc).__name__) from exc


def launch_agent(o):
    cfg = config(o.config)
    human = o.operation == "human"
    if human and cfg.get("human_route") and not o.routed:
        route = cfg["human_route"]
        require(isinstance(route, dict) and set(route) == {"config", "host", "profiles"}, "invalid_human_route")
        host = text(route["host"])
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", host), "invalid_human_host")
        # Reuse the named-host transport, including pinned executables, strict SSH and literal argv.
        command = [RUNTIME, "targets", "exec", "--config", absolute(route["config"]), "--host", host, "--tty", "--",
                   "agents", "human", "--config", absolute(route["profiles"]), "--profile", o.profile, "--routed"]
        if o.layout:
            command += ['--layout', o.layout]
        return subprocess.call(command), None
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
        validate_adapter(profile.get("harness", o.profile), argv)
    require(type(profile.get("scratch_pane", True)) is bool, "invalid_scratch_pane")
    layout = o.layout or profile.get('layout', 'tab')
    require(layout in ('tab', 'detached'), 'invalid_agent_layout')
    require(type(profile.get('come_forward', False)) is bool, 'invalid_come_forward')
    execution, callbacks = execution_config(profile)
    harness = profile.get("harness", o.profile)
    require(isinstance(harness, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,32}", harness), "invalid_status_app")
    flourish = profile.get("launch_flourish", "✦ ")
    require(flourish is False or isinstance(flourish, str) and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in flourish), "invalid_launch_flourish")
    tint = tint_config(profile.get("tint"))
    accounting = cost_settings(profile)
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
    session = address_id(o.session, "session")
    ss = address_id(o.starter_session, "session") if not human else None
    sb = address_id(o.starter_block, "block") if not human else None
    rs = address_id(o.report_to_session or ss, "session") if not human else None
    rb = address_id(o.report_to_block or sb, "block") if not human else None
    require(not human or (execution is None and delivery is None), "human_launch_uses_human_route_not_managed_execution_or_fence")
    name, owner, purpose = text(o.name or o.profile), text(o.owner), text(o.purpose, 256)
    host = text(o.host)
    cwd = absolute(o.cwd)
    ensure_project_trust(profile, cwd, execution)
    ensure_project_trust_json(profile, cwd, execution)
    review = o.review_at or now() + cfg.get("defaults", {}).get("review_after_ms", 3600000)
    require(type(review) is int and now() < review <= now() + 30 * 86400000, "invalid_review_at")
    brief = message(read_file(o.brief_file, 32768)) if o.brief_file else None
    intent = scratch_line(profile["intent"] if "intent" in profile else
                          next((line.strip() for line in (brief or "").splitlines() if line.strip()), purpose))
    launch_id, token = secrets.token_hex(16), secrets.token_hex(32)
    target = dict(host=host, server="unix://" + socket, session_id=session, block_id=None)
    starter = dict(host=host, server="unix://" + socket, session_id=ss, block_id=sb) if not human else None
    report_to = dict(host=host, server="unix://" + socket, session_id=rs, block_id=rb) if not human else None
    state = dict(schema_version=1, launch_id=launch_id, token=token, name=name, owner=owner, purpose=purpose,
                 review_at=review, target=target, starter=starter, report_to=report_to, profile=o.profile, argv=argv,
                 cwd=cwd, harness=harness, launch_flourish=flourish, resume_session_id=profile.get("resume_session_id"),
                 store=o.store, created_at=now(), socket=socket, registry=root, phase="creation_uncertain", tracked=False,
                 protocol_acknowledged=False, protocol_outcome=None, brief_attempted=False, brief_outcome=None,
                 immediate_child_term=None, notifications={}, brief_file=None, protocol_file=None,
                 hook_events=profile.get("hook_events", False), client_path=os.environ.get("PATH", os.defpath),
                 rex_executable=os.environ.get("TEEREX_INTERNAL_REX"), delivery=delivery, execution=execution,
                 callbacks=callbacks, cost=accounting, remote_child_term=None, human=human, scratch_pane=profile.get("scratch_pane", True), tint=tint, layout=layout, come_forward=profile.get("come_forward", False))
    if human:
        guard = __import__("teerex_pane_guard")
        if not guard.managed_agent():
            state["human_creator"] = guard.human_identity()
    if not human:
        if state.get("store"):
            try:
                state["destination_roles"] = {field: "seat" for field in ("starter", "report_to")
                    if registered_seat(state, state[field])}
            except (Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                state["role_lookup_failure"] = str(exc)
        state["intent"] = intent
        state["contract"] = contract_init(state, profile, brief, o.done_when, o.contract_interval_s)
    # Maintenance is independent of creation. One caller prunes; concurrent launches
    # proceed without waiting on its pane reads, jobs cleanup or fleet updates.
    try:
        with Registry(root, lock_name="prune.lock", wait_ms=0):
            pruned = prune_records(root, apply=True)
        state["auto_prune"] = dict(retired=len(pruned["retired"]), live_before=pruned["live_before"])
    except (Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        state["auto_prune"] = dict(outcome="skipped", reason=str(exc))
    with Registry(root) as registry:
        if brief is not None:
            state["brief_file"] = registry.write_message(launch_id, "brief", brief)
        registry.save(state, new=True)
    o.launch_id = launch_id  # Preserve the reason for every failure after the record exists.
    command = [RUNTIME, "agents", "supervise", "--registry", root, "--launch-id", launch_id]
    if layout == 'detached':
        try:
            made = detached_operation(state, 'create', command)
            code, packet = 0, dict(outcome='created_and_verified', created=dict(block_id=made['block_id']), placement=made['placement'])
        except (OSError, ValueError, Refusal, subprocess.TimeoutExpired):
            code, packet = 1, dict(outcome='creation_uncertain')
    elif human:
        code, packet = invoke(["surfaces", "open", "--socket", socket, "--session", session, "--layout", "tab",
                               "--label", name, "--cwd", cwd, "--", *command], human_launch=human)
    else:
        code, packet = invoke(["spawn", "--socket", socket, "--session", session, "--name", name, "--cwd", cwd,
                               "--report-to-session", rs, "--report-to-block", rb, "--", *command])
    def created(s):
        s["spawn_receipt"] = packet
        s["placement"] = packet.get("placement", "placed") if isinstance(packet, dict) and code == 0 else "unknown"
        if isinstance(packet, dict) and packet.get("created"):
            s["target"]["block_id"] = address_id(packet["created"]["block_id"], "block")
    state = update(root, launch_id, created)
    if not succeeded(code, packet, "created_and_verified" if human or layout == "detached" else "created_and_attached"):
        state = launch_failed(root, launch_id, (packet or {}).get("failure_reason") or (packet or {}).get("reason") or "creation_uncertain")
        return 1, receipt(state, "creation_uncertain", client_exit=code)
    try:
        block = state["target"]["block_id"]
        try:
            scratchpad = scratch_init(session, block, name, purpose, scratch_line(intent), (state.get("contract") or {}).get("done_when", ""))
        except Exception as exc:
            scratchpad = str(scratch_path(session, block))
            state = update(root, launch_id, lambda s: s.update(scratchpad_failure_reason=str(exc)[:600]))
        state = update(root, launch_id, lambda s: s.update(scratchpad=scratchpad))
        if state["scratch_pane"] and layout != "detached":
            side_code, side_packet = invoke(["surfaces", "open", "--socket", socket, "--session", session,
                                            "--layout", "tiled", "--anchor", block, "--label", name + " scratchpad",
                                            "--", RUNTIME, *(["--rex", state["rex_executable"]] if state.get("rex_executable") else []),
                                            "scratch", "watch", "--socket", socket, "--session", session, "--block", block, "--registry", root], human_launch=human)
            state = update(root, launch_id, lambda s: s.update(scratch_pane_receipt=side_packet,
                            scratch_pane_opened=succeeded(side_code, side_packet, "created_and_verified")))
        code, packet = invoke(["jobs", "track", "--registry", root, "--socket", socket, "--session", session, "--block", block,
                               "--owner", owner, "--kind", "agent", "--purpose", purpose,
                               "--deadline-unix-ms", str(review), "--cleanup", "manual"])
        def tracked(s):
            s["track_receipt"] = packet
            s["tracked"] = succeeded(code, packet, "verified")
            s["phase"] = "protocol_pending" if s["tracked"] else "tracking_uncertain"
        state = update(root, launch_id, tracked)
        if not state["tracked"]:
            state = launch_failed(root, launch_id, (packet or {}).get("failure_reason") or (packet or {}).get("reason") or "tracking_uncertain")
            return 1, receipt(state, "tracking_uncertain", client_exit=code)
        publish_fleet(root, state, "launch", "unknown", "Visible agent registered; protocol not acknowledged; readiness not assessed")
        state = load(root, launch_id)
        if human:
            with Registry(root) as registry:
                state = registry.read(launch_id)
                state["protocol_file"] = registry.write_message(launch_id, "human", "Human interactive launch; no brief or ACK.")
                state["phase"] = "human_interactive"
                registry.save(state)
            return 0, receipt(state, "human_launched")
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
                    f"Your session scratchpad is {scratchpad} (AGENT_SCRATCHPAD).\n"
                    + ('Contract: write your steps first; every turn after the brief ends declared — finished (every step checked off, To-do empty), blocked (teerex scratch flag "what is stuck; what you tried; what you need"; never check off steps you could not do), or waiting (teerex scratch now STEP --waiting "on what" --check 10m). teerex tells your starter each step and each declaration.\n' if state.get("contract") else "") +
                    "Keep its Now/To-do/Done current before and after every step; Now has at most one task.\n"
                    "Report stops, results, blockers and questions directly to report-to through teerex send.\n"
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
    except BaseException as exc:
        with contextlib.suppress(Exception):
            launch_failed(root, launch_id, str(exc) or type(exc).__name__)
        raise
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
        state["brief_attempt_at"] = now()
        if state.get("contract"):
            state["contract"]["last_contact_at"] = state["brief_attempt_at"]
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
    try:
        return publish_fleet_attempt(root, state, event_id, reported_state, detail)
    except (Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        report = dict(event_id=event_id, outcome="uncertain", failure_reason=str(exc)[:600])
        update(root, state["launch_id"], lambda s: s.update(fleet_report=report))
        return 1


def publish_fleet_attempt(root, state, event_id, reported_state, detail):
    if state["store"] is None:
        return 0
    def intent(s):
        history = s.setdefault("fleet_reports", {})
        history_add(history, event_id, dict(outcome="uncertain", attempted_at=now()), 65, "fleet_report_already_attempted")
    update(root, state["launch_id"], intent)
    code, packet = invoke(["fleet", "report", "--store", state["store"], "--host", state["target"]["host"],
                           "--socket", state["socket"], "--session", state["target"]["session_id"],
                           "--block", state["target"]["block_id"], "--owner", state["owner"], "--purpose", state["purpose"],
                           "--state", reported_state, "--detail", detail[:512]], client_path=state["client_path"],
                          rex_executable=state["rex_executable"])
    def reported(s):
        report = dict(outcome="reported" if code == 0 else "uncertain", client_exit=code, receipt=packet)
        s["fleet_reports"][event_id].update(report)
        s["fleet_report"] = dict(event_id=event_id, **report)
    update(root, state["launch_id"], reported)
    return code


def turn_report_rule(root, state, kind):
    if kind == "StopFailure":
        return "harness_failed"
    try:
        path = Path(state["scratchpad"])
        data = scratch_read(path)
        raw = read_file(str(path)).decode("utf-8")
        if not data.get("now"):
            return "finished_now_empty"
        section = re.search(r"(?ms)^## Now\s*\n(.*?)(?=^## |\Z)", raw)
        if not data.get("todo") and section and re.search(r"(?m)^-\s+\[[xX]\]\s+", section[1]):
            return "finished_now_done"
        waiting = data.get("waiting")
        match = re.search(r"(?m)^Waiting:\s*(.+?)\s*·\s*(.+?)\s*·\s*since\s+(.+)$", raw)
        on = waiting.get("on") if isinstance(waiting, dict) else match[1].strip() if match else None
        if on:
            names = {"seat"}
            target = state.get("report_to") or state.get("starter")
            if target:
                for record in Path(root).glob("agents-*.json"):
                    candidate = json.loads(read_file(str(record), limit=None, private=True))
                    address = candidate.get("target") or {}
                    if all(address.get(k) == target.get(k) for k in ("session_id", "block_id")):
                        names.add(candidate.get("name"))
                code, packet = invoke(["surfaces", "inspect", "--socket", state["socket"],
                    "--session", target["session_id"], "--pane", target["block_id"]],
                    client_path=state["client_path"], rex_executable=state["rex_executable"])
                if not code and isinstance(packet, dict):
                    names.add((packet.get("actual") or {}).get("label"))
            if on in names:
                return "waiting_on_report_to_or_seat"
        return "progress_turn_suppressed"
    except (OSError, ValueError, KeyError, Refusal, subprocess.SubprocessError):
        return "scratchpad_unreadable"


def notify(root, launch_id, event_id, body, evidence, reported_state="unknown", delivery_rule=None):
    with Registry(root) as registry:
        state = registry.read(launch_id)
        history_add(state["notifications"], event_id,
                    dict(outcome="uncertain", evidence=evidence, attempted_at=now(), delivery_rule=delivery_rule),
                    64, "notification_already_attempted")
        registry.save(state)
    # Starter and report-to can differ; notify both, deduplicating the exact tuple.
    destinations = [state["starter"]] if state["starter"] is not None else []
    if state["report_to"] is not None and state["report_to"] != state["starter"]:
        destinations.append(state["report_to"])
    if delivery_rule == "progress_turn_suppressed":
        destinations = []
    results = []
    for i, destination in enumerate(destinations):
        code, packet = send(root, state, destination, body, "notice-" + event_id + "-" + str(i))
        results.append(dict(target=destination, client_exit=code, receipt=packet,
                            outcome="queued" if succeeded(code, packet, "queued") else "transport_acknowledged" if transport_ack(code, packet) else "uncertain"))
    def reported(s):
        s["notifications"][event_id]["results"] = results
        outcomes = {r["outcome"] for r in results}
        s["notifications"][event_id]["outcome"] = (
            "suppressed" if delivery_rule == "progress_turn_suppressed" else
            "uncertain" if "uncertain" in outcomes else
            "queued" if "queued" in outcomes else "transport_acknowledged")
    state = update(root, launch_id, reported)
    publish_fleet(root, state, event_id, reported_state, body.replace("\n", " "))
    state = load(root, launch_id)
    ok = state["notifications"][event_id]["outcome"] in ("transport_acknowledged", "queued", "suppressed")
    outcome = ("notification_suppressed" if delivery_rule == "progress_turn_suppressed" else
               "notification_queued" if ok and state["notifications"][event_id]["outcome"] == "queued" else
               "notification_acknowledged" if ok else "notification_uncertain")
    return (0 if ok else 1), receipt(state, outcome, delivery_rule=delivery_rule)


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
                event["last_assistant_message"] = transcript_last_text(event.get("transcript_path"))
            except (OSError, Refusal, ValueError):
                event["last_assistant_message"] = "(last words unavailable on compute host)"
        event.pop("transcript_path", None)
        args = callback_command(dict(config=absolute(o.callback_config), host=o.callback_host),
                                ["stop", "--registry", o.registry, "--launch-id", o.launch_id, "--event-file", "-", "--event-id", event_id])
        return invoke(args[1:], timeout=250, input_bytes=json.dumps(event, ensure_ascii=False).encode())
    return report_stop(o.registry, o.launch_id, event_id, event)


def validate_hook_event(event, allow_transcript=True):
    require(isinstance(event, dict), "invalid_hook_event")
    require(event.get("hook_event_name") in ("Stop", "StopFailure", "UserPromptSubmit", "ScratchCheck"), "unsupported_hook_event")
    require(isinstance(event.get("last_assistant_message", "") or "", str), "invalid_last_words")
    require(len(json.dumps(event).encode()) <= 32768, "hook_event_too_large")
    require(allow_transcript or "transcript_path" not in event, "channel_transcript_path_forbidden")


def delivered_input(root, launch_id, event):
    def started(s):
        if event.get("reminder"):
            s["last_reminder_at_ns"] = event["at_ns"]
            return
        s["last_input_at_ns"] = event["at_ns"]
        c = s.get("contract")
        if c and event["at_ns"] >= c.get("last_contact_at", 0) * 1000000:
            c.update(stalled=False, lapses=0, last_contact_at=event["at_ns"] // 1000000)
        pending = (c or {}).get("awaiting_starter")
        if pending and event["at_ns"] >= pending["at"] * 1000000:
            c.update(awaiting_starter=None, starter_lapses=0)
            c.pop("starter_reminded_at", None)
        previous = s.get("last_hook") or {}
        if event["at_ns"] <= previous.get("at_ns", previous.get("at", 0) * 1000000):
            return
        if not event.get("reminder"):
            s.update(turn_started_at=event["at_ns"] // 1000000, scratch_reminded=False, scratch_reminder_pending=False, contract_reminded=False)
        s["last_hook"] = dict(kind="UserPromptSubmit", state="working", at=event["at_ns"] // 1000000,
                              at_ns=event["at_ns"], text="acknowledged input delivered", evidence="send_paste_and_enter_acknowledged")
    return update(root, launch_id, started)


def report_stop(root, launch_id, event_id, event, allow_transcript=True):
    validate_hook_event(event, allow_transcript)
    kind = event["hook_event_name"]
    event_at_ns = time.time_ns()
    if kind == "UserPromptSubmit":
        def started(s):
            previous = s.get("last_hook") or {}
            if event_at_ns < previous.get("at_ns", previous.get("at", 0) * 1000000):
                return
            scratch_turn(s, event, s.get("scratchpad"))
            s["contract_reminded"] = False
            if s.get("contract"):
                s["contract"].update(stalled=False, lapses=0, last_contact_at=now())
            s["last_hook"] = dict(kind=kind, state="working", at=now(), at_ns=event_at_ns, text="turn started")
        state = update(root, launch_id, started)
        return 0, receipt(state, "turn_started")
    check = None
    if kind != "StopFailure" and event.get("scratch_harness") in ("claude", "codex", "pi"):
        def checked(s):
            basis = "prompt_submit_or_initial_child_start"
            if event["scratch_harness"] == "codex" and event.get("codex_notify"):
                # Notify supplies a turn ID and inputs, but no start timestamp. Its previous
                # notification is the available lower bound; never invent an exact prompt time.
                continuation = s.get("scratch_reminder_pending") and event.get("scratch_reminder_turn")
                turn = event.get("codex_turn_id")
                if turn and turn != s.get("codex_turn_id") and not continuation:
                    s.update(turn_started_at=s.get("codex_last_notify_at", s.get("turn_started_at", now())), scratch_reminded=False, contract_reminded=False)
                    s["scratch_reminder_pending"] = False
                s["codex_turn_id"] = turn
                s["codex_last_notify_at"] = now()
                basis = "previous_notify_or_initial_child_start_actual_turn_start_unknown"
            s["scratchpad_check"] = dict(scratch_turn(s, event, s.get("scratchpad")), basis=basis)
            if s.get("contract") and contract_active(s) and s["scratchpad_check"]["action"] == "allow":
                contract_check = contract_turn(s)
                s["contract_check"] = contract_check
                if contract_check["action"] == "block":
                    s["scratchpad_check"].update(action="block", reason=contract_check["reason"], contract=True)
            if event["scratch_harness"] == "codex" and s["scratchpad_check"]["action"] == "block":
                s["scratch_reminder_pending"] = True
        state = update(root, launch_id, checked)
        check = state["scratchpad_check"]
        if check["action"] == "block" and event["scratch_harness"] == "codex":
            target = state["target"]
            code, packet = invoke(["send", "--socket", state["socket"], "--session", target["session_id"],
                                   "--block", target["block_id"], "--from", "teerex-scratchpad", "--message-file", "-"],
                                  timeout=45, client_path=state["client_path"], rex_executable=state["rex_executable"],
                                  input_bytes=(check["reason"] if check.get("contract") else SCRATCH_REMINDER).encode())
            check = dict(check, action="reminded", reminder_exit=code, reminder_receipt=packet)
            state = update(root, launch_id, lambda s: s.update(scratchpad_check=check))
            return 0, receipt(state, "scratchpad_blocked", scratchpad_check=check)
        elif check["action"] == "block" or kind == "ScratchCheck":
            return 0, receipt(state, "scratchpad_blocked" if check["action"] == "block" else "scratchpad_checked", scratchpad_check=check)
    if kind == "ScratchCheck":
        return 0, receipt(load(root, launch_id), "scratchpad_not_checked", scratchpad_check=dict(status="not_checked", action="allow"))
    last = event.get("last_assistant_message", "") or ""
    if allow_transcript and kind == "Stop" and not last:
        try:
            last = transcript_last_text(event.get("transcript_path"))
        except (OSError, Refusal, ValueError):
            last = "(last words unavailable: transcript could not be read)"
    error = str(event.get("error") or event.get("error_details") or event.get("message") or "unknown error")
    details = (last or "(no last words supplied)") if kind == "Stop" else error[:600]
    state = load(root, launch_id)
    # Hook metadata reports a turn, never process death; only invocation IDs deduplicate.
    title = "NOT DONE" if kind == "Stop" else "ERROR (harness failure report, death not verified)"
    body = f"{title}: {state['name']}\n{details}"
    if check and check["status"] == "stale":
        body += "\nScratchpad: stale; " + check["action"]
    if state.get("contract") and contract_active(state) and kind == "Stop" and not event.get("scratch_harness"):
        # Direct stop callbacks also enforce declaration after the brief.
        state = update(root, launch_id, lambda s: s.update(contract_check=contract_turn(s)))
        if state["contract_check"]["action"] == "block":
            return 0, receipt(state, "scratchpad_blocked", scratchpad_check=state["contract_check"])
    if (state.get("contract") and contract_active(state) and kind == "Stop"
            and (state.get("contract_check") or {}).get("status") != "protocol_ack"):
        c = state["contract"]
        declared = c.get("declared")
        if declared == "done":
            body = f"DONE {state['name']}: {c['done_when']} — " + " ".join(details.split())[:300]
        elif declared == "blocked":
            body = f"NOT DONE {state['name']} step {c['step_n']}/{c['steps_total']}: {c['flag']['text']}"
        elif declared == "waiting":
            waiting = scratch_read(Path(state["scratchpad"]))["waiting"]
            clock = datetime.datetime.fromtimestamp(c["check_at"] / 1000, datetime.timezone.utc).strftime("%H:%MZ")
            body = f"NOT DONE {state['name']} step {c['step_n']}/{c['steps_total']}: {waiting}; checks again {clock}"
        else:
            body = f"NOT DONE {state['name']} step {c['step_n']}/{c['steps_total']}: ended its turn without declaring done, blocked or waiting"
        delivery_rule = "contract_" + (declared or "no_answer")
    else:
        delivery_rule = turn_report_rule(root, state, kind)
    if kind == "Stop" and not delivery_rule.startswith("contract_"):
        try:
            snapshot = contract_snapshot(state)
        except (OSError, ValueError, KeyError):
            snapshot = dict(step_n=0, steps_total=0)
        if delivery_rule in ("finished_now_empty", "finished_now_done") and (state.get("contract_check") or {}).get("status") != "protocol_ack":
            body = f"DONE {state['name']}: " + " ".join(details.split())[:300] + "\n" + details
        else:
            reason = "protocol acknowledged; awaiting task steps" if (state.get("contract_check") or {}).get("status") == "protocol_ack" else "turn ended with work remaining"
            if check and check["status"] == "stale":
                reason += "; Scratchpad: stale; " + check["action"]
            body = f"NOT DONE {state['name']} step {snapshot['step_n']}/{snapshot['steps_total']}: {reason}"
    turn_state = "error" if kind == "StopFailure" else "done" if delivery_rule in ("finished_now_empty", "finished_now_done", "contract_done") else "idle"
    def remembered(s):
        previous = s.get("last_hook") or {}
        if event_at_ns < previous.get("at_ns", previous.get("at", 0) * 1000000):
            return
        s["contract_turn_ended"] = True
        if s.get("contract"):
            s["contract"].update(stalled=False, lapses=0, last_contact_at=now())
        s["last_hook"] = dict(kind=kind, state=turn_state, at=now(), at_ns=event_at_ns, text=details, event_id=event_id, evidence="harness_report_not_process_death", scratchpad_check=check, delivery_rule=delivery_rule)
    update(root, launch_id, remembered)
    if delivery_rule.startswith("contract_"):
        update(root, launch_id, lambda s: s.update(contract_turn_reported=True))
        declared = state["contract"].get("declared")
        def reporting(s):
            history_add(s["notifications"], event_id,
                        dict(outcome="uncertain", attempted_at=now(), delivery_rule=delivery_rule,
                             evidence="harness_report_not_process_death"), 64, "notification_already_attempted")
        update(root, launch_id, reporting)
        last_message = details if declared == "done" else None
        if declared == "blocked":
            # The supervisor may already have sent FLAG. Attach last words once per
            # flag, while every turn still sends its own NOT DONE answer.
            with Registry(root) as registry:
                current = registry.read(launch_id)
                flag = current["contract"]["flag"]
                if not flag.get("last_message_attempted"):
                    flag["last_message_attempted"] = now()
                    last_message = details
                    registry.save(current)
        turn_report = dict(outcome="done", step_n=c["step_n"], steps_total=c["steps_total"], reason=c["done_when"])
        if declared != "done":
            reason = c["flag"]["text"] if declared == "blocked" else waiting if declared == "waiting" else "ended its turn without declaring done, blocked or waiting"
            turn_report = dict(outcome=declared or "no_answer", step_n=c["step_n"],
                               steps_total=c["steps_total"], reason=reason)
        code, delivery = contract_tell(root, launch_id, declared or "no_answer", body,
                                       last_message=last_message, turn_report=turn_report)
        update(root, launch_id, lambda s: s["notifications"][event_id].update(outcome=("queued" if delivery.get("outcome") == "queued" else "transport_acknowledged") if code == 0 else "uncertain", receipt=delivery))
        state = load(root, launch_id)
        publish_fleet(root, state, event_id, "completed" if declared == "done" else "blocked" if declared in ("blocked", "waiting") else "idle", body)
        packet = receipt(load(root, launch_id), ("notification_queued" if delivery.get("outcome") == "queued" else "notification_acknowledged") if code == 0 else "notification_uncertain", delivery_rule=delivery_rule, contract_delivery=delivery)
    else:
        code, packet = notify(root, launch_id, event_id, body, "harness_report_not_process_death",
                              reported_state=("completed" if turn_state == "done" else "idle") if kind == "Stop" else "unknown", delivery_rule=delivery_rule)
    if check is not None:
        packet["scratchpad_check"] = check
    packet["turn_state"] = turn_state
    return code, packet


def supervisor_error(o, field, exc):
    # The supervisor shares the harness terminal: diagnostics belong only in its private record.
    with contextlib.suppress(Exception):
        with Registry(o.registry) as registry:
            state = registry.read(o.launch_id)
            if field not in state:
                state[field] = dict(reason=str(exc)[:600], at=now())
                registry.save(state)


def contract_steps(root, launch_id, previous):
    state = load(root, launch_id)
    if not state.get("contract") or not contract_active(state):
        return previous
    try:
        snapshot = contract_snapshot(state)
        done = scratch_read(Path(state["scratchpad"]))["done"]
    except (OSError, ValueError):
        return previous
    old_now, old_done = previous
    name = state["name"]
    n, total = snapshot["step_n"], snapshot["steps_total"]
    # Done is newest first. Count repeated labels separately rather than treating them as a set.
    remaining = list(old_done)
    added = []
    for item in reversed(done):
        if item in remaining:
            remaining.remove(item)
        else:
            added.append(item)
    finished_n = len(done) - len(added)
    for item in added:
        finished_n += 1
        contract_tell(root, launch_id, "step", f"STEP {name} {finished_n}/{total} finished: {item}")
    if snapshot["now"] and snapshot["now"] != old_now:
        contract_tell(root, launch_id, "step", f"STEP {name} {n}/{total} started: {snapshot['now']}")
    flag = snapshot.get("flag")
    if flag:
        contract_tell(root, launch_id, "flag", f"FLAG {name} step {n}/{total}: {flag['text']}")
    # contract_tell owns delivery/contact fields; never replace them with a stale snapshot.
    fields = {key: snapshot[key] for key in ("steps_total", "step_n", "now", "declared", "check_at")}
    if any(state["contract"].get(key) != value for key, value in fields.items()):
        update(root, launch_id, lambda s: s["contract"].update(fields))
    return snapshot["now"], list(done)


def contract_observation(state):
    code, packet = invoke(["observe", "--state", "--socket", state["socket"],
                           "--session", state["target"]["session_id"], "--block", state["target"]["block_id"]],
                          client_path=state["client_path"], rex_executable=state["rex_executable"])
    require(code == 0 and isinstance(packet, dict), "worker_activity_unknown_no_stall")
    records = packet.get("osc7501", {}).get("records", [])
    busy = packet.get("state") == "working" or any(record.get("state") == "working" for record in records)
    quiet = not busy and packet.get("state") in ("idle_prompt", "awaiting_choice", "awaiting_text", "error", "exited")
    return busy, quiet


def contract_lapse(root, launch_id):
    state = load(root, launch_id)
    c = state.get("contract")
    if not c or not contract_active(state) or c.get("declared") == "done":
        return
    timestamp = now()
    window = max(c["last_contact_at"], c.get("last_lapse_at", 0), c.get("last_lapse_check_at", 0))
    elapsed = timestamp - c["last_contact_at"]
    check = c.get("check_at")
    if timestamp - window <= c["interval_s"] * 1000 and not (check and window < check <= timestamp):
        return
    starter = state.get("starter")
    if starter and not pane_presence(state, starter):
        def starter_fault(s):
            current = s["contract"]
            if current.get("absent_starter") != starter:
                s.setdefault("starter_faults", []).append(dict(at=timestamp, absent=[starter], fault="starter_absent"))
            current.update(absent_starter=starter, stalled=False, lapses=0, last_lapse_check_at=timestamp)
        update(root, launch_id, starter_fault)
        contract_tell(root, launch_id, "starter_absent",
                      f"STARTER ABSENT {state['name']}: starter pane is gone; responsibility rerouted")
        return
    busy, quiet = contract_observation(state)
    def observed(s):
        current = s["contract"]
        current["last_lapse_check_at"] = timestamp
        if busy:
            current.update(stalled=False, lapses=0)
    update(root, launch_id, observed)
    if busy or not quiet:
        return
    lapses = c["lapses"] + 1
    name = state["name"]
    instruction = "tell your starter now what is stuck, what you tried, what you need"
    line = f"LAPSE {name} step {c['step_n']}/{c['steps_total']}: no contact for {elapsed // 60000} min; {instruction}"
    def lapsed(s):
        # Supervisor delivery is not contact from the worker; real contact wins a dispatch race.
        if s["contract"]["last_contact_at"] == c["last_contact_at"]:
            s["contract"].update(lapses=lapses, stalled=True, last_lapse_at=timestamp)
    update(root, launch_id, lapsed)
    if lapses == 1:
        contract_tell(root, launch_id, "wake", instruction, to="self")
    contract_tell(root, launch_id, "lapse", line)
    if lapses == 2:
        contract_tell(root, launch_id, "lapse", line, to="seat")


def contract_starter(root, launch_id):
    state = load(root, launch_id)
    c = state.get("contract") or {}
    pending = c.get("awaiting_starter")
    if not pending or not contract_active(state):
        return
    timestamp = now()
    if timestamp - max(pending["at"], c.get("starter_reminded_at", 0)) <= c["interval_s"] * 1000:
        return
    lapses = c["starter_lapses"] + 1
    line = f"UNANSWERED {state['name']} {pending['kind']} from {(timestamp - pending['at']) // 60000} min ago: accept it or send it back; accept: teerex agents accept --launch-id {launch_id}"
    def reminded(s):
        if s["contract"].get("awaiting_starter") == pending:
            s["contract"].update(starter_lapses=lapses, starter_reminded_at=timestamp)
    update(root, launch_id, reminded)
    contract_tell(root, launch_id, "unanswered", line)
    if lapses == 2:
        contract_tell(root, launch_id, "unanswered", line, to="seat")


def close_scratch_viewer(state):
    """Only this launch's exact, successfully created side pane is owned."""
    side = state.get('scratch_pane_receipt') or {}
    block = (side.get('created') or {}).get('block_id')
    if side.get('outcome') != 'created_and_verified' or not block:
        return dict(outcome='no_recorded_viewer')
    address_id(block, 'block')
    code, packet = invoke(['surfaces', 'close', '--socket', state['socket'],
                           '--session', state['target']['session_id'], '--pane', block],
                          client_path=state['client_path'], rex_executable=state['rex_executable'])
    return dict(client_exit=code, receipt=packet)


def supervise(o):
    signal.signal(signal.SIGHUP, terminate)
    state = None
    try:
        state = load(o.registry, o.launch_id)
        return supervise_child(o)
    except Exception as exc:
        supervisor_error(o, "last_supervisor_error", exc)
        if not getattr(o, "child_started", False):
            supervisor_launch_failed(o, str(exc))
        return 1, None
    finally:
        if state is not None:
            try:
                agent_input_path(state["socket"], os.environ["REX_SESSION"], os.environ["REX_BLOCK"]).unlink(missing_ok=True)
            except Exception as exc:
                supervisor_error(o, "last_supervisor_cleanup_error", exc)
            try:
                with Registry(o.registry, lock_name="prune.lock", wait_ms=60000):
                    current = load(o.registry, o.launch_id)
                    if pane_absent(current) is True:
                        retire_record(o.registry, current, "pane_gone", dict(basis="supervisor_exit_pane_absent"))
            except FileNotFoundError:
                pass  # A concurrent launch/prune already archived it.
            except Exception as exc:
                supervisor_error(o, "last_supervisor_cleanup_error", exc)


def supervise_child(o):
    # This command is launched ONLY as the actual retained visible Rex terminal program.
    os.environ['AGENT_REGISTRY'] = o.registry
    state = load(o.registry, o.launch_id)
    sid, bid = os.environ.get("REX_SESSION"), os.environ.get("REX_BLOCK")
    address_id(sid, "session")
    address_id(bid, "block")
    require(sid == state["target"]["session_id"], "supervisor_session_mismatch")
    end = time.monotonic() + 60  # Includes jobs lock wait, live validation and fleet reporting.
    while (not state["tracked"] or not state["protocol_file"]) and time.monotonic() < end:
        time.sleep(.05)
        state = load(o.registry, o.launch_id)
        if state["phase"] in ("tracking_uncertain", "launch_failed"):
            break
    require(state["phase"] != "launch_failed", state.get("failure_reason", "launch_failed"))
    require(state["tracked"] and state["protocol_file"] and state["target"]["block_id"] == bid,
            "supervisor_requires_verified_tracked_pane_and_protocol")
    os.environ.update(AGENT_SESSION=sid, AGENT_PANE=bid)
    def claim(s):
        require(not s.get("supervisor_claimed"), "supervisor_already_claimed")
        require(s["immediate_child_term"] is None, "child_already_exited")
        s["supervisor_claimed"] = True
        s["supervisor_pid"] = os.getpid()
        s.update(turn_started_at=now(), scratch_reminded=False, contract_reminded=False)
    update(o.registry, o.launch_id, claim)
    env = dict(os.environ)
    for key in ("AGENT_CHANNEL", "LC_AGENT_CHANNEL", "TEEREX_OPERATOR", "LC_TEEREX_OPERATOR", "TEEREX_OPERATOR_ACTIVE", "LC_TEEREX_OPERATOR_ACTIVE"):
        env.pop(key, None)  # A new launch never inherits its parent's capability implicitly.
    metadata = dict(AGENT_SESSION=sid, AGENT_PANE=bid, REX_SESSION=sid, REX_BLOCK=bid, AGENT_NAME=state["name"],
                    AGENT_STARTER=(state["starter"]["session_id"] + " " + state["starter"]["block_id"]) if state["starter"] else "",
                    AGENT_REPORT_TO=(state["report_to"]["session_id"] + " " + state["report_to"]["block_id"]) if state["report_to"] else "",
                    AGENT_LAUNCH_ID=o.launch_id, AGENT_REGISTRY=o.registry, AGENT_SCRATCHPAD=state["scratchpad"])
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
        command = [RUNTIME, "agents", "stop", "--registry", o.registry, "--launch-id", o.launch_id, "--event-file", "-"]
        if broker is not None:
            channel_command = [RUNTIME, "agents", "channel", "--handle", broker.handle, "--operation", "stop", "--event-file", "-"]
            command = channel_command
        argv = adapter_argv(argv, state["harness"], command, o.registry, o.launch_id, broker=broker, tint_enabled=state.get("tint") is not False)
    protocol = message(read_file(state["protocol_file"], 32768, private=True))
    if state.get("execution") is None:
        if not state.get("human"):
            argv = argv + [protocol]
    else:
        execution = state["execution"]
        payload = dict(argv=argv, cwd=execution["cwd"], metadata=metadata, protocol=protocol, registry=o.registry,
                       launch_id=o.launch_id, token=state["token"], callbacks=state["callbacks"], hook_events=state["hook_events"], harness=state["harness"],
                       pane=state["target"], store=state["store"], tint_enabled=state.get("tint") is not False)
        encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
        require(len(encoded) <= 98304, "compute_payload_too_large")
        argv = [RUNTIME, "targets", "exec", "--config", execution["config"], "--host", execution["host"], "--tty",
                "--", "agents", "exec", "--payload", encoded]
    # No output pipe: agent, supervisor and real pointer/keyboard input share the visible terminal.
    program_status(state, "working", "visible agent process starting; readiness not assessed", starting=True)
    child = None
    term = None
    try:
        child = subprocess.Popen(argv, env=env, cwd=state["cwd"])
        o.child_started = True
        update(o.registry, o.launch_id, lambda s: s.update(immediate_child_started_at=now(), protocol_outcome="not_applicable_human" if state.get("human") else "argument_supplied"))
        def forward(sig, unused):
            # Revoke on cancellation even if the child ignores its forwarded signal.
            if broker is not None:
                broker.close()
            # Registry updates stay outside the signal handler: the interrupted code may hold its lock.
            # Only our still-unreaped immediate child. Not a process-tree stop guarantee.
            with contextlib.suppress(ProcessLookupError):
                child.send_signal(sig)
        signal.signal(signal.SIGTERM, forward)
        signal.signal(signal.SIGHUP, forward)
        signal.signal(signal.SIGINT, forward)
        last_cost_check = time.monotonic() - 60
        last_hook = None
        last_status = None
        last_input_ns = 0
        channel_closed_reported = False
        previous_steps = (None, [])
        while True:

            try:
                if child.poll() is not None:
                    break
                if broker is not None:
                    broker.service()
                else:
                    time.sleep(.05)
                if broker is not None and broker.closed and not channel_closed_reported:
                    update(o.registry, o.launch_id, lambda s: s.update(channel_status="revoked"))
                    channel_closed_reported = True
                try:
                    incoming = agent_input_read(state["socket"], sid, bid)
                except (ValueError, OSError) as exc:
                    supervisor_error(o, "last_input_read_error", exc)
                    incoming = None
                if incoming is not None and incoming["at_ns"] > last_input_ns:
                    delivered_input(o.registry, o.launch_id, incoming)
                    last_input_ns = incoming["at_ns"]
                previous_steps = contract_steps(o.registry, o.launch_id, previous_steps)
                contract_starter(o.registry, o.launch_id)
                contract_lapse(o.registry, o.launch_id)
                live = load(o.registry, o.launch_id)
                if time.monotonic() - last_cost_check >= 60:
                    last_cost_check = time.monotonic()
                    try:
                        matches, unused = cost_matches([live])
                        cost_flag(o.registry, live, cost_row(live, matches[live['launch_id']]))
                    except Exception as exc:
                        supervisor_error(o, "last_cost_error", exc)
                current = live.get("last_hook")
                try:
                    waiting = scratch_read(Path(state["scratchpad"])).get("waiting", "")
                except (OSError, ValueError) as exc:
                    supervisor_error(o, "last_supervisor_loop_error", exc)
                    waiting = ""
                status = ("blocked", waiting[:300]) if waiting and (current or {}).get("state") != "error" else (
                    (current.get("state") or {"Stop": "idle", "StopFailure": "error", "UserPromptSubmit": "working"}[current["kind"]], current["text"])
                    if current else ("working", "visible agent process starting; readiness not assessed"))
                if (live.get("contract") or {}).get("stalled"):
                    status = ("blocked", f"stalled: no contact {(now() - live['contract']['last_contact_at']) // 60000} min")
                if status != last_status:
                    program_status(state, *status)
                    last_status = status
                if current is not None and current != last_hook:
                    if current["kind"] in ("Stop", "StopFailure"):
                        come_forward(state, current["kind"])
                    last_hook = current
            except Exception as exc:
                supervisor_error(o, "last_supervisor_loop_error", exc)
                time.sleep(.05)

        code = child.returncode
        term = {"Exited": code} if code >= 0 else {"Signal": -code}
    except OSError as exc:
        if not getattr(o, "child_started", False):
            supervisor_launch_failed(o, str(exc))
        term = {"launch_error": str(exc)[:600]}
        code = 125
    finally:
        if broker is not None:
            broker.close()
            update(o.registry, o.launch_id, lambda s: s.update(channel_status="revoked"))
        if term is not None:
            def ended(s):
                s.update(immediate_child_term=term, immediate_child_ended_at=now())
                # Exit does not answer a pending report; only the starter can accept it.
            update(o.registry, o.launch_id, ended)
            try:
                cleanup = close_scratch_viewer(load(o.registry, o.launch_id))
                update(o.registry, o.launch_id, lambda s: s.update(scratch_cleanup=cleanup))
            except Exception as exc:
                supervisor_error(o, 'last_scratch_cleanup_error', exc)
        program_status(state, "done" if term == {"Exited": 0} else "error",
                       "immediate child terminated; descendants not verified" if term is not None else
                       "supervision failed; immediate child termination unknown")
    if pane_absent(state) is True:
        # Closing the pane must not wait for starter messaging or board presentation.
        return (code if code >= 0 else min(255, 128 - code)), None
    come_forward(state, "exit")
    state = load(o.registry, o.launch_id)
    last = state.get("last_hook", {}).get("text", "(no harness last words supplied)")
    role = "SSH transport" if state.get("execution") else "Immediate child"
    remote = (f"Remote child: {json.dumps(state['remote_child_term']) if state.get('remote_child_term') else 'unknown; no measured exit callback'}\n"
              if state.get("execution") else "")
    notice_code, result = notify(o.registry, o.launch_id, "child-exit",
                                f"PROCESS EXIT: {state['name']}\n{role}: {json.dumps(term)}\n" + remote +
                                f"Last harness report: {last}\nDescendants are not verified gone.", "waited_immediate_child")
    if notice_code:
        supervisor_error(o, "last_supervisor_notice_error", result)
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
        history_add(history, event_id,
                    dict(outcome="uncertain", owner=o.owner, reason=o.reason, anchor=o.anchor, focus=o.focus, at=now()),
                    32, "presentation_already_attempted")
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


def accept(o):
    """Accept report state under the same lock as reports, input and pruning."""
    import teerex_pane_guard
    with Registry(o.registry) as registry:
        candidates = []
        history = Path(registry.root) / "archive"
        if history.exists():
            with Registry(str(history)):
                pass
        if o.launch_id:
            launch_id = identifier(o.launch_id)
            live = Path(registry.root) / registry.name(launch_id)
            paths = [live] if live.exists() else [Path(registry.root) / "archive" / launch_id / "retired.json"]
            if not paths[0].exists():
                paths = [Path(registry.root) / "archive" / launch_id / registry.name(launch_id)]
        else:
            paths = list(Path(registry.root).glob("agents-*.json"))
            history = Path(registry.root) / "archive"
            if history.exists():
                require(not history.is_symlink(), "private_owned_archive_required")
                for directory in history.iterdir():
                    if re.fullmatch(r"[0-9a-f]{32}", directory.name):
                        path = directory / "retired.json"
                        paths.append(path if path.exists() else directory / registry.name(directory.name))
        for path in paths:
            # Registry validates ownership/modes and refuses symlink directories.
            with (contextlib.nullcontext(registry) if path.parent == Path(registry.root) else Registry(str(path.parent))) as records:
                launch_id = o.launch_id or (path.parent.name if path.name == "retired.json" else path.stem[7:])
                state = records.read(launch_id, path.name)
            if o.name is not None and state.get("name") != o.name:
                continue
            policy = teerex_pane_guard.snapshot("unix://" + state["socket"])
            actor = policy["actor"]
            same = lambda address: bool(address) and all(actor.get(k) and actor[k] == address.get(k) for k in ("session_id", "block_id"))
            responsible = same(state.get("starter")) or same(state.get("report_to"))
            allowed = responsible or policy["operator"] or any(same(seat) for seat in policy["seats"])
            if o.name is not None:
                # Names select only this caller's own agents, including archives.
                if not responsible:
                    continue
            else:
                require(allowed, "report_acceptance_requires_starter_report_to_seat_or_operator")
            candidates.append((path, state, actor, policy["operator"]))
        require(len(candidates) == 1, "agent_name_ambiguous" if candidates else "agent_not_found_for_caller")
        path, state, actor, operator = candidates[0]
        pending = (state.get("contract") or {}).get("awaiting_starter")
        require(pending and pending.get("kind") in ("done", "flag"), "no_pending_report")
        require(o.note is None or isinstance(o.note, str), "invalid_acceptance_note")
        acceptance = dict(accepted_by=dict(actor, operator=operator), accepted_at=now(), note=o.note, report=pending)
        state["starter_acceptance"] = acceptance
        state["contract"].update(awaiting_starter=None, starter_lapses=0)
        state["contract"].pop("starter_reminded_at", None)
        with (contextlib.nullcontext(registry) if path.parent == Path(registry.root) else Registry(str(path.parent))) as records:
            records.save(state, name=path.name)
        return 0, receipt(state, "report_accepted", acceptance=acceptance)


def since_timestamp(value):
    if value is None:
        return 0
    if value.isdecimal():
        return int(value)
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "since_requires_timezone")
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError):
        raise Refusal("since_requires_ISO_with_timezone_or_unix_ms")


def timeline(o):
    root = Path(absolute(o.registry))
    require(root.is_dir() and not root.is_symlink(), "invalid_registry_directory")
    since = since_timestamp(o.since)
    states = {}
    # No Registry lock: this is a read-only snapshot of atomically replaced files.
    for path in sorted(root.iterdir()):
        match = RECORD.fullmatch(path.name)
        if match:
            state = json.loads(read_file(str(path), limit=None, private=True))
            require(state.get("launch_id") == match.group(1), "invalid_lifecycle_record")
            states[state["launch_id"]] = state
    archive = root / "archive"
    if archive.is_dir() and not archive.is_symlink():
        for directory in sorted(archive.iterdir()):
            if not re.fullmatch(r"[0-9a-f]{32}", directory.name) or directory.is_symlink() or not directory.is_dir():
                continue
            path = directory / "retired.json"
            if not path.exists():
                path = directory / ("agents-" + directory.name + ".json")
            state = json.loads(read_file(str(path), limit=None, private=True))
            require(state.get("launch_id") == directory.name, "invalid_lifecycle_record")
            states[state["launch_id"]] = state
    rows = []
    legacy = []
    for launch_id, state in states.items():
        if o.name is not None and state.get("name") != o.name:
            continue
        if "timeline" not in state or state.get("timeline_partial"):
            legacy.append(launch_id)
        history = list(state.get("timeline", lifecycle_events(state)))
        # prune writes retired.json directly, preserving the last live state.
        for event in lifecycle_events(state):
            if event not in history:
                history.append(event)
        for event in history:
            if event["at"] >= since:
                rows.append(dict(event, name=state["name"], launch_id=launch_id, pane=state.get("target")))
    rows.sort(key=lambda e: (e["at"], e["launch_id"]))
    result = dict(schema_version=1, kind="agents_timeline", events=rows,
                  legacy_partial_launches=sorted(legacy), snapshot="read_only_not_live_liveness")
    if o.json:
        return 0, result
    for row in rows:
        at = datetime.datetime.fromtimestamp(row["at"] / 1000, datetime.timezone.utc).isoformat(timespec="milliseconds")
        pane = row.get("pane") or {}
        detail = row.get("text", "")
        if "term" in row:
            detail = json.dumps(row["term"], sort_keys=True)
        print("%s %s %s %s %s %s %s" % (at, row["name"], row["launch_id"], row["event"],
                                        pane.get("session_id", "unknown"), pane.get("block_id", "unknown"), detail))
    if legacy:
        print("Legacy history is partial for %d launch(es); overwritten hooks and missing timestamps cannot be recovered." % len(legacy), file=sys.stderr)
    return 0, None


def rebind_seat(o):
    old, new = [json.loads(value) for value in o.old_target], json.loads(o.new_target)
    for address in old + [new]:
        address_id(address["session_id"], "session")
        address_id(address["block_id"], "block")
    require(all(address.get("host") == new.get("host") and address.get("server") == new.get("server")
                for address in old), "seat_inheritance_same_server_required")
    require(isinstance(new.get("server"), str) and new["server"].startswith("unix:///"), "absolute_seat_server_required")
    transport = dict(socket=new["server"][7:], client_path=os.environ.get("PATH", os.defpath),
                     rex_executable=os.environ.get("TEEREX_INTERNAL_REX"))
    require(pane_presence(transport, new), "new_seat_not_live")
    require(all(not pane_presence(transport, address) for address in old), "previous_seat_still_live")
    rebound = []
    with Registry(o.registry) as registry:
        for path in Path(o.registry).glob("agents-*.json"):
            if not re.fullmatch(r"agents-[0-9a-f]{32}\.json", path.name):
                continue
            state = registry.read(path.stem[7:])
            fields = [field for field in ("starter", "report_to") if state.get(field) in old]
            if not fields:
                continue
            for field in fields:
                state[field] = new
                state.setdefault("destination_roles", {})[field] = "seat"
            c = state.get("contract")
            if c:
                if c.get("starter") in old:
                    c["starter"] = new
                c.update(stalled=False, lapses=0, starter_lapses=0, last_contact_at=now())
                c.pop("last_lapse_at", None)
                c.pop("absent_starter", None)
                c.pop("starter_reminded_at", None)
            state.setdefault("seat_inheritance", []).append(dict(at=now(), previous=old, target=new, fields=fields))
            registry.save(state)
            rebound.append(state["launch_id"])
    return 0, dict(schema_version=1, kind="agents_result", outcome="rebound", launches=rebound)


def profiles(o):
    cfg = config(o.config)
    return 0, dict(schema_version=1, kind="agent_profiles", profiles=cfg["profiles"], defaults=cfg.get("defaults", {}),
                   security_settings_changed=False, config_source=o.config)


def shell(o):
    cfg = config(o.config)
    print("# Opt-in human launch functions replace existing names; inspect before sourcing. No shell files are edited.")
    for name in cfg["profiles"]:
        require(re.fullmatch(r"[a-z][a-z0-9_-]*", name), "profile_not_shell_identifier")
        print(f"{name}() {{ {shlex.join([RUNTIME, 'agents', 'human', '--config', o.config, '--profile', name])} \"$@\"; }}")
    return 0, None


def bounded_int(minimum, maximum):
    def parse(value):
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"expected integer in {minimum}..{maximum}") from None
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"expected integer in {minimum}..{maximum}")
        return number
    return parse


def parser():
    p = ActionParser(prog="teerex agents", description=(
        "Tracked tab/detached profiles, protocol ACK-before-one-brief, optional named SSH compute and opt-in bounded local fence channel. "
        "Python3.9+. API13 jobs. Profiles accept tint: false or {idle,error,done: #RRGGBB}; supervisor uses child status. "
        "Creation, transport ACK, agent ACK, idle and child exit are distinct. "
        "Profiles accept layout: tab|detached and opt-in come_forward: true (place on Stop/StopFailure/exit without focus). "
        "No readiness claim, input lease, untracked agent, daemon, automatic retry/close or whole-tree death guarantee."))
    sub = p.add_subparsers(dest="operation", required=True)
    q = sub.add_parser("rebind_seat", help="registry-locked inheritance after boards verifies the previous seat absent")
    q.add_argument("--registry", required=True)
    q.add_argument("--old-target", action="append", required=True)
    q.add_argument("--new-target", required=True)
    for op in ("profiles", "shell"):
        q = sub.add_parser(op, help="inspect profiles" if op == "profiles" else "print replacement human-launch functions; no starter/brief needed; never edits shell files")
        q.add_argument("--config", required=True)
    sub.add_parser("fence-probe", help="one-shot inside-fence checks; --protect-file ABS [--evidence-fd N] [--then -- ARGV...]; outside: --record-identities --out ABS")
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
    q = sub.add_parser("hook", help="scratch enforcement; progress Stop reports stay in timeline; finished/waiting/failure reports deliver")
    q.add_argument("--harness", required=True, choices=("claude", "codex", "pi"))
    q.add_argument("--command-json", required=True, help="literal callback argv JSON")
    source = q.add_mutually_exclusive_group(required=True)
    source.add_argument("--payload", help="Codex notify appends one JSON argv payload")
    source.add_argument("--event-file", help="normalized bounded Stop JSON file or stdin")
    q = sub.add_parser("launch", help="create tracked tab/detached agent and scratchpad; profiles: intent, scratch_pane (default true); await ACK before brief")
    q.add_argument("--config", required=True)
    q.add_argument("--profile", required=True)
    q.add_argument("--layout", choices=("tab", "detached"), help="override profile layout; detached stays tracked without a window")
    for key in ("registry", "socket", "session", "name", "cwd", "starter-session", "starter-block", "report-to-session",
                "report-to-block", "host", "owner", "purpose", "store", "brief-file"):
        q.add_argument("--" + key)
    q.add_argument("--review-at", type=int, help="absolute future Unix milliseconds, <=30 days; default config review_after_ms")
    q.add_argument("--launch-wait-ms", type=bounded_int(0, 60000), default=60000, metavar="0..60000",
                   help="legacy compatibility option; launches no longer use a global creation queue")
    q.add_argument("--ack-timeout-ms", type=bounded_int(100, 60000), default=10000, metavar="100..60000")
    q.add_argument("--done-when")
    q.add_argument("--contract-interval-s", type=bounded_int(1, 2147483647))
    human_parser = sub.add_parser("human", parents=[q], add_help=False,
                                  help="human interactive launch: visible tracked pane, standing flags, no starter/brief/ACK")
    human_parser.set_defaults(operation="human")
    human_parser.add_argument("--routed", action="store_true", help=argparse.SUPPRESS)
    q = sub.add_parser("cost", help="local live/recent managed agent transcript tokens, dollars and wall/turn time; unknown costs stay unknown")
    q.add_argument("--registry", default=str(Path.home() / ".local/state/teerex-agents"))
    q.add_argument("--rivet-item", action="append", help="explicit Rivet item: read rv show displayed dollars; repeatable")
    q.add_argument("--since", help="launches since inclusive ISO timestamp with timezone or Unix milliseconds")
    q.add_argument("--json", action="store_true")
    q = sub.add_parser("timeline", help="read timestamped launch/ACK/brief/Stop/StopFailure/exit/prune events, including archives; oldest first")
    q.add_argument("--registry", required=True)
    q.add_argument("--name", help="exact agent name")
    q.add_argument("--since", help="inclusive ISO timestamp with timezone or Unix milliseconds")
    q.add_argument("--json", action="store_true", help="structured events and legacy-history limitations")
    q = sub.add_parser("accept", help="accept a pending DONE/FLAG from a live or archived worker; never sends input")
    q.add_argument("--registry", default=str(Path.home() / ".local/state/teerex-agents"))
    selection = q.add_mutually_exclusive_group(required=True)
    selection.add_argument("--launch-id")
    selection.add_argument("--name", help="unambiguous exact name among caller's own agents")
    q.add_argument("--note", help="optional acceptance note retained in timeline")
    q = sub.add_parser("prune", help="archive records whose agent exited, never started, or whose pane is gone; plan unless --apply")
    q.add_argument("--registry", required=True)
    q.add_argument("--apply", action="store_true", help="move retired records to REGISTRY/archive/<launch_id>/ (never deleted)")
    q.add_argument("--launch-wait-ms", type=bounded_int(0, 60000), default=60000, metavar="0..60000")
    for op in ("ack", "deliver", "inspect", "present", "stop", "supervise", "exited"):
        q = sub.add_parser(op, help={"ack": "record agent protocol ACK; token plus exact pane required",
                                    "deliver": "explicitly attempt a not-yet-attempted brief after ACK",
                                    "inspect": "lifecycle metadata and freshly read placement; unavailable placement is unknown",
                                    "present": "explicit relocation beside anchor through jobs owner/generation checks",
                                    "stop": "record idle/done/error turn state and conditional report, never death proof",
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


def refusal_next(o, reason=""):
    if reason.startswith("[Errno 2]"):
        return "Ask your starter for the current launch name and registry path; do not create replacement files."
    if reason == "absolute_path_required":
        return "Use an absolute path starting with / for the selected file or directory, then repeat the command."
    if reason == "launch_queue_busy":
        return "Wait for the current launch to finish, then repeat the launch command."
    if o.operation == "ack":
        return "Ask your starter for the current acknowledgment command; do not reuse an old token."
    registry = getattr(o, "registry", None)
    launch_id = getattr(o, "launch_id", None)
    if registry and launch_id:
        return shlex.join(["teerex", "agents", "inspect", "--registry", str(registry), "--launch-id", launch_id])
    if registry:
        return shlex.join(["teerex", "agents", "prune", "--registry", str(registry)])
    return "teerex agents " + o.operation + " --help"


def main():
    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGTERM, terminate)
    o = parser().parse_args(sys.argv[2:])
    try:
        if o.operation == "deliver":
            code, result = deliver(o.registry, o.launch_id)
        elif o.operation == "inspect":
            state = load(o.registry, o.launch_id)
            try:
                state['placement'] = detached_operation(state, 'inspect')['placement']
            except (OSError, ValueError, Refusal, subprocess.TimeoutExpired):
                state['placement'] = 'unknown'
            code, result = 0, receipt(state, "metadata_with_fresh_placement")
        elif o.operation == "exec":
            code, result = remote_exec(o)
        elif o.operation == "human":
            require(o.brief_file is None and o.starter_session is None and o.starter_block is None, "human_launch_has_no_brief_or_starter")
            code, result = launch(o)
        else:
            code, result = globals()[o.operation](o)
        if result is not None and o.operation != "supervise":
            print(json.dumps(result, ensure_ascii=False))
        if code:
            if (sys.stdin.isatty() and sys.stderr.isatty()): print("next: " + refusal_next(o), file=sys.stderr)
        return code
    except (KeyboardInterrupt, Cancelled) as exc:
        sig = exc.args[0] if isinstance(exc, Cancelled) else signal.SIGINT
        if o.operation == "supervise":
            supervisor_error(o, "last_supervisor_error", exc)
        else:
            print(json.dumps(dict(schema_version=1, kind="agents_result", outcome="cancelled_uncertain", retry_safe=False)))
        if (sys.stdin.isatty() and sys.stderr.isatty()): print("next: " + refusal_next(o), file=sys.stderr)
        return 128 + sig
    except (Refusal, OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as exc:
        result = dict(schema_version=1, kind="agents_result", outcome="refused_or_uncertain",
                      failure_reason=str(exc), retry_safe=False, agent_readiness="not_assessed", all_processes_verified_gone=False)
        if o.operation == "supervise":
            supervisor_error(o, "last_supervisor_error", exc)
        else:
            print(json.dumps(result))
        if (sys.stdin.isatty() and sys.stderr.isatty()): print("next: " + refusal_next(o, str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
