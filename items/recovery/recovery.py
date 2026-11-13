#!/usr/bin/env python3
"""Bounded public-Rex recovery. No screen scraping, updater, close or retry."""
import argparse
import contextlib
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

LIMIT = 1024 * 1024
MAX_PANES = 128
MAX_SESSIONS = 32
ADDRESS_KEYS = {"host", "server", "session_id", "block_id"}
LAUNCH_KEYS = {"launch_id", "name", "owner", "purpose", "review_at", "target", "starter", "report_to",
               "profile", "argv", "cwd", "harness", "resume_session_id", "store", "created_at", "phase",
               "tracked", "protocol_acknowledged", "protocol_outcome", "brief_attempted", "immediate_child_term", "seat", "inbox"}
OMISSIONS = {
    "draft": "unsupported_no_authoritative_input_buffer_API; never_inferred_from_rendered_text",
    "argv": "not_exposed_by_Rex; explicit_private_metadata_only",
    "resume_session_id": "not_exposed_by_Rex; explicit_metadata_is_unverified_harness_state",
    "credentials": "no_environment_or_credential_file_reads; explicit_argv_may_contain_secrets_and_stays_private",
    "agent_relaunch": "withheld_requires_new_protocol_gate; historical_ACK_is_not_new_ACK",
    "focus_zoom_minimized_state": "recorded_but_not_reapplied; restored_panes_remain_inspectable",
    "board_state": "not_copied; remap_receipt_requires_explicit_boards_remap",
    "application_internal_addresses": "argv_is_literal; embedded_pane_IDs_not_rewritten; relaunch_viewers_via_their_owning_command",
    "detached_blocks": "inventoried_but_not_recreated_as_hidden_programs",
}


class Refusal(Exception):
    pass


class Cancelled(Exception):
    def __init__(self, number):
        self.number = number


def cancelled(number, _frame):
    raise Cancelled(number)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise Refusal(message)


def full_id(value, prefix):
    try:
        return isinstance(value, str) and value.startswith(prefix + ":") and str(uuid.UUID(value[len(prefix) + 1:])) == value[len(prefix) + 1:]
    except ValueError:
        return False


def text(value, limit=4096):
    return isinstance(value, str) and 0 < len(value.encode("utf-8")) <= limit and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def address(value):
    require(isinstance(value, dict) and set(value) == ADDRESS_KEYS, "invalid_address_fields")
    require(text(value["host"], 128) and text(value["server"]) and value["server"].startswith("unix:///"), "invalid_address_host_server")
    require(full_id(value["session_id"], "session") and full_id(value["block_id"], "block"), "canonical_full_address_required")
    return value


def key(value):
    return value["server"], value["session_id"], value["block_id"]


def private_stat(fd, directory=False):
    s = os.fstat(fd)
    require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == (0o700 if directory else 0o600), "private_owned_0700_directory_or_0600_file_required")
    require(stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink == 1, "private_regular_nonlinked_file_required")


def read_fd(fd):
    private_stat(fd)
    chunks = []
    size = 0
    while True:
        chunk = os.read(fd, min(65536, LIMIT + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        require(size <= LIMIT, "private_file_exceeds_1MiB")
    try:
        return json.loads(b"".join(chunks))
    except (ValueError, UnicodeError):
        raise Refusal("invalid_private_JSON")


def read_private(path):
    require(os.path.isabs(path), "private_file_path_must_be_absolute")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        return read_fd(fd)
    finally:
        os.close(fd)


class Store:
    def __init__(self, path):
        require(os.path.isabs(path), "directory_must_be_absolute")
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            private_stat(self.fd, True)
        except BaseException:
            os.close(self.fd)
            raise
        self.path = path

    def close(self):
        os.close(self.fd)

    def read(self, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            return read_fd(fd)
        finally:
            os.close(fd)

    def create(self, name, value):
        data = encoded(value) + b"\n"
        require(len(data) <= LIMIT, "state_exceeds_1MiB")
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            private_stat(fd)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
            os.fsync(self.fd)
        finally:
            os.close(fd)

    def journal(self, record):
        # Created exclusively before mutation. Same file retained after any uncertainty.
        fd = os.open("restore.jsonl", os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            private_stat(fd)
            data = encoded(record) + b"\n"
            require(os.fstat(fd).st_size + len(data) <= LIMIT, "restore_journal_exceeds_1MiB")
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)


def run_process(argv, timeout, cap=LIMIT):
    """One attempt, bounded stdout/stderr and deadline; no stderr content in receipts."""
    env = dict(os.environ)
    for name in ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT"):
        env.pop(name, None)
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=env, start_new_session=True)
    output = bytearray()
    diagnostic_size = 0
    reaped = False
    end = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ, "out")
            selector.register(p.stderr, selectors.EVENT_READ, "err")
            while selector.get_map():
                remaining = end - time.monotonic()
                require(remaining > 0, "transport_deadline_result_may_be_unknown")
                for event, _ in selector.select(min(remaining, .1)):
                    data = os.read(event.fd, 8192)
                    if not data:
                        selector.unregister(event.fileobj)
                    elif event.data == "out":
                        output.extend(data)
                        require(len(output) <= cap, "transport_output_exceeds_bound_result_may_be_unknown")
                    else:
                        diagnostic_size += len(data)
                        require(diagnostic_size <= 65536, "transport_diagnostics_exceed_bound_result_may_be_unknown")
        try:
            code = p.wait(timeout=max(.001, end - time.monotonic()))
            reaped = True
        except subprocess.TimeoutExpired:
            raise Refusal("transport_deadline_result_may_be_unknown")
        require(code == 0, "transport_exit_%s_result_may_be_unknown" % code)
        try:
            return json.loads(output)
        except (ValueError, UnicodeError):
            raise Refusal("invalid_transport_JSON_result_may_be_unknown")
    finally:
        if not reaped:
            # The unreaped direct child reserves its process-group ID.
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
        p.stdout.close()
        p.stderr.close()


class Rex:
    def __init__(self, socket, timeout):
        require(os.path.isabs(socket) and text(socket), "absolute_explicit_socket_required")
        self.server = "unix://" + socket
        self.socket = socket
        self.timeout = timeout
        selected = os.environ.get("TEEREX_INTERNAL_REX") or shutil.which("rex")
        require(selected is not None, "Rex_executable_not_found; select_with_root_transport")
        self.executable = os.path.abspath(selected)
        require(not os.environ.get("TEEREX_INTERNAL_REX") or os.path.isabs(selected), "root_Rex_pin_must_be_absolute")
        self.base = [self.executable, "--autostart=false", "--server", self.server, "--timeout", "3s", "--color", "never"]

    def call(self, method, args=None):
        value = run_process(self.base + ["api", "call", method, encoded(args or {}).decode()], self.timeout)
        require(isinstance(value, dict), "invalid_Rex_response_object")
        return value

    def identity(self, allow_older=False):
        version = self.call("server.version")
        status = self.call("server.status")
        require(version.get("api_revision") in ((10, 11, 12, 13) if allow_older else (13,)), "recovery_requires_API13; update_inventory_only_accepts_API10_to_13")
        require(text(status.get("host_id"), 128) and text(status.get("instance_id"), 128), "server_identity_unavailable")
        return {"server": self.server, "rex_executable": self.executable, "version": version, "host_id": status["host_id"], "instance_id": status["instance_id"]}


def sanitize_launch(entry, server):
    require(isinstance(entry, dict) and entry.get("schema_version", 1) == 1, "invalid_launch_metadata")
    # Whitelist excludes protocol tokens, briefs, environment, hook credentials and arbitrary private fields.
    out = {k: copy.deepcopy(v) for k, v in entry.items() if k in LAUNCH_KEYS}
    address(out.get("target"))
    require(out["target"]["server"] == server, "metadata_target_server_mismatch")
    for field in ("starter", "report_to", "inbox"):
        if out.get(field) is not None:
            address(out[field])
    require(out.get("seat") in (None, True, False), "seat_must_be_explicit_boolean")
    argv = out.get("argv")
    require(argv is None or isinstance(argv, list) and 1 <= len(argv) <= 64 and all(isinstance(v, str) and "\0" not in v and len(v.encode()) <= 4096 for v in argv) and text(argv[0]), "invalid_explicit_argv")
    require(argv is None or len(encoded(argv)) <= 16384, "argv_exceeds_16KiB")
    cwd = out.get("cwd")
    require(cwd is None or text(cwd) and os.path.isabs(cwd), "metadata_cwd_must_be_absolute")
    for field in ("harness", "resume_session_id"):
        require(out.get(field) is None or text(out[field], 256), "invalid_harness_or_resume_id")
    for field in ("launch_id", "name", "owner", "purpose", "profile", "store", "phase", "protocol_outcome"):
        require(out.get(field) is None or text(out[field]), "invalid_launch_text_field")
    for field in ("tracked", "protocol_acknowledged", "brief_attempted"):
        require(out.get(field) is None or type(out[field]) is bool, "invalid_launch_boolean_field")
    for field in ("review_at", "created_at"):
        require(out.get(field) is None or type(out[field]) is int and out[field] > 0, "invalid_launch_timestamp")
    term = out.get("immediate_child_term")
    if term is not None:
        require(isinstance(term, dict), "invalid_declared_child_term")
        out["immediate_child_term"] = {k: v for k, v in term.items() if k in ("Exited", "Signal") and type(v) is int}
        if "launch_error" in term:
            out["immediate_child_term"]["launch_error"] = "declared_error_details_omitted"
    require(len(encoded(out)) <= 32768, "launch_metadata_exceeds_32KiB")
    return out


def load_metadata(args, server):
    entries = []
    if args.metadata:
        value = read_private(args.metadata)
        require(isinstance(value, dict) and value.get("schema_version") == 1 and isinstance(value.get("entries"), list), "metadata_requires_schema1_entries")
        entries.extend(value["entries"])
    if args.registry:
        with contextlib.closing(Store(args.registry)) as registry:
            lock = os.open("agents.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=registry.fd)
            try:
                private_stat(lock)
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                names = sorted(n for n in os.listdir(registry.fd) if n.startswith("agents-") and n.endswith(".json"))
                require(len(names) <= MAX_PANES, "agent_registry_exceeds_128_records")
                entries.extend(registry.read(name) for name in names)
            finally:
                os.close(lock)
    require(len(entries) <= MAX_PANES, "metadata_exceeds_128_records")
    result = {}
    for entry in entries:
        clean = sanitize_launch(entry, server)
        require(key(clean["target"]) not in result, "duplicate_launch_metadata_target")
        result[key(clean["target"])] = clean
    return result


def snapshot(rex, args):
    source = rex.identity()
    launches = load_metadata(args, rex.server)
    sessions = rex.call("session.list").get("sessions") or []
    require(isinstance(sessions, list) and len(sessions) <= MAX_SESSIONS, "snapshot_exceeds_32_sessions")
    result = {"schema_version": 1, "kind": "recovery_snapshot", "captured_at_unix_ms": int(time.time() * 1000),
              "source": source, "sessions": [], "boards": None, "omissions": dict(OMISSIONS), "metadata_provenance": "explicit_private_caller_records_not_harness_verified",
              "consistency": "per_session_layout_double_checked; process_and_cross_session_state_not_atomic"}
    if args.board_store:
        executable = os.environ.get("TEEREX_RECOVERY_EXECUTABLE")
        require(executable and os.path.isabs(executable), "board_capture_requires_integrated_teerex")
        with contextlib.closing(Store(args.board_store)):
            state = run_process([executable, "boards", "state", "inspect", "--store", args.board_store], rex.timeout)
        require(state.get("kind") == "boards_state" and state.get("state", {}).get("schema_version") == 1, "invalid_boards_state_receipt")
        state = state["state"]
        seats = [address(s["target"]) for s in state.get("seats", []) if s["target"]["server"] == rex.server]
        targets = {key(t): t for t in seats}
        require(len(targets) == len(seats), "conflicting_board_seat_alias_for_same_pane")
        for f in state.get("fleet", []):
            t = address(f["target"])
            if t["server"] == rex.server:
                require(key(t) not in targets or targets[key(t)] == t, "conflicting_board_host_alias_for_same_pane")
                targets[key(t)] = t
        require(len(targets) <= MAX_PANES, "boards_targets_exceed_128")
        # Only routing references, not inbox bodies/decision content, are copied.
        result["boards"] = {"store": args.board_store, "generation": state["generation"], "targets": list(targets.values()), "seats": seats,
                            "messages_copied": False, "provenance": "explicit_boards_state_inspect_report"}
    count = 0
    used = set()
    for s in sessions:
        sid = s["session_id"]
        require(full_id(sid, "session"), "invalid_session_id")
        view = rex.call("session.view", {"session_id": sid})
        blocks = rex.call("session.list_blocks", {"session_id": sid}).get("blocks") or []
        require(view.get("session_id") == sid, "session_view_identity_mismatch")
        count += len(blocks)
        require(count <= MAX_PANES, "snapshot_exceeds_128_panes")
        panes = []
        for b in blocks:
            require(full_id(b.get("block_id"), "block"), "invalid_block_id")
            pane = {"block": b, "process": None, "cwd": None, "process_status": "not_terminal", "launch": None,
                    "command_support": "unknown_no_argv_API", "draft_support": OMISSIONS["draft"]}
            if b.get("creator_name") == "com.superlogical.terminal":
                try:
                    proc = rex.call("com.superlogical.terminal.process", {"session_id": sid, "block_id": b["block_id"], "args": {}})
                    # Store only process identity/cwd, not arbitrary returned fields.
                    pane["process"] = {name: {k: v for k, v in (proc.get(name) or {}).items() if k in {"pid", "name", "path", "argv0", "script", "cwd"}} for name in ("child", "foreground")}
                    pane["cwd"] = (proc.get("foreground") or {}).get("cwd")
                    pane["process_status"] = "observed_not_agent_lifecycle"
                except Refusal as e:
                    pane["process_status"] = "unavailable:" + str(e)
            ident = (rex.server, sid, b["block_id"])
            if ident in launches:
                pane["launch"] = launches[ident]
                pane["command_support"] = "explicit_private_metadata"
                used.add(ident)
            launch = pane["launch"] or {}
            board_seat = any(t["session_id"] == sid and t["block_id"] == b["block_id"] for t in (result.get("boards") or {}).get("seats", []))
            pane["field_support"] = {"layout_labels_host": "public_API_observed", "cwd": "public_process_observed" if pane["cwd"] else "unknown",
                                     "argv": pane["command_support"], "harness": "explicit_metadata_unverified" if launch.get("harness") else "unknown",
                                     "resume_session_id": "explicit_metadata_unverified" if launch.get("resume_session_id") else "unknown",
                                     "report_to": "explicit_metadata" if launch.get("report_to") else "unknown",
                                     "seat": "explicit_boards_reference" if board_seat else "explicit_metadata" if launch.get("seat") is not None else "unknown",
                                     "inbox": "explicit_metadata" if launch.get("inbox") else "unknown", "draft": "unsupported_not_read"}
            panes.append(pane)
        # Detect layout/list races. Process/cwd observations remain per-call, not atomic.
        after = rex.call("session.view", {"session_id": sid})
        require(after == view, "layout_changed_during_snapshot_no_retry")
        result["sessions"].append({"view": view, "panes": panes})
    inventory = {(rex.server, s["view"]["session_id"], p["block"]["block_id"])
                 for s in result["sessions"] for p in s["panes"]}
    blocks = {k[2]: k for k in inventory}
    omitted = []
    for ident in sorted(set(launches) - used):
        require(ident[2] not in blocks, "metadata_pane_identity_contradiction")
        omitted.append({"reason": "launch_target_absent_at_snapshot", "target": launches[ident]["target"]})
    boards = result.get("boards")
    if boards:
        for target in boards["targets"]:
            if key(target) not in inventory:
                require(target["block_id"] not in blocks, "board_pane_identity_contradiction")
                omitted.append({"reason": "board_target_absent_at_snapshot", "target": target})
        boards["targets"] = [t for t in boards["targets"] if key(t) in inventory]
        boards["seats"] = [t for t in boards["seats"] if key(t) in inventory]
    result["omissions"]["absent_references"] = omitted
    declared_addresses(result)
    require((rex.call("session.list").get("sessions") or []) == sessions, "session_inventory_changed_no_retry")
    require(rex.identity() == source, "server_identity_changed_no_retry")
    require(len(encoded(result)) < LIMIT, "snapshot_exceeds_1MiB")
    with contextlib.closing(Store(args.directory)) as store:
        store.create("snapshot.json", result)
    return result


def load_snapshot(store):
    value = store.read("snapshot.json")
    require(isinstance(value, dict) and value.get("schema_version") == 1 and value.get("kind") == "recovery_snapshot", "unsupported_snapshot_schema")
    require(isinstance(value.get("sessions"), list) and len(value["sessions"]) <= MAX_SESSIONS, "invalid_snapshot_sessions")
    require(isinstance(value.get("source"), dict) and value["source"].get("version", {}).get("api_revision") == 13, "snapshot_requires_API13_source")
    total = 0
    session_ids = set()
    block_ids = set()
    for s in value["sessions"]:
        require(isinstance(s, dict) and isinstance(s.get("view"), dict) and isinstance(s.get("panes"), list), "invalid_snapshot_session")
        sid = s["view"].get("session_id")
        require(full_id(sid, "session") and sid not in session_ids, "invalid_or_duplicate_snapshot_session_id")
        session_ids.add(sid)
        for p in s["panes"]:
            bid = p.get("block", {}).get("block_id")
            require(full_id(bid, "block") and bid not in block_ids, "invalid_or_duplicate_snapshot_pane")
            block_ids.add(bid)
            if p.get("launch"):
                p["launch"] = sanitize_launch(p["launch"], value["source"]["server"])
                require(p["launch"]["target"]["session_id"] == sid and p["launch"]["target"]["block_id"] == bid, "snapshot_metadata_pane_mismatch")
            total += 1
    require(total <= MAX_PANES, "snapshot_exceeds_128_panes")
    boards = value.get("boards")
    if boards is not None:
        require(isinstance(boards, dict) and isinstance(boards.get("targets"), list) and isinstance(boards.get("seats"), list), "invalid_snapshot_boards_references")
        board_keys = set()
        for t in boards["targets"]:
            address(t)
            require(t["server"] == value["source"]["server"] and key(t) not in board_keys, "invalid_or_ambiguous_board_reference")
            board_keys.add(key(t))
        require(all(t in boards["targets"] for t in boards["seats"]), "seat_reference_not_in_board_targets")
    return value


def valid_rect(rect):
    return (isinstance(rect, list) and len(rect) == 4 and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in rect)
            and rect[2] > 0 and rect[3] > 0 and rect[0] + rect[2] <= 1.000001 and rect[1] + rect[3] <= 1.000001)


def leaves(node, depth=0):
    require(isinstance(node, dict) and depth <= 16 and valid_rect(node.get("rect")), "invalid_or_deep_layout")
    if node.get("block_id"):
        require(not node.get("split"), "ambiguous_layout_node")
        return [node["block_id"]]
    split = node.get("split")
    require(isinstance(split, dict) and split.get("direction") in ("horizontal", "vertical") and isinstance(split.get("ratio"), (int, float)) and 0 < split["ratio"] < 1, "invalid_layout_split")
    return leaves(split.get("before"), depth + 1) + leaves(split.get("after"), depth + 1)


def declared_addresses(saved):
    result = {}
    refs = list((saved.get("boards") or {}).get("targets", []))
    for s in saved["sessions"]:
        for p in s["panes"]:
            launch = p.get("launch") or {}
            refs.extend(launch[field] for field in ("target", "starter", "report_to", "inbox") if launch.get(field))
    for t in refs:
        address(t)
        require(key(t) not in result or result[key(t)] == t, "conflicting_declared_host_for_same_Rex_pane")
        result[key(t)] = t
    return result


def restore_plan(rex, saved, accept):
    declared_addresses(saved)
    current = rex.identity()
    require(current["host_id"] == saved["source"]["host_id"], "restore_host_mismatch_no_cross_host_execution")
    target_sessions = rex.call("session.list").get("sessions") or []
    issues = list(saved["omissions"].get("absent_references", []))
    hard = []
    pane_count = 0
    placed_keys = set()
    for session in saved["sessions"]:
        panes = {p["block"]["block_id"]: p for p in session["panes"]}
        placed = []
        for w in session["view"].get("windows") or []:
            layers = w.get("layers") or []
            if not layers or layers[0].get("kind") != "tiled":
                hard.append("missing_tiled_layer")
            for i, layer in enumerate(layers):
                require(valid_rect(layer.get("bounds")), "invalid_layer_bounds")
                if i and layer.get("kind") != "floating":
                    hard.append("unknown_layer_kind")
                ids = leaves(layer.get("layout"))
                require(ids == [b["block_id"] for b in layer.get("blocks") or []], "layout_block_order_mismatch")
                if i and len(ids) > 1:
                    hard.append("floating_split_restore_not_supported_by_surfaces")
                placed.extend(ids)
                for bid in ids:
                    require(bid in panes, "layout_pane_absent_from_inventory")
        require(len(placed) == len(set(placed)), "pane_placed_more_than_once")
        placed_keys.update((saved["source"]["server"], session["view"]["session_id"], bid) for bid in placed)
        for bid, pane in panes.items():
            b = pane["block"]
            pane_count += 1
            reason = None
            if bid not in placed:
                issues.append({"block_id": bid, "reason": "detached_not_recreated"})
                continue
            if b.get("host_id") != current["host_id"]:
                hard.append("attached_remote_host_not_recreatable:" + bid)
            elif b.get("creator_name") != "com.superlogical.terminal" or b.get("flavor") != "com.superlogical.terminal.shell":
                hard.append("unsupported_block_flavor:" + bid)
            launch = pane.get("launch") or {}
            if launch.get("harness") or launch.get("resume_session_id"):
                reason = "agent_resume_withheld_requires_new_protocol_gate"
            elif not launch.get("argv") or not launch.get("cwd"):
                reason = "command_or_cwd_unknown_holding_shell_only"
            for field in ("starter", "report_to", "inbox"):
                target = launch.get(field)
                if target:
                    matches = [q for t in saved["sessions"] for q in t["panes"] if key(target) == (saved["source"]["server"], t["view"]["session_id"], q["block"]["block_id"]) and q["block"].get("placement") == "placed"]
                    if not matches:
                        hard.append("unmapped_" + field + ":" + bid)
            if reason:
                issues.append({"block_id": bid, "reason": reason})
    for target in (saved.get("boards") or {}).get("targets", []):
        if key(target) not in placed_keys:
            inventory = {(saved["source"]["server"], s["view"]["session_id"], p["block"]["block_id"])
                         for s in saved["sessions"] for p in s["panes"]}
            require(not any(k[2] == target["block_id"] and k != key(target) for k in inventory), "board_pane_identity_contradiction")
            if key(target) in inventory:
                hard.append("unmapped_board_reference:" + target["block_id"])
            else:
                issues.append({"reason": "board_target_absent_at_snapshot", "target": target})
    context = {"snapshot_sha256": digest(saved), "target": current, "existing_sessions": target_sessions, "accept_omissions": accept}
    return {"schema_version": 1, "kind": "restore_plan", "confirmation": digest(context), "context": context,
            "panes_in_snapshot": pane_count, "omissions": issues, "hard_blockers": hard,
            "can_apply": not target_sessions and not hard and (not issues or accept),
            "existing_server_must_be_empty": True, "old_panes_closed": False, "commands_started_by_preview": False,
            "agent_readiness": "not_assessed", "board_state": OMISSIONS["board_state"], "retry_safe": False}


# Only a newly created recovery-owned terminal receives these routing lines. They
# are read as data, never shell code; argv is positional and never interpolated.
SHIM = '''stty -echo 2>/dev/null || exit 125
IFS= read -r AGENT_REPORT_TO || exit 125
IFS= read -r TEEREX_INBOX || exit 125
IFS= read -r AGENT_STARTER || exit 125
export AGENT_REPORT_TO TEEREX_INBOX AGENT_STARTER
export LC_AGENT_REPORT_TO="$AGENT_REPORT_TO" LC_AGENT_STARTER="$AGENT_STARTER"
export AGENT_SESSION="$REX_SESSION" AGENT_PANE="$REX_BLOCK"
export LC_REX_SESSION="$REX_SESSION" LC_REX_BLOCK="$REX_BLOCK"
export AGENT_NAME="$1" LC_AGENT_NAME="$1"
shift
cd -- "$1" || exit 125
shift
stty echo 2>/dev/null || exit 125
exec "$@"
'''
HOLD = ["/bin/sh", "-c", "printf '%s\\n' 'teerex: original command/agent resume withheld; inspect recovery omissions before relaunch.'; exec /bin/sh"]


def restore_apply(rex, saved, plan, store, args):
    require(plan["can_apply"], "restore_preflight_blocked")
    require(args.confirm == plan["confirmation"], "exact_preview_confirmation_required; repeat_preview_after_drift")
    executable = os.environ.get("TEEREX_RECOVERY_EXECUTABLE")
    require(executable and os.path.isabs(executable), "recovery_requires_integrated_teerex_surfaces_executable")
    # Exclusive durable marker is also the no-retry interlock, including crashes.
    store.create("restore.jsonl", {"event": "begin", "plan": plan})
    mappings = []
    map_by_old = {}
    session_map = {}
    created_panes = []
    declared = declared_addresses(saved)
    omissions = {o["block_id"] for o in plan["omissions"]}

    def opened(sid, old_sid, pane, layout, anchor=None, direction=None, ratio=None, bounds=None):
        b = pane["block"]
        launch = pane.get("launch") or {}
        holding = b["block_id"] in omissions
        command = HOLD if holding else launch["argv"]
        cwd = launch.get("cwd") if not holding else "/"
        label = b.get("label") or "recovered"
        argv = [executable, "surfaces", "open", "--socket", rex.socket, "--session", sid,
                "--layout", layout, "--label", label, "--cwd", cwd]
        if anchor:
            argv += ["--anchor", anchor]
        if direction:
            argv += ["--direction", direction, "--ratio", str(ratio)]
        if bounds:
            argv += ["--bounds", json.dumps(bounds)]
        argv += ["--", "/bin/sh", "-c", SHIM, "teerex-restore", launch.get("name") or label, cwd] + command
        store.journal({"event": "surface_attempt", "old_session_id": old_sid, "old_block_id": b["block_id"], "layout": layout})
        made = run_process(argv, rex.timeout)
        require(made.get("outcome") == "created_and_verified" and made.get("actual", {}).get("attached") is True, "surface_creation_not_verified_inspect_before_retry")
        bid = made.get("created", {}).get("block_id")
        require(full_id(bid, "block") and made["actual"].get("block_id") == bid and made["actual"].get("session_id") == sid, "surface_receipt_identity_mismatch")
        old = declared.get((saved["source"]["server"], old_sid, b["block_id"])) or {"host": saved["source"]["host_id"], "server": saved["source"]["server"], "session_id": old_sid, "block_id": b["block_id"]}
        new = {"host": old["host"], "server": rex.server, "session_id": sid, "block_id": bid}
        is_seat = old in (saved.get("boards") or {}).get("seats", []) or launch.get("seat")
        mapping = {"old": old, "new": new, "seat": is_seat, "holding_shell": holding, "geometry": made["actual"]}
        mappings.append(mapping)
        map_by_old[key(old)] = new
        created_panes.append((pane, new))
        store.journal({"event": "pane_mapped", "mapping": mapping})
        return bid

    def subdivide(sid, old_sid, node, first, panes):
        split = node.get("split")
        if not split:
            return
        other = leaves(split["after"])[0]
        bid = opened(sid, old_sid, panes[other], "tiled", anchor=first,
                     direction="right" if split["direction"] == "horizontal" else "down", ratio=1 - split["ratio"])
        subdivide(sid, old_sid, split["before"], first, panes)
        subdivide(sid, old_sid, split["after"], bid, panes)

    try:
        for s in saved["sessions"]:
            old_sid = s["view"]["session_id"]
            store.journal({"event": "session_create_attempt", "old_session_id": old_sid})
            made = rex.call("session.create", {"label": s["view"].get("label") or "recovered"})
            sid = made.get("session_id")
            require(full_id(sid, "session"), "session_creation_receipt_unavailable")
            session_map[old_sid] = sid
            store.journal({"event": "session_mapped", "old_session_id": old_sid, "new_session_id": sid})
            panes = {p["block"]["block_id"]: p for p in s["panes"]}
            for w in s["view"].get("windows") or []:
                anchor = None
                for i, layer in enumerate(w["layers"]):
                    first_old = leaves(layer["layout"])[0]
                    first = opened(sid, old_sid, panes[first_old], "tab" if i == 0 else "float", anchor=anchor,
                                   bounds=layer["bounds"] if i else None)
                    if not i:
                        anchor = first
                        # Tab labels and pane labels are independent public facts.
                        wid = mappings[-1]["geometry"]["window_id"]
                        rex.call("session.set_window_label", {"session_id": sid, "window_id": wid, "label": w.get("label") or "recovered"})
                    subdivide(sid, old_sid, layer["layout"], first, panes)
        # Later subdivisions move earlier leaves. Re-inspect every final rectangle
        # before releasing any command, rather than treating creation geometry as final.
        expected = {}
        def remember(node, layer):
            if node.get("block_id"):
                expected[node["block_id"]] = {"rect": node["rect"], "bounds": layer["bounds"], "kind": layer["kind"]}
            else:
                remember(node["split"]["before"], layer)
                remember(node["split"]["after"], layer)
        for s in saved["sessions"]:
            for w in s["view"].get("windows") or []:
                for layer in w["layers"]:
                    remember(layer["layout"], layer)
        for mapping, (pane, _) in zip(mappings, created_panes):
            new = mapping["new"]
            checked = run_process([executable, "surfaces", "inspect", "--socket", rex.socket,
                                   "--session", new["session_id"], "--pane", new["block_id"]], rex.timeout)
            actual = checked.get("actual") or {}
            require(checked.get("outcome") == "inspected" and actual.get("block_id") == new["block_id"] and actual.get("attached") is True, "final_surface_inspection_failed")
            rect = actual.get("rect") or []
            wanted = expected[mapping["old"]["block_id"]]
            require(len(rect) == 4 and all(abs(x - y) <= .000001 for x, y in zip(rect, wanted["rect"])), "final_layout_geometry_mismatch_commands_withheld")
            require(actual.get("layer_kind") == wanted["kind"] and len(actual.get("layer_bounds") or []) == 4 and all(abs(x - y) <= .000001 for x, y in zip(actual["layer_bounds"], wanted["bounds"])), "final_layer_geometry_mismatch_commands_withheld")
            require(actual.get("host_id") == plan["context"]["target"]["host_id"] and actual.get("session_id") == new["session_id"], "final_pane_host_or_session_mismatch")
            require(actual.get("label") == (pane["block"].get("label") or "recovered"), "final_pane_label_mismatch_commands_withheld")
            mapping["geometry"] = actual
            store.journal({"event": "final_geometry_verified", "mapping": mapping})
        board_handoff = None
        if (saved.get("boards") or {}).get("targets"):
            inventory = {(saved["source"]["server"], s["view"]["session_id"], p["block"]["block_id"]) for s in saved["sessions"] for p in s["panes"]}
            board_targets = {key(t) for t in saved["boards"]["targets"] if key(t) in inventory}
            if board_targets:
                board_map = [{"old": m["old"], "new": m["new"]} for m in mappings if key(m["old"]) in board_targets]
                require(len(board_map) == len(board_targets), "boards_target_not_restored")
                store.create("board-map.json", board_map)
                board_handoff = {"map_file": os.path.join(store.path, "board-map.json"), "applied": False,
                                 "next": "boards state remap-preview --store ABS --map-file ABS; then explicit remap-apply with preview generation and reason"}
                if args.board_store:
                    board_handoff["preview"] = run_process([executable, "boards", "state", "remap-preview", "--store", args.board_store,
                                                            "--map-file", board_handoff["map_file"]], rex.timeout)
                    require(board_handoff["preview"].get("outcome") == "preview_only", "boards_remap_preview_not_confirmed")
        remapped_launches = []
        for pane, new in created_panes:
            launch = copy.deepcopy(pane.get("launch") or {})
            report = ""
            inbox = ""
            for field in ("target", "starter", "report_to", "inbox"):
                if launch.get(field):
                    launch[field] = map_by_old[key(launch[field])]
            if launch.get("report_to"):
                report = launch["report_to"]["session_id"] + " " + launch["report_to"]["block_id"]
            if launch.get("inbox"):
                inbox = launch["inbox"]["session_id"] + " " + launch["inbox"]["block_id"]
            starter = ""
            if launch.get("starter"):
                starter = launch["starter"]["session_id"] + " " + launch["starter"]["block_id"]
            store.journal({"event": "routing_write_attempt", "target": new})
            data = report + "\n" + inbox + "\n" + starter + "\n"
            ack = rex.call("com.superlogical.terminal.write", {"session_id": new["session_id"], "block_id": new["block_id"], "args": {"data": data}})
            require(ack.get("bytes_written") == len(data.encode()), "routing_queue_ack_incomplete_no_retry")
            store.journal({"event": "routing_queued", "target": new, "consumption": "not_assessed"})
            if launch:
                remapped_launches.append(launch)
        receipt = {"schema_version": 1, "kind": "recovery_remap", "source": saved["source"], "target": plan["context"]["target"],
                   "sessions": session_map, "mappings": mappings, "launches": remapped_launches,
                   "outcome": "partial_restore_with_explicit_omissions" if omissions else "structure_restored_routing_queued",
                   "omissions": plan["omissions"], "support": OMISSIONS, "agent_readiness": "not_assessed",
                   "command_execution": "not_assessed", "board_state_applied": False, "board_handoff": board_handoff, "retry_safe": False}
        store.create("remap.json", receipt)
        store.journal({"event": "finished", "outcome": receipt["outcome"]})
        return {"schema_version": 1, "kind": "restore_result", "outcome": receipt["outcome"], "mapped_panes": len(mappings),
                "receipt": os.path.join(store.path, "remap.json"), "board_state_applied": False,
                "agent_readiness": "not_assessed", "retry_safe": False}, 3 if omissions else 0
    except BaseException:
        store.journal({"event": "interrupted_or_failed", "outcome": "partial_or_uncertain_inspect_journal_before_any_action", "mapped_panes": len(mappings), "retry_safe": False})
        raise


def summary(saved):
    return {"schema_version": 1, "kind": "snapshot_result", "source": saved["source"],
            "sessions": len(saved["sessions"]), "panes": sum(len(s["panes"]) for s in saved["sessions"]),
            "drafts_captured": False, "omissions": saved["omissions"], "snapshot_sha256": digest(saved)}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="teerex recovery", description="Private bounded Rex snapshot and restore (API13), update inventory (API10..13). Python 3.9+. No updater, close, screen scraping or retries.",
                                     epilog="Exit 0: requested structural evidence only, not complete recovery; 1: refusal/uncertainty; 2: usage; 3: explicit partial restore; 124: controller deadline; 130/143: cancellation. See items/recovery/README.md for omissions.")
    sub = parser.add_subparsers(dest="operation", required=True)
    descriptions = {"snapshot": "Capture layout/labels/hosts/process cwd plus explicit private launch/board references. No drafts or automatic argv/resume discovery.",
                    "restore": "Default is read-only preview. Apply creates visible panes only on an empty same-host server, with exact target/impact hash confirmation. Agents require a fresh gate and are withheld.",
                    "update": "Read-only running-vs-installed CLI inventory and pane impact. Optional snapshot; update/restart/restore are manual, separate actions, never performed here.",
                    "inspect": "Read the private snapshot inventory and per-field support without contacting Rex or exposing full argv/resume IDs on stdout."}
    for name in ("snapshot", "restore", "update", "inspect"):
        p = sub.add_parser(name, help=descriptions[name], description=descriptions[name])
        location = p.add_mutually_exclusive_group(required=name != "update")
        location.add_argument("--directory", help="existing private owned 0700 directory; files 0600, never overwritten")
        location.add_argument("--root", help="private snapshot root; snapshot creates a timestamped child, inspect/restore select newest complete snapshot")
        if name != "inspect":
            p.add_argument("--socket", required=True, help="explicit absolute socket on command host")
            p.add_argument("--timeout-ms", type=int, default=5000, help="per child/request bound 100..60000 ms")
        if name in ("snapshot", "update", "restore"):
            p.add_argument("--board-store", help="explicit private boards store; snapshot routing refs only, restore remap-preview only")
        if name in ("snapshot", "update"):
            p.add_argument("--metadata", help="absolute private schema1 entries JSON; no credentials/briefs/drafts")
            p.add_argument("--registry", help="explicit private agents registry; sanitized launch metadata only")
        if name == "restore":
            p.add_argument("--apply", action="store_true", help="create visible panes; requires exact preview token; never closes old panes")
            p.add_argument("--confirm", help="exact confirmation hash from matching preview")
            p.add_argument("--accept-omissions", action="store_true", help="preview/apply holding shells for missing commands or gated agents; never pretends resume")
        if name == "update":
            p.add_argument("--snapshot", action="store_true", help="save snapshot before manual update; requires --directory")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        if args.root:
            require(os.path.isabs(args.root), "root_must_be_absolute")
            if args.operation == "snapshot" or args.operation == "update" and args.snapshot:
                os.makedirs(args.root, mode=0o700, exist_ok=True)
            with contextlib.closing(Store(args.root)) as root:
                if args.operation == "snapshot" or args.operation == "update" and args.snapshot:
                    name = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-%020d" % time.time_ns()
                    os.mkdir(name, mode=0o700, dir_fd=root.fd)
                    args.directory = os.path.join(args.root, name)
                else:
                    candidates = []
                    for name in os.listdir(root.fd):
                        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}(?:-[0-9]{20})?", name):
                            continue
                        with contextlib.closing(Store(os.path.join(args.root, name))) as child:
                            if "snapshot.json" in os.listdir(child.fd):
                                load_snapshot(child)
                                candidates.append(name)
                    require(candidates, "no_complete_snapshot_under_root")
                    args.directory = os.path.join(args.root, max(candidates))
        if args.operation == "inspect":
            with contextlib.closing(Store(args.directory)) as store:
                saved = load_snapshot(store)
            result = summary(saved)
            result["inventory"] = [{"session_id": s["view"]["session_id"], "label": s["view"].get("label"),
                                    "panes": [{"block": p["block"], "cwd": p["cwd"], "command_support": p["command_support"], "field_support": p.get("field_support"),
                                               "harness": (p.get("launch") or {}).get("harness"), "resume_id_support": "explicit_metadata_unverified" if (p.get("launch") or {}).get("resume_session_id") else "unknown"} for p in s["panes"]]} for s in saved["sessions"]]
        else:
            require(100 <= args.timeout_ms <= 60000, "timeout_must_be_100_to_60000_ms")
            rex = Rex(args.socket, args.timeout_ms / 1000)
            if args.operation == "snapshot":
                result = summary(snapshot(rex, args))
                result["path"] = os.path.join(args.directory, "snapshot.json")
            elif args.operation == "restore":
                require(not args.confirm or args.apply, "confirmation_is_only_for_apply")
                with contextlib.closing(Store(args.directory)) as store:
                    saved = load_snapshot(store)
                    result = restore_plan(rex, saved, args.accept_omissions)
                    if args.apply:
                        result, code = restore_apply(rex, saved, result, store, args)
                        print(json.dumps(result, ensure_ascii=False))
                        return code
            else:
                require(not args.snapshot or args.directory, "update_snapshot_requires_private_directory")
                source = rex.identity(allow_older=True)
                installed = run_process([rex.executable, "version", "--json"], rex.timeout)
                require(isinstance(installed, dict), "invalid_installed_Rex_version")
                inventory = []
                sessions = rex.call("session.list").get("sessions") or []
                require(len(sessions) <= MAX_SESSIONS, "update_exceeds_32_sessions")
                for s in sessions:
                    for b in rex.call("session.list_blocks", {"session_id": s["session_id"]}).get("blocks") or []:
                        inventory.append({"session_id": s["session_id"], **b})
                        require(len(inventory) <= MAX_PANES, "update_exceeds_128_panes")
                require(rex.identity(allow_older=True) == source, "server_identity_changed_during_update_inventory_no_retry")
                running_commit = source["version"].get("commit")
                installed_commit = installed.get("commit")
                result = {"schema_version": 1, "kind": "update_preview", "running": source, "installed_cli": installed,
                          "build_differs": running_commit != installed_commit if running_commit and installed_commit else None,
                          "api_differs": source["version"].get("api_revision") != installed.get("api_revision") if "api_revision" in installed else None,
                          "inventory_consistency": "bounded_per_session_observations_not_atomic_serverwide",
                          "installed_comparison_scope": "selected_Rex_CLI_on_command_host_not_GUI_bundle_or_remote_installation",
                          "panes_at_risk": inventory, "impact_certainty": "inventory_not_proof_every_attached_host_process_will_close",
                          "update_performed": False, "restart_performed": False, "restore_performed": False,
                          "execution_support": "manual_handoff_no_public_update_API", "drafts_recoverable": False,
                          "snapshot_support": "supported_API13_subset" if source["version"]["api_revision"] == 13 else "unsupported_snapshot_requires_API13; preserve_manual_accounting_before_update",
                          "next": "Review pane inventory and snapshot omissions. Use this target server's documented update/restart control manually with explicit authorization. Then run restore preview against the empty restarted server; confirm its exact token separately."}
                if args.snapshot:
                    if source["version"]["api_revision"] != 13:
                        result["snapshot"] = {"outcome": "unsupported_API_revision", "written": False}
                        result["next"] = "Do not update on this receipt alone: snapshot is unavailable on this old API. Preserve manual accounting and drafts separately; no automatic recovery claim."
                        print(json.dumps(result, ensure_ascii=False))
                        return 1
                    result["snapshot"] = summary(snapshot(rex, args))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Cancelled as e:
        print(json.dumps({"schema_version": 1, "kind": "recovery_failure", "outcome": "cancelled_partial_or_uncertain", "signal": e.number, "retry_safe": False}))
        return 128 + e.number
    except (Refusal, OSError, ValueError, KeyError, TypeError) as e:
        # Private argv, drafts, server diagnostics and credentials never echo in errors.
        reason = str(e) if isinstance(e, Refusal) else type(e).__name__
        print(json.dumps({"schema_version": 1, "kind": "recovery_failure", "outcome": "refused_or_uncertain", "reason": reason, "retry_safe": False}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
