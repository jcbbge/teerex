"""Visible agent lifecycle. Python 3.9+ stdlib; embedded by the native CLI.

Only the in-pane supervisor waits for an agent. No daemon, screen-based ACK,
implicit endpoint, hidden fallback, creation retry or notification retry exists.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import time

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
        data = f.read(limit + 1)
    require(len(data) <= limit, "file_too_large")
    return data


class Registry:
    """Stable advisory lock and per-launch durable intent, on a trusted local filesystem."""
    def __init__(self, root):
        self.root = absolute(root)

    def __enter__(self):
        import fcntl
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            s = os.fstat(self.fd)
            require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == 0o700, "private_owned_registry_required")
            self.lock = os.open("agents.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                0o600, dir_fd=self.fd)
            s = os.fstat(self.lock)
            require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and
                    stat.S_IMODE(s.st_mode) == 0o600 and s.st_nlink == 1, "private_owned_lock_required")
            end = time.monotonic() + 2
            while True:
                try:
                    fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic() < end, "registry_busy_after_2s_lock_wait")
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

    def read(self, launch_id):
        data = read_file(str(Path(self.root) / self.name(launch_id)), private=True)
        state = json.loads(data)
        require(state["schema_version"] == 1 and state["launch_id"] == launch_id, "invalid_lifecycle_record")
        return state

    def save(self, state, new=False):
        name = self.name(state["launch_id"])
        if new:
            require(len([n for n in os.listdir(self.fd) if re.fullmatch(r"agents-[0-9a-f]{32}\.json", n)]) < 32,
                    "registry_full")
            require(not os.path.lexists(str(Path(self.root) / name)), "launch_already_exists")
        raw = json.dumps(state, ensure_ascii=False, sort_keys=True).encode()
        require(len(raw) <= LIMIT, "record_too_large")
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

    def write_message(self, launch_id, suffix, value):
        name = "agents-" + identifier(launch_id) + "-" + suffix + ".txt"
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


def receipt(state, outcome, **extra):
    # Tokens, full argv, briefs and reports stay private; state files are the recovery interface.
    result = {k: state.get(k) for k in ("launch_id", "name", "owner", "purpose", "review_at", "profile", "target",
                                        "starter", "report_to", "phase", "tracked", "protocol_acknowledged",
                                        "brief_attempted", "brief_outcome", "immediate_child_term", "notifications")}
    result.update(schema_version=1, kind="agents_result", outcome=outcome, agent_readiness="not_assessed",
                  task_completion="not_assessed", all_processes_verified_gone=False, exclusive_input_lease=False,
                  retry_safe=False, **extra)
    return result


def invoke(arguments, timeout=10, client_path=None, rex_executable=None):
    """Bounded foreground client, never the agent. Retain diagnostics without treating exit as ACK."""
    import tempfile
    # Output sinks are private regular files, not pipes that a failed descendant can hold open.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        environment = dict(os.environ)
        if client_path is not None:
            environment["PATH"] = client_path
        if rex_executable is not None:
            environment["TEEREX_INTERNAL_REX"] = absolute(rex_executable)
        p = subprocess.Popen([RUNTIME, *arguments], stdin=subprocess.DEVNULL, stdout=out, stderr=err,
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


def send(root, state, destination, body, label):
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


def config(path):
    value = json.loads(read_file(path))
    require(value.get("schema_version") == 1 and isinstance(value.get("profiles"), dict), "invalid_profiles_config")
    require(isinstance(value.get("defaults", {}), dict), "invalid_profile_defaults")
    return value


def launch(o):
    cfg = config(o.config)
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
        require(profile.get("harness", o.profile) == "claude" and "--settings" not in argv, "unsupported_or_conflicting_hook_adapter")
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
    session, ss, sb = address_id(o.session, "session"), address_id(o.starter_session, "session"), address_id(o.starter_block, "block")
    rs = address_id(o.report_to_session or ss, "session")
    rb = address_id(o.report_to_block or sb, "block")
    name, owner, purpose = text(o.name or o.profile), text(o.owner), text(o.purpose, 256)
    host = text(o.host)
    cwd = absolute(o.cwd)
    review = o.review_at or now() + cfg.get("defaults", {}).get("review_after_ms", 3600000)
    require(type(review) is int and now() < review <= now() + 30 * 86400000, "invalid_review_at")
    brief = message(read_file(o.brief_file, 32768)) if o.brief_file else None
    launch_id, token = secrets.token_hex(16), secrets.token_hex(32)
    target = dict(host=host, server="unix://" + socket, session_id=session, block_id=None)
    starter = dict(host=host, server="unix://" + socket, session_id=ss, block_id=sb)
    report_to = dict(host=host, server="unix://" + socket, session_id=rs, block_id=rb)
    state = dict(schema_version=1, launch_id=launch_id, token=token, name=name, owner=owner, purpose=purpose,
                 review_at=review, target=target, starter=starter, report_to=report_to, profile=o.profile, argv=argv,
                 cwd=cwd, harness=text(profile.get("harness", o.profile)), resume_session_id=profile.get("resume_session_id"),
                 store=o.store, created_at=now(), socket=socket, registry=root, phase="creation_uncertain", tracked=False,
                 protocol_acknowledged=False, protocol_outcome=None, brief_attempted=False, brief_outcome=None,
                 immediate_child_term=None, notifications={}, brief_file=None, protocol_file=None,
                 hook_events=profile.get("hook_events", False), client_path=os.environ.get("PATH", os.defpath),
                 rex_executable=os.environ.get("TEEREX_INTERNAL_REX"))
    with Registry(root) as registry:
        if brief is not None:
            state["brief_file"] = registry.write_message(launch_id, "brief", brief)
        registry.save(state, new=True)
    command = [RUNTIME, "agents", "supervise", "--registry", root, "--launch-id", launch_id]
    code, packet = invoke(["spawn", "--socket", socket, "--session", session, "--name", name, "--cwd", cwd,
                           "--report-to-session", rs, "--report-to-block", rb, "--", *command])
    def created(s):
        s["spawn_receipt"] = packet
        if isinstance(packet, dict) and packet.get("created"):
            s["target"]["block_id"] = address_id(packet["created"]["block_id"], "block")
    state = update(root, launch_id, created)
    if not succeeded(code, packet, "created_and_attached"):
        return 1, receipt(state, "creation_uncertain", client_exit=code)
    block = state["target"]["block_id"]
    code, packet = invoke(["jobs", "track", "--registry", root, "--socket", socket, "--session", session, "--block", block,
                           "--owner", owner, "--kind", "agent", "--purpose", purpose,
                           "--deadline-unix-ms", str(review), "--cleanup", "manual"])
    def tracked(s):
        s["track_receipt"] = packet
        s["tracked"] = succeeded(code, packet, "verified")
        s["phase"] = "protocol_pending" if s["tracked"] else "tracking_uncertain"
    state = update(root, launch_id, tracked)
    if not state["tracked"]:
        return 1, receipt(state, "tracking_uncertain", client_exit=code)
    if publish_fleet(root, state, "launch", "unknown", "Visible agent registered; protocol not acknowledged; readiness not assessed"):
        return 1, receipt(load(root, launch_id), "fleet_report_uncertain")
    # The first harness prompt is an explicit profile-supported argv argument. Sending terminal input
    # immediately after creation would race shell/harness startup and silently lose the protocol.
    protocol = ("Messaging protocol (not a task brief):\n"
                f"Your name is {name}; your pane is {session} {block}.\n"
                f"Your starter is {ss} {sb}; report-to is {rs} {rb}.\n"
                "Report stops, results, blockers and questions directly to report-to using teerex send; "
                "never type into a registered human seat. A finished turn is idle, not process death.\n"
                "Do not begin a task or launch another agent before the brief. Acknowledge this protocol now by running:\n" +
                shlex.join([RUNTIME, "agents", "ack", "--registry", root, "--launch-id", launch_id,
                            "--token", token, "--session", session, "--block", block]) +
                "\nThis ACK records protocol acknowledgment only, not readiness, authorization or exclusive input control.")
    with Registry(root) as registry:
        state = registry.read(launch_id)
        state["protocol_file"] = registry.write_message(launch_id, "protocol", protocol)
        state["phase"] = "awaiting_protocol_ack"
        registry.save(state)
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
    if state["store"] is None:
        return 0
    def intent(s):
        history = s.setdefault("fleet_reports", {})
        require(event_id not in history, "fleet_report_already_attempted")
        require(len(history) < 65, "fleet_report_history_full")
        history[event_id] = dict(outcome="uncertain", attempted_at=now())
    update(root, state["launch_id"], intent)
    code, packet = invoke(["fleet", "report", "--store", state["store"], "--host", state["target"]["host"],
                           "--socket", state["socket"], "--session", state["target"]["session_id"],
                           "--block", state["target"]["block_id"], "--owner", state["owner"], "--purpose", state["purpose"],
                           "--state", reported_state, "--detail", detail[:512]], client_path=state["client_path"],
                          rex_executable=state["rex_executable"])
    update(root, state["launch_id"], lambda s: s["fleet_reports"][event_id].update(
        outcome="reported" if code == 0 else "uncertain", client_exit=code, receipt=packet))
    return code


def notify(root, launch_id, event_id, body, evidence, reported_state="unknown"):
    with Registry(root) as registry:
        state = registry.read(launch_id)
        require(event_id not in state["notifications"], "notification_already_attempted")
        require(len(state["notifications"]) < 64, "notification_history_full")
        state["notifications"][event_id] = dict(outcome="uncertain", evidence=evidence, attempted_at=now())
        registry.save(state)
    # Starter and report-to can differ; notify both, deduplicating the exact tuple.
    destinations = [state["starter"]]
    if state["report_to"] != state["starter"]:
        destinations.append(state["report_to"])
    results = []
    for i, destination in enumerate(destinations):
        code, packet = send(root, state, destination, body, "notice-" + event_id + "-" + str(i))
        results.append(dict(target=destination, client_exit=code, receipt=packet,
                            outcome="transport_acknowledged" if transport_ack(code, packet) else "uncertain"))
    def reported(s):
        s["notifications"][event_id]["results"] = results
        s["notifications"][event_id]["outcome"] = ("transport_acknowledged" if all(r["outcome"] == "transport_acknowledged"
                                                                                   for r in results) else "uncertain")
    state = update(root, launch_id, reported)
    fleet_code = publish_fleet(root, state, event_id, reported_state, body.replace("\n", " "))
    ok = state["notifications"][event_id]["outcome"] == "transport_acknowledged" and fleet_code == 0
    return (0 if ok else 1), receipt(state, "notification_acknowledged" if ok else "notification_uncertain")


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
    raw = sys.stdin.buffer.read(32769) if o.event_file == "-" else read_file(o.event_file, 32768)
    require(len(raw) <= 32768, "hook_event_too_large")
    event = json.loads(raw)
    require(isinstance(event, dict), "invalid_hook_event")
    kind = event.get("hook_event_name")
    require(kind in ("Stop", "StopFailure"), "unsupported_hook_event")
    last = event.get("last_assistant_message", "") or ""
    require(isinstance(last, str), "invalid_last_words")
    if kind == "Stop" and not last:
        try:
            last = transcript_last_text(event.get("transcript_path"))
        except (OSError, Refusal, ValueError):
            last = "(last words unavailable: transcript could not be read)"
    error = str(event.get("error") or event.get("error_details") or event.get("message") or "unknown error")
    details = (last[:1500] or "(no last words supplied)") if kind == "Stop" else error[:600]
    state = load(o.registry, o.launch_id)
    # Hook metadata is a report by the configured harness, never measured process death.
    # Equal last words can occur on different turns; never deduplicate by message text.
    # A caller reconciling the same hook invocation can supply its stable event ID explicitly.
    event_id = identifier(o.event_id) if o.event_id else secrets.token_hex(16)
    title = "IDLE (harness turn-stop report)" if kind == "Stop" else "ERROR (harness failure report, death not verified)"
    body = f"{title}: {state['name']}\n{details}"
    def remembered(s):
        s["last_hook"] = dict(kind=kind, at=now(), text=details, evidence="harness_report_not_process_death")
    update(o.registry, o.launch_id, remembered)
    return notify(o.registry, o.launch_id, event_id, body, "harness_report_not_process_death",
                  reported_state="idle" if kind == "Stop" else "unknown")


def supervise(o):
    # This command is launched ONLY as the actual retained visible Rex terminal program.
    state = load(o.registry, o.launch_id)
    sid, bid = os.environ.get("REX_SESSION"), os.environ.get("REX_BLOCK")
    address_id(sid, "session")
    address_id(bid, "block")
    require(sid == state["target"]["session_id"], "supervisor_session_mismatch")
    end = time.monotonic() + 12
    while (not state["tracked"] or not state["protocol_file"]) and time.monotonic() < end:
        time.sleep(.05)
        state = load(o.registry, o.launch_id)
    require(state["tracked"] and state["protocol_file"] and state["target"]["block_id"] == bid,
            "supervisor_requires_verified_tracked_pane_and_protocol")
    def claim(s):
        require(not s.get("supervisor_claimed"), "supervisor_already_claimed")
        require(s["immediate_child_term"] is None, "child_already_exited")
        s["supervisor_claimed"] = True
    update(o.registry, o.launch_id, claim)
    env = dict(os.environ)
    metadata = dict(AGENT_SESSION=sid, AGENT_PANE=bid, REX_SESSION=sid, REX_BLOCK=bid, AGENT_NAME=state["name"],
                    AGENT_STARTER=state["starter"]["session_id"] + " " + state["starter"]["block_id"],
                    AGENT_REPORT_TO=state["report_to"]["session_id"] + " " + state["report_to"]["block_id"],
                    AGENT_LAUNCH_ID=o.launch_id, AGENT_REGISTRY=o.registry)
    env.update(metadata)
    env.update({"LC_" + k: v for k, v in metadata.items()})
    argv = state["argv"]
    if state.get("hook_events"):
        require(state["harness"] == "claude", "automatic_hook_adapter_not_supported_for_harness")
        hook = shlex.join([RUNTIME, "agents", "stop", "--registry", o.registry, "--launch-id", o.launch_id, "--event-file", "-"])
        require("--settings" not in argv, "profile_settings_conflict")
        settings = {"hooks": {k: [{"hooks": [{"type": "command", "command": hook, "timeout": 15}]}]
                              for k in ("Stop", "StopFailure")}}
        argv = argv + ["--settings", json.dumps(settings)]
    argv = argv + [message(read_file(state["protocol_file"], 32768, private=True))]
    # No output pipe: agent, supervisor and real pointer/keyboard input share the visible terminal.
    def osc(status, detail):
        sys.stdout.write("\x1b]7501;" + json.dumps(dict(state=status, title=state["name"], msg=detail)) + "\x07")
        sys.stdout.flush()
    osc("working", "visible agent process starting; readiness not assessed")
    child = None
    term = None
    try:
        child = subprocess.Popen(argv, env=env, cwd=state["cwd"])
        update(o.registry, o.launch_id, lambda s: s.update(immediate_child_started_at=now(), protocol_outcome="argument_supplied"))
        def forward(sig, unused):
            # Only our still-unreaped immediate child. Not a process-tree stop guarantee.
            with contextlib.suppress(ProcessLookupError):
                child.send_signal(sig)
        signal.signal(signal.SIGTERM, forward)
        signal.signal(signal.SIGINT, forward)
        code = child.wait()
        term = {"Exited": code} if code >= 0 else {"Signal": -code}
    except OSError as exc:
        term = {"launch_error": str(exc)[:600]}
        code = 125
    finally:
        if term is not None:
            update(o.registry, o.launch_id, lambda s: s.update(immediate_child_term=term, immediate_child_ended_at=now()))
    osc("done" if term == {"Exited": 0} else "error", "immediate child terminated; descendants not verified")
    state = load(o.registry, o.launch_id)
    last = state.get("last_hook", {}).get("text", "(no harness last words supplied)")
    notice_code, result = notify(o.registry, o.launch_id, "child-exit",
                                f"PROCESS EXIT: {state['name']}\nImmediate child: {json.dumps(term)}\n"
                                f"Last harness report: {last}\nDescendants are not verified gone.", "waited_immediate_child")
    if notice_code:
        print(json.dumps(result), file=sys.stderr)
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
        require(event_id not in history and len(history) < 32, "presentation_already_attempted_or_history_full")
        history[event_id] = dict(outcome="uncertain", owner=o.owner, reason=o.reason, anchor=o.anchor, focus=o.focus, at=now())
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


def profiles(o):
    cfg = config(o.config)
    return 0, dict(schema_version=1, kind="agent_profiles", profiles=cfg["profiles"], defaults=cfg.get("defaults", {}),
                   security_settings_changed=False, config_source=o.config)


def shell(o):
    cfg = config(o.config)
    print("# Opt-in shell functions; inspect before sourcing. No personal settings are edited.")
    for name in cfg["profiles"]:
        require(re.fullmatch(r"[a-z][a-z0-9_-]*", name), "profile_not_shell_identifier")
        print(f"if typeset -f {name} >/dev/null 2>&1; then")
        print(f"  printf '%s\\n' 'teerex: preserved existing {name} function; profile wrapper not installed' >&2")
        print("else")
        print(f"  {name}() {{ {shlex.join([RUNTIME, 'agents', 'launch', '--config', o.config, '--profile', name])} \"$@\"; }}")
        print("fi")
    return 0, None


def parser():
    p = argparse.ArgumentParser(prog="teerex agents", description=(
        "Visible launch profiles, durable jobs responsibility, token/address protocol ACK gating and explicit stop reports. "
        "Python3.9+. API13 jobs. Creation, transport ACK, agent ACK, idle and child exit are distinct. "
        "No readiness claim, input lease, hidden agent, daemon, automatic retry/close or whole-tree death guarantee."))
    sub = p.add_subparsers(dest="operation", required=True)
    for op in ("profiles", "shell"):
        q = sub.add_parser(op, help="inspect profiles" if op == "profiles" else "print opt-in shell functions; never edits shell files")
        q.add_argument("--config", required=True)
    q = sub.add_parser("launch", help="create visible pane, track jobs, send protocol, await agent ACK, attempt brief once")
    q.add_argument("--config", required=True)
    q.add_argument("--profile", required=True)
    for key in ("registry", "socket", "session", "name", "cwd", "starter-session", "starter-block", "report-to-session",
                "report-to-block", "host", "owner", "purpose", "store", "brief-file"):
        q.add_argument("--" + key)
    q.add_argument("--review-at", type=int, help="absolute future Unix milliseconds, <=30 days; default config review_after_ms")
    q.add_argument("--ack-timeout-ms", type=int, default=10000, choices=range(100, 60001), metavar="100..60000")
    for op in ("ack", "deliver", "inspect", "present", "stop", "supervise"):
        q = sub.add_parser(op, help={"ack": "record agent protocol ACK; token plus exact pane required",
                                    "deliver": "explicitly attempt a not-yet-attempted brief after ACK",
                                    "inspect": "offline lifecycle metadata; not live liveness",
                                    "present": "explicit relocation beside anchor through jobs owner/generation checks",
                                    "stop": "submit a harness Stop/StopFailure report, never death proof",
                                    "supervise": "internal retained visible in-pane program; waits immediate child"}[op])
        q.add_argument("--registry", required=True)
        q.add_argument("--launch-id", required=True)
        if op == "ack":
            for key in ("token", "session", "block"):
                q.add_argument("--" + key, required=True)
        if op == "stop":
            q.add_argument("--event-file", required=True, help="absolute JSON file or - for bounded stdin")
            q.add_argument("--event-id", help="optional stable 32-lowercase-hex hook invocation ID; duplicate attempts refuse")
        if op == "present":
            for key in ("owner", "reason", "anchor"):
                q.add_argument("--" + key, required=True)
            q.add_argument("--generation", required=True, type=int)
            q.add_argument("--focus", required=True, choices=("yes", "no"))
    return p


def main():
    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGTERM, terminate)
    o = parser().parse_args(sys.argv[2:])
    try:
        if o.operation == "deliver":
            code, result = deliver(o.registry, o.launch_id)
        elif o.operation == "inspect":
            code, result = 0, receipt(load(o.registry, o.launch_id), "saved_metadata_not_live_evidence")
        else:
            code, result = globals()[o.operation](o)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False))
        return code
    except (KeyboardInterrupt, Cancelled) as exc:
        sig = exc.args[0] if isinstance(exc, Cancelled) else signal.SIGINT
        print(json.dumps(dict(schema_version=1, kind="agents_result", outcome="cancelled_uncertain", retry_safe=False)))
        return 128 + sig
    except (Refusal, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps(dict(schema_version=1, kind="agents_result", outcome="refused_or_uncertain", failure_reason=str(exc),
                              retry_safe=False, agent_readiness="not_assessed", all_processes_verified_gone=False)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
