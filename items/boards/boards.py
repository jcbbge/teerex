"""Foreground boards and explicit seat storage. Embedded by main.zig; Python 3.9+."""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import select
import selectors
import signal
import stat
import subprocess
import sys
import textwrap
import time

MAX_BYTES = 1048576
MAX_SEATS = 32
MAX_RECORDS = 128
MAX_FLEET = 128
STATES = ("working", "waiting_on_operator", "idle", "dead", "completed", "unknown")
ID = re.compile(r"^(session|block):[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
HOST = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class Refused(Exception):
    pass


class Deadline(Refused):
    pass


class Cancelled(Exception):
    def __init__(self, signum):
        self.signum = signum


def cancelled(signum, _frame):
    raise Cancelled(signum)


def check(ok, reason):
    if not ok:
        raise Refused(reason)


def text(value, limit=4096, multiline=True):
    check(isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= limit,
          "text_empty_or_too_large")
    check(all(ord(c) >= 32 and ord(c) != 127 or multiline and c in "\n\t" for c in value),
          "control_characters_refused")
    return value


def exact(value, keys):
    check(isinstance(value, dict) and set(value) == set(keys), "unexpected_schema_fields")


def target(value):
    exact(value, ("host", "server", "session_id", "block_id"))
    check(isinstance(value["host"], str) and HOST.fullmatch(value["host"]), "invalid_host_name")
    check(isinstance(value["server"], str) and value["server"].startswith("unix:///")
          and os.path.isabs(value["server"][7:]), "absolute_unix_server_required")
    text(value["server"], 4096, False)
    for k in ("session", "block"):
        check(isinstance(value[k + "_id"], str) and ID.fullmatch(value[k + "_id"])
              and value[k + "_id"].startswith(k + ":"), "canonical_full_target_required")
    return value


def card(value):
    exact(value, ("id", "title", "ask", "context", "options", "recommend"))
    for k in ("id", "title", "ask", "context", "recommend"):
        text(value[k], 128 if k == "id" else 4096)
    check(isinstance(value["options"], list) and 2 <= len(value["options"]) <= 8, "two_to_eight_options_required")
    labels = []
    for option in value["options"]:
        exact(option, ("label", "gain", "lose"))
        for k in ("label", "gain", "lose"):
            text(option[k], 4096)
        check(option["label"] not in labels, "duplicate_option_label")
        labels.append(option["label"])
    return value


def stamp():
    return int(time.time() * 1000)


def private(fd, directory=False):
    s = os.fstat(fd)
    check(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == (0o700 if directory else 0o600)
          and (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink == 1),
          "store_requires_owned_0700_directory_and_0600_single_link_files")


def read_fd(fd, limit):
    check(stat.S_ISREG(os.fstat(fd).st_mode), "regular_file_required")
    with os.fdopen(os.dup(fd), "rb") as f:
        raw = f.read(limit + 1)
    check(len(raw) <= limit, "file_exceeds_bound")
    return raw.decode("utf-8")


def read_input(path, limit, deadline=None):
    check(path == "-" or os.path.isabs(path), "absolute_input_file_or_stdin_required")
    if path == "-":
        if deadline is None:
            raw = sys.stdin.buffer.read(limit + 1)
        else:
            raw = bytearray()
            fd = sys.stdin.fileno()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                    raise Deadline("stdin_EOF_deadline_no_record_saved")
                chunk = os.read(fd, min(65536, limit + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                check(len(raw) <= limit, "input_exceeds_bound")
        check(len(raw) <= limit, "input_exceeds_bound")
        return raw.decode("utf-8")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        return read_fd(fd, limit)
    finally:
        os.close(fd)


def json_load(raw):
    def pairs(items):
        d = {}
        for k, v in items:
            check(k not in d, "duplicate_json_key")
            d[k] = v
        return d
    return json.loads(raw, object_pairs_hook=pairs)


class Store:
    def __init__(self, path):
        check(os.path.isabs(path), "absolute_store_required")
        self.path = path
        self.dir = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.lock = None
        try:
            private(self.dir, True)
            self.lock = self.open("lock", os.O_RDWR | os.O_CREAT)
            private(self.lock)
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.state = {"schema_version": 1, "generation": 0, "seats": [], "fleet": []}
            try:
                fd = self.open("state.json", os.O_RDONLY)
            except FileNotFoundError:
                return
            try:
                private(fd)
                self.state = json_load(read_fd(fd, MAX_BYTES))
            finally:
                os.close(fd)
            validate_state(self.state)
        except BaseException:
            self.close()
            raise

    def open(self, name, flags):
        return os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.dir)

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.dir is not None:
            os.close(self.dir)
            self.dir = None

    def save(self):
        self.state["generation"] += 1
        validate_state(self.state)
        raw = json.dumps(self.state, ensure_ascii=False, indent=2).encode()
        reserved = sum(len(folded(s)[0]) for s in self.state["seats"]) * 16384
        check(len(raw) + reserved <= MAX_BYTES, "store_full_clear_explicitly_resolution_space_reserved")
        # An unreconciled crash staging file is never overwritten or promoted.
        fd = self.open("state.next", os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        renamed = False
        try:
            private(fd)
            with os.fdopen(os.dup(fd), "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.rename("state.next", "state.json", src_dir_fd=self.dir, dst_dir_fd=self.dir)
            renamed = True
            os.fsync(self.dir)
        finally:
            os.close(fd)
            if not renamed:
                os.unlink("state.next", dir_fd=self.dir)


def validate_state(s):
    exact(s, ("schema_version", "generation", "seats", "fleet"))
    check(s["schema_version"] == 1 and type(s["generation"]) is int and 0 <= s["generation"] < 2**53,
          "invalid_store_version_or_generation")
    check(isinstance(s["seats"], list) and len(s["seats"]) <= MAX_SEATS and isinstance(s["fleet"], list)
          and len(s["fleet"]) <= MAX_FLEET, "invalid_store_capacity")
    seen = []
    for seat in s["seats"]:
        exact(seat, ("target", "owner", "registered_at", "records"))
        target(seat["target"])
        text(seat["owner"], 128, False)
        check(type(seat["registered_at"]) is int and seat["registered_at"] > 0, "invalid_timestamp")
        check(seat["target"] not in seen, "duplicate_seat")
        seen.append(seat["target"])
        check(isinstance(seat["records"], list) and len(seat["records"]) <= MAX_RECORDS, "invalid_records_capacity")
        decisions = {}
        for r in seat["records"]:
            exact(r, ("kind", "at", "from", "body"))
            check(type(r["at"]) is int and r["at"] > 0, "invalid_timestamp")
            text(r["from"], 128, False)
            if r["kind"] == "message":
                text(r["body"], 65536)
            elif r["kind"] == "decision":
                card(r["body"])
                check(r["body"]["id"] not in decisions, "duplicate_decision_id")
                decisions[r["body"]["id"]] = False
            elif r["kind"] == "resolution":
                exact(r["body"], ("id", "answer"))
                text(r["body"]["answer"])
                check(r["body"]["id"] in decisions and not decisions[r["body"]["id"]], "resolution_without_open_decision")
                decisions[r["body"]["id"]] = True
            else:
                raise Refused("unknown_record_kind")
    seen = []
    for r in s["fleet"]:
        exact(r, ("target", "owner", "purpose", "state", "at", "detail"))
        target(r["target"])
        text(r["owner"], 128, False)
        text(r["purpose"], 1024)
        text(r["detail"], 4096)
        check(r["state"] in STATES and type(r["at"]) is int and r["at"] > 0, "invalid_fleet_report")
        check(r["target"] not in seen, "duplicate_fleet_target")
        seen.append(r["target"])


def result(**fields):
    print(json.dumps(dict(schema_version=1, **fields), ensure_ascii=False), flush=True)


def selected(a):
    check(os.path.isabs(a.socket), "absolute_socket_required")
    return target(dict(host=a.host, server="unix://" + a.socket, session_id=a.session, block_id=a.block))


def seat_for(store, t):
    return next((s for s in store.state["seats"] if s["target"] == t), None)


def folded(seat):
    opened, done, activity = {}, [], []
    for r in seat["records"]:
        if r["kind"] == "decision":
            opened[r["body"]["id"]] = r
        elif r["kind"] == "resolution":
            done.append((opened.pop(r["body"]["id"]), r))
        else:
            activity.append(r)
    return list(opened.values()), done, activity


def mutate(a):
    t = selected(a)
    with contextlib.closing(Store(a.store)) as store:
        seat = seat_for(store, t)
        if a.command == "try-route":
            if seat is None:
                result(kind="inbox_route", outcome="not_registered", target=t,
                       generation=store.state["generation"], terminal_input_attempted=False)
                return 3
            a.command, a.operation = "inbox", "append"
        if a.command == "seat" and a.operation == "inspect":
            result(kind="seat", registered=seat is not None, seat=seat, generation=store.state["generation"],
                   provenance="report", live_state="not_checked", store=a.store)
            return 0
        if a.command == "seat" and a.operation == "register":
            text(a.owner, 128, False)
            check(seat is None, "seat_already_registered_inspect_before_clear")
            check(len(store.state["seats"]) < MAX_SEATS, "seat_capacity_reached")
            seat = dict(target=t, owner=a.owner, registered_at=stamp(), records=[])
            store.state["seats"].append(seat)
        elif a.command == "fleet":
            existing = next((r for r in store.state["fleet"] if r["target"] == t), None)
            if a.operation == "report":
                for k, limit in (("owner", 128), ("purpose", 1024), ("detail", 4096)):
                    text(getattr(a, k), limit)
                r = dict(target=t, owner=a.owner, purpose=a.purpose, state=a.state, at=stamp(), detail=a.detail)
                if existing:
                    store.state["fleet"].remove(existing)
                check(len(store.state["fleet"]) < MAX_FLEET, "fleet_capacity_reached")
                store.state["fleet"].append(r)
            else:
                check(existing is not None, "fleet_report_not_found")
                check(a.generation == store.state["generation"], "generation_conflict")
                text(a.reason)
                store.state["fleet"].remove(existing)
        else:
            check(seat is not None, "target_not_registered_as_seat_no_terminal_input_attempted")
            if a.operation == "clear":
                check(a.generation == store.state["generation"], "generation_conflict")
                text(a.reason)
                if a.command == "seat":
                    check(not seat["records"], "clear_inbox_before_unregistering_seat")
                    store.state["seats"].remove(seat)
                else:
                    check(not folded(seat)[0], "resolve_open_decisions_before_clear")
                    seat["records"] = []
            else:
                text(a.sender, 128, False)
                check(len(seat["records"]) < MAX_RECORDS, "inbox_full_resolve_and_clear_explicitly")
                if a.command == "inbox":
                    body = text(read_input(a.message_file, 65536, getattr(a, "input_deadline", None)), 65536)
                    # Legacy typed message prefixes are rejected, never silently demoted to activity.
                    check(not body.startswith(("DECISION-JSON:", "DECISION-RESOLVED-JSON:")), "use_typed_ask_command")
                    kind = "message"
                elif a.resolve is not None:
                    check(a.card_file is None and a.answer is not None, "resolve_requires_answer_not_card")
                    text(a.resolve, 128)
                    body = dict(id=a.resolve, answer=text(a.answer))
                    check(any(r["body"]["id"] == a.resolve for r in folded(seat)[0]), "open_decision_not_found")
                    kind = "resolution"
                else:
                    check(a.card_file is not None and a.answer is None, "ask_requires_card_file_or_resolve_answer")
                    body = card(json_load(read_input(a.card_file, 49152)))
                    check(not any(r["kind"] == "decision" and r["body"]["id"] == body["id"] for r in seat["records"]),
                          "decision_id_already_used")
                    # Reserve one future resolution record for every pinned card.
                    check(len(seat["records"]) + len(folded(seat)[0]) + 2 <= MAX_RECORDS,
                          "inbox_full_reserve_resolution_capacity")
                    kind = "decision"
                if kind == "message":
                    check(len(seat["records"]) + len(folded(seat)[0]) + 1 <= MAX_RECORDS,
                          "inbox_full_reserve_resolution_capacity")
                seat["records"].append(dict(kind=kind, at=stamp(), **{"from": a.sender}, body=body))
        if getattr(a, "input_deadline", None) is not None and time.monotonic() >= a.input_deadline:
            raise Deadline("inbox_deadline_before_save_no_record_saved")
        store.save()
        result(kind="boards_result", command=a.command, operation=a.operation, outcome="recorded", target=t,
               generation=store.state["generation"], store=a.store, provenance="report", terminal_input_attempted=False,
               application_consumption="not_assessed", global_atomicity=False)
        return 0


def bounded_command(argv, timeout=5):
    env = {k: v for k, v in os.environ.items() if k not in ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT")}
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    out, err = bytearray(), bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ, out)
            selector.register(p.stderr, selectors.EVENT_READ, err)
            while selector.get_map():
                check(time.monotonic() < deadline, "rex_read_deadline")
                for key, _ in selector.select(min(.1, max(0, deadline - time.monotonic()))):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    key.data.extend(data)
                    check(len(out) <= MAX_BYTES and len(err) <= 8192, "rex_response_exceeds_bound")
        code = p.wait(timeout=max(.001, deadline - time.monotonic()))
        check(code == 0, "rex_read_failed_exit_" + str(code) + ": " + err.decode("utf-8", errors="replace")[:256])
        return json_load(out.decode())
    finally:
        # Only this invocation's transport process group; never a server or pane.
        if p.returncode is None:
            # The unreaped leader reserves this PID/group; never signal a re-used ID.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        p.stdout.close()
        p.stderr.close()


# One explicit read-only connection per configured server. No input/focus/launch methods.
READ_LUA = r'''
local function call(m,a)
  local v,e=rex.call(m,a); if not v then error(e) end
  if #rex.json.encode(v)>1048576 then error("response_exceeds_bound") end
  return v
end
local include_status=rex.args.include_status
local version=call("server.version")
if version.api_revision~=13 then error("fleet_requires_API13") end
local identity=call("server.status")
local rows={}
local sessions=call("session.list").sessions or {}
if #sessions>32 then error("session_limit_32") end
for _,s in ipairs(sessions) do
  call("session.attach",{session_id=s.session_id})
  local blocks=call("session.list_blocks",{session_id=s.session_id}).blocks or {}
  for _,b in ipairs(blocks) do
    if b.creator_name=="com.superlogical.terminal" then
      if #rows>=128 then error("terminal_limit_128") end
      local status=nil
      if include_status then
        status=call("com.superlogical.terminal.program_status",{session_id=s.session_id,block_id=b.block_id,args={}})
        if type(status.records)~="table" then error("invalid_status_records") end
      end
      table.insert(rows,{program_status=status,session=s.session_id,block=b.block_id,label=b.label or "",host_id=b.host_id,
        placement=b.placement,window_id=b.window_id})
    end
  end
end
io.write('{"version":',rex.json.encode(version),',"identity":',
  rex.json.encode({instance_id=identity.instance_id,host_id=identity.host_id}),',"rows":',
  #rows==0 and '[]' or rex.json.encode(rows),'}\n')
'''


def probe(socket, jobs_registry=None, teerex=None):
    check(os.path.isabs(socket), "absolute_socket_required")
    registrations = None
    if jobs_registry is not None:
        check(os.path.isabs(jobs_registry) and teerex is not None and os.path.isabs(teerex), "absolute_registry_and_teerex_required")
        registrations = bounded_command([teerex, "jobs", "list", "--registry", jobs_registry])
        check(registrations.get("kind") == "jobs_list", "invalid_jobs_list")
    live = bounded_command([os.environ.get("TEEREX_INTERNAL_REX") or "rex", "--autostart=false", "--server", "unix://" + socket,
                            "--timeout", "3s", "--color", "never", "do", "-e", READ_LUA, "--args", json.dumps(dict(include_status=jobs_registry is not None))])
    if registrations is not None:
        live["registrations"] = registrations["entries"]
    check(len(json.dumps(live).encode()) <= MAX_BYTES, "probe_response_exceeds_bound")
    return live


def status_evidence(raw):
    check(isinstance(raw, dict), "invalid_program_status")
    records = raw.get("records")
    if records == {}:  # Rex Lua encodes an empty table as an object.
        records = []
    check(isinstance(records, list) and len(records) <= 128, "invalid_status_records")
    projected = []
    seen = set()
    for record in records:
        check(isinstance(record, dict), "invalid_status_record")
        record_id = record.get("id")
        check(record_id is None or isinstance(record_id, str), "invalid_status_id")
        check(record_id not in seen, "duplicate_status_id")
        seen.add(record_id)
        check(record.get("state") in ("idle", "working", "done", "blocked", "error"), "invalid_status_state")
        result = {key: record.get(key) for key in ("id", "state", "app", "effective_app", "title", "updated_at")}
        for value in result.values():
            check(value is None or isinstance(value, str) and len(value.encode()) <= 4096, "invalid_status_text")
        result["age_ms"] = None
        try:
            timestamp = record["updated_at"].replace("Z", "+00:00")
            # Rex returns nanoseconds; Python 3.9/3.10 accepts up to microseconds.
            timestamp = re.sub(r"(\.\d{6})\d+", r"\1", timestamp)
            at = datetime.datetime.fromisoformat(timestamp)
            if at.tzinfo is not None:
                delta = stamp() - int(at.timestamp() * 1000)
                if delta >= 0:
                    result["age_ms"] = delta
        except (KeyError, AttributeError, ValueError, OverflowError):
            pass
        projected.append(result)
    return dict(provenance="terminal_report", freshness="unknown", records=projected,
                age_basis="board_host_wall_clock_minus_server_timestamp_not_freshness")


def fleet_snapshot(a, state):
    if a.targets_file:
        configured = json_load(read_input(a.targets_file, 65536))
        check(isinstance(configured, list) and 1 <= len(configured) <= 16, "targets_requires_one_to_sixteen_named_servers")
        hosts = []
        for cfg in configured:
            exact(cfg, ("host", "server"))
            zero = "00000000-0000-0000-0000-000000000000"
            target(dict(cfg, session_id="session:" + zero, block_id="block:" + zero))
            check(cfg["host"] not in hosts, "duplicate_named_host")
            hosts.append(cfg["host"])
    else:
        check(a.config is not None and a.hosts is not None and os.path.isabs(a.config), "config_and_hosts_required")
        names = a.hosts.split(",")
        check(1 <= len(names) <= 16 and len(set(names)) == len(names)
              and all(HOST.fullmatch(n) for n in names), "invalid_named_hosts")
        configured = [dict(name=n) for n in names]
    registries = {}
    for selection in a.jobs_registry:
        if selection.startswith("/"):
            name, path = "*", selection
        else:
            name, sep, path = selection.partition("=")
            check(sep and HOST.fullmatch(name), "jobs_registry_requires_ABS_or_HOST_equals_ABS")
        check(os.path.isabs(path) and not any(ord(c) < 32 or ord(c) == 127 for c in path), "absolute_jobs_registry_required")
        check(name not in registries, "duplicate_jobs_registry_host")
        registries[name] = path
    check(not ("*" in registries and len(registries) != 1), "jobs_registry_default_cannot_mix_with_host_paths")
    selected_names = {item.get("name", item.get("host")) for item in configured}
    check(all(name == "*" or name in selected_names for name in registries), "jobs_registry_host_not_selected")
    rows, sources, found = [], [], set()
    reports = {json.dumps(r["target"], sort_keys=True): r for r in state["fleet"]}
    for item in configured:
        cfg = item.copy()
        registry = registries.get(item.get("name", item.get("host")), registries.get("*"))
        try:
            if "name" in item:
                check(a.teerex is not None and os.path.isabs(a.teerex), "explicit_teerex_executable_required")
                resolved = bounded_command([a.teerex, "targets", "resolve", "--config", a.config, "--host", item["name"]])["host"]
                cfg = dict(host=resolved["host_id"], server="unix://" + resolved["socket"])
                live = bounded_command([a.teerex, "--config", a.config, "--host", item["name"], "boards", "probe"]
                                       + (["--jobs-registry", registry] if registry else []), timeout=8)
            else:
                live = probe(cfg["server"][7:], registry, a.teerex)
            check(live["version"]["api_revision"] == 13 and isinstance(live["rows"], list)
                  and len(live["rows"]) <= MAX_FLEET, "invalid_live_response")
            text(live["identity"]["instance_id"], 128, False)
            text(live["identity"]["host_id"], 128, False)
            registrations = live["registrations"] if registry else []
            check(isinstance(registrations, list) and len(registrations) <= 32, "invalid_jobs_response")
            matched_registrations = []
            local_rows, local_found = [], set()
            for b in live["rows"]:
                t = target(dict(cfg, session_id=b["session"], block_id=b["block"]))
                text(b["host_id"], 128, False)
                check(b["placement"] in ("placed", "detached"), "unknown_placement")
                check(isinstance(b["label"], str) and len(b["label"].encode()) <= 4096, "invalid_label")
                key = json.dumps(t, sort_keys=True)
                check(key not in local_found and key not in found, "duplicate_live_target")
                local_found.add(key)
                report = reports.get(key)
                local_rows.append(dict(target=t, observation=dict(present=True, placement=b["placement"],
                                      host_id=b["host_id"], label=b["label"], observed_at=stamp()),
                                      report=report, state=report["state"] if report else "unknown",
                                      state_provenance="report" if report else "unknown",
                                      agent_classification="reported_agent" if report else "unknown_terminal"))
                if registry:
                    registration = next((e for e in registrations if e["session_id"] == b["session"]
                        and e["block_id"] == b["block"] and (e["socket"] == cfg["server"][7:] or
                            (e["source"]["instance_id"] == live["identity"]["instance_id"] and e["source"]["host_id"] == live["identity"]["host_id"]))), None)
                    identity_matches = registration is not None and (
                        registration["source"]["instance_id"] == live["identity"]["instance_id"]
                        and registration["source"]["host_id"] == live["identity"]["host_id"]
                        and registration["block_host_id"] == b["host_id"])
                    if registration is not None:
                        matched_registrations.append(registration)
                    local_rows[-1].update(registration=registration, registration_matches_presence=identity_matches, presence=local_rows[-1]["observation"],
                                          program_status=status_evidence(b.get("program_status")))
                    if identity_matches and not report:
                        local_rows[-1]["agent_classification"] = "registered_" + registration["kind"]
            for e in registrations:
                if e in matched_registrations:
                    continue
                same_source = (e["source"]["instance_id"] == live["identity"]["instance_id"]
                               and e["source"]["host_id"] == live["identity"]["host_id"])
                t = target(dict(host=cfg["host"], server="unix://" + e["socket"], session_id=e["session_id"], block_id=e["block_id"]))
                key = json.dumps(t, sort_keys=True)
                report = reports.get(key)
                presence = dict(present=False if same_source else None,
                                reason="registered_pane_absent" if same_source else "registration_source_not_observed")
                local_rows.append(dict(target=t, observation=presence, presence=presence, registration=e, registration_matches_presence=False,
                                       program_status=None, report=report, state=report["state"] if report else "unknown",
                                       state_provenance="report" if report else "unknown", agent_classification="registered_" + e["kind"]))
                local_found.add(key)
            rows.extend(local_rows)
            found.update(local_found)
            sources.append(dict(**cfg, configured_name=item.get("name"), outcome="observed", provenance="observation",
                                source=live["identity"], version=live["version"], observed_at=stamp()))
        except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as e:
            sources.append(dict(**cfg, configured_name=item.get("name"), outcome="unknown", provenance="observation",
                                reason=str(e)[:256], observed_at=stamp()))
    # Unobserved and unselected saved reports remain visible, never silently dropped.
    for key, r in reports.items():
        if key not in found:
            rows.append(dict(target=r["target"], observation=dict(present=None, reason="not_observed_not_death_evidence"),
                             report=r, state=r["state"], state_provenance="report", agent_classification="reported_agent"))
    return dict(schema_version=1, kind="fleet_board", evaluated_at=stamp(), sources=sources, rows=rows,
                inference="none", completion="not_inferred", atomic_snapshot=False,
                scope="selected_named_servers_all_terminals_plus_all_saved_agent_reports")


def age(at):
    delta = stamp() - at
    return (str(delta // 1000) + "s ago") if delta >= 0 else "clock in future/unknown duration"


def wrap(value, width, indent="  "):
    lines = []
    # Untrusted live labels cannot inject terminal escape sequences.
    value = "".join(c if ord(c) >= 32 and ord(c) != 127 or c in "\n\t" else "?" for c in value)
    for para in value.expandtabs(4).splitlines() or [""]:
        lines.extend(textwrap.wrap(para, max(8, width - len(indent)), initial_indent=indent,
                                   subsequent_indent=indent, break_on_hyphens=False) or [indent])
    return lines


def render_inbox(seat, width):
    opened, done, activity = folded(seat)
    lines = ["TEEREX / INBOX · read-only · " + seat["target"]["host"],
             "REPORTS, not operator approval · " + str(len(opened)) + " waiting on you", ""]
    if not opened:
        lines.append("No open decisions recorded. Silence says nothing about agents.")
    for r in opened:
        d = r["body"]
        lines += ["━" * min(width, 76), "DECISION · " + d["title"], "REPORT from " + r["from"] + " · " + age(r["at"]) + " · id " + d["id"]]
        lines += wrap(d["ask"], width) + ["CONTEXT"] + wrap(d["context"], width) + ["OPTIONS"]
        for i, op in enumerate(d["options"], 1):
            lines += wrap(str(i) + ". " + op["label"], width)
            lines += wrap("+ Gain: " + op["gain"], width, "    ") + wrap("− Loss: " + op["lose"], width, "    ")
        lines += ["RECOMMENDATION"] + wrap(d["recommend"], width)
        lines += wrap("Resolve explicitly: teerex ask [same target/store] --resolve " + d["id"] + " --answer 'operator words' --from operator", width)
    if done:
        lines += ["", "RESOLVED · reported answers"]
        for d, r in done[-2:]:
            lines += wrap(d["body"]["title"] + ": " + r["body"]["answer"], width)
    lines += ["", "RECENT ACTIVITY · latest 6 reports (inspect for full text)"]
    for r in activity[-6:]:
        lines += wrap(r["from"] + " · " + age(r["at"]) + " · " + r["body"].splitlines()[0], width)
    return "\n".join(part for line in lines for part in wrap(line, width, ""))


def render_fleet(snapshot, width):
    lines = ["TEEREX / FLEET · live read-only · no silence inference",
             "OBSERVATION = Rex facts; REPORT = agent/operator claim; unknown = unestablished", ""]
    for src in snapshot["sources"]:
        lines += wrap(src.get("host", src.get("name", "unknown")) + " · OBSERVATION " + src["outcome"]
                      + " · " + src.get("reason", "API13 read completed"), width)
    for row in snapshot["rows"]:
        t, r, obs = row["target"], row["report"], row["observation"]
        lines += ["─" * min(width, 76)]
        lines += wrap(t["host"] + " / " + obs.get("label", t["block_id"]) + " · " + row["agent_classification"], width)
        lines += wrap("STATE " + row["state"] + " [" + row["state_provenance"] + "]" + (" · reported " + age(r["at"]) if r else " · duration unknown"), width)
        lines += wrap("OWNER " + (r["owner"] if r else "unknown") + " · PURPOSE " + (r["purpose"] if r else "unknown"), width)
        lines += wrap("OBSERVATION presence=" + str(obs["present"]) + " · placement=" + obs.get("placement", "unknown"), width)
        if "registration" in row:
            reg = row["registration"]
            lines += wrap("REGISTRATION [jobs] " + (reg["owner"] + " · " + reg["purpose"] + " · " + reg["kind"]
                          + " · matches presence=" + str(row["registration_matches_presence"]) + " · generation=" + str(reg["generation"]) + " · deadline=" + str(reg["deadline_unix_ms"]) if reg else "unknown"), width)
            lines += wrap("PRESENCE [live] " + str(row["presence"]["present"]) + " · " + row["presence"].get("reason", "observed"), width)
            status = row["program_status"]
            if status is None or not status["records"]:
                lines += wrap("PROGRAM_STATUS [terminal report] unknown", width)
            else:
                for record in status["records"]:
                    lines += wrap("PROGRAM_STATUS [terminal report] " + str(record["id"]) + " · " + record["state"]
                                  + " · app=" + str(record["app"] or record["effective_app"]) + " · title=" + str(record["title"])
                                  + " · age=" + (str(record["age_ms"]) + "ms (clock difference; freshness unknown)" if record["age_ms"] is not None else "unknown"), width)
        if r:
            lines += wrap("REPORT " + r["detail"], width)
        lines += wrap(t["session_id"] + " / " + t["block_id"], width)
    if not snapshot["rows"]:
        lines.append("No terminal rows observed; this is not a claim that the fleet is idle or dead.")
    return "\n".join(part for line in lines for part in wrap(line, width, ""))


def board(a):
    tty = sys.stdout.isatty()
    check(a.once or tty, "live_board_requires_visible_tty_use_once_for_capture")
    if a.view == "inbox":
        t = selected(a)
    try:
        while True:
            # Release lock between refreshes and before every Rex request.
            with contextlib.closing(Store(a.store)) as store:
                state = store.state
                seat = seat_for(store, t) if a.view == "inbox" else None
                generation = state["generation"]
            width = max(32, min(160, os.get_terminal_size().columns if tty and not a.once else a.width))
            if a.view == "inbox":
                check(seat is not None, "seat_not_registered")
                payload = dict(schema_version=1, kind="inbox_board", seat=seat, generation=generation, provenance="report")
                rendered = render_inbox(seat, width)
            else:
                payload = fleet_snapshot(a, state)
                rendered = render_fleet(payload, width)
            if a.json:
                print(json.dumps(payload, ensure_ascii=False), flush=True)
            else:
                print(("\x1b[2J\x1b[H" if tty else "") + rendered, flush=True)
            if a.once:
                return 0 if a.view != "fleet" or all(s["outcome"] == "observed" for s in payload["sources"]) else 1
            time.sleep(a.interval_ms / 1000)
    except KeyboardInterrupt:
        return 130


def state_command(a):
    with contextlib.closing(Store(a.store)) as store:
        if a.operation == "inspect":
            result(kind="boards_state", store=a.store, state=store.state, provenance="report", live_state="not_checked")
            return 0
        mappings = json_load(read_input(a.map_file, 65536))
        check(isinstance(mappings, list) and 1 <= len(mappings) <= MAX_FLEET, "invalid_remap_count")
        old, new = [], []
        for m in mappings:
            exact(m, ("old", "new"))
            target(m["old"])
            target(m["new"])
            check(m["old"] not in old and m["new"] not in new and m["old"] != m["new"], "duplicate_or_unchanged_mapping")
            old.append(m["old"])
            new.append(m["new"])
        affected = []
        for records in (store.state["seats"], store.state["fleet"]):
            for r in records:
                if r["target"] in old:
                    affected.append(r["target"])
                    r["target"] = new[old.index(r["target"])]
        check(all(t in affected for t in old), "mapping_source_not_registered")
        validate_state(store.state)  # Collision refusal before saving; swaps are allowed as a single local update.
        if a.operation == "remap-apply":
            check(a.generation == store.state["generation"], "generation_conflict")
            text(a.reason)
            store.save()
        result(kind="boards_remap", outcome="applied" if a.operation == "remap-apply" else "preview_only",
               mappings=mappings, generation=store.state["generation"], live_state="not_checked",
               provenance="report", terminal_input_attempted=False, global_atomicity=False)
        return 0


def parser():
    p = argparse.ArgumentParser(prog="teerex", description="Explicit operator seats, bounded typed inboxes, and visible read-only boards. Python3 required; no daemon. Reports never certify liveness/completion.")
    commands = p.add_subparsers(dest="command", required=True)

    def common(q, needs_target=True):
        q.add_argument("--store", required=True, help="existing private owned 0700 absolute directory; state stays on this command's machine")
        if needs_target:
            for k in ("host", "socket", "session", "block"):
                q.add_argument("--" + k, required=True)

    q = commands.add_parser("probe", help="one bounded read-only API13 fleet sample; root named-host routing supplies socket")
    q.add_argument("--socket", required=True)
    q.add_argument("--jobs-registry", help="absolute read-only jobs registry on this command host; max 32 entries/256 KiB")
    q.add_argument("--teerex", help="absolute current CLI; native bridge supplies self path")
    c = commands.add_parser("state", help="private authoritative inspect and explicit recovery remapping")
    ops = c.add_subparsers(dest="operation", required=True)
    for op in ("inspect", "remap-preview", "remap-apply"):
        q = ops.add_parser(op)
        common(q, False)
        if op != "inspect":
            q.add_argument("--map-file", required=True, help="absolute JSON [{old:target,new:target}]")
        if op == "remap-apply":
            q.add_argument("--generation", required=True, type=int)
            q.add_argument("--reason", required=True)
    for cmd, operations in (("seat", ("register", "inspect", "clear")), ("inbox", ("append", "inspect", "clear")), ("fleet", ("report", "forget"))):
        c = commands.add_parser(cmd)
        ops = c.add_subparsers(dest="operation", required=True)
        for op in operations:
            q = ops.add_parser(op)
            common(q)
            if op in ("register", "report"):
                q.add_argument("--owner", required=True)
            if op in ("clear", "forget"):
                q.add_argument("--generation", required=True, type=int)
                q.add_argument("--reason", required=True)
            if op == "append":
                q.add_argument("--from", dest="sender", required=True)
                q.add_argument("--message-file", required=True)
            if op == "report":
                q.add_argument("--purpose", required=True)
                q.add_argument("--state", choices=STATES, required=True)
                q.add_argument("--detail", required=True)
    q = commands.add_parser("try-route", help="append if exact seat registered; exit 3 ONLY for not_registered; all errors refuse")
    common(q)
    q.add_argument("--from", dest="sender", required=True)
    q.add_argument("--message-file", required=True)
    q.add_argument("--timeout-ms", type=int, default=10000, choices=range(100, 60001), metavar="100..60000",
                   help="registered stdin must reach EOF before deadline; no partial append; default 10000")
    q = commands.add_parser("ask", help="complete typed card or explicit resolution; never terminal input")
    common(q)
    q.set_defaults(operation="ask")
    q.add_argument("--from", dest="sender", required=True)
    group = q.add_mutually_exclusive_group(required=True)
    group.add_argument("--card-file", help="absolute JSON file or -; id/title/ask/context/options/recommend required")
    group.add_argument("--resolve")
    q.add_argument("--answer")
    c = commands.add_parser("boards", help="run in a visible Rex terminal; Ctrl+C stops; never starts a hidden watcher")
    views = c.add_subparsers(dest="view", required=True)
    for v in ("inbox", "fleet"):
        q = views.add_parser(v)
        common(q, v == "inbox")
        q.add_argument("--once", action="store_true", help="one bounded snapshot, including non-TTY capture")
        q.add_argument("--json", action="store_true")
        q.add_argument("--width", type=int, default=80, choices=range(32, 161), metavar="32..160")
        q.add_argument("--interval-ms", type=int, default=2000, choices=range(500, 60001), metavar="500..60000")
        if v == "fleet":
            group = q.add_mutually_exclusive_group(required=True)
            group.add_argument("--targets-file", help='fixture/forwarded endpoints: absolute JSON list of {host,server:unix:///ABS}')
            group.add_argument("--config", help="actual shared config; --hosts selects exact names such as m5,hive,m1")
            q.add_argument("--hosts", help="comma-separated explicit shared-config names; unavailable hosts stay visible")
            q.add_argument("--jobs-registry", action="append", default=[], help="ABS for all selected command hosts, or repeat HOST=ABS per host (max 16); read-only jobs validation, 32 entries/256 KiB per registry; live status max 128 records/terminal, 1 MiB transport cap")
            q.add_argument("--teerex", help="absolute current CLI; native bridge supplies its self path, never PATH guessing")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Unlike argparse's default, reject duplicate options rather than accepting the last.
    options = [x.split("=", 1)[0] for x in argv if x.startswith("--")]
    check(len([x for x in options if x != "--jobs-registry"]) == len(set(x for x in options if x != "--jobs-registry")), "duplicate_option")
    a = parser().parse_args(argv)
    if a.command == "try-route":
        a.input_deadline = time.monotonic() + a.timeout_ms / 1000
    if a.command == "probe":
        check(options.count("--jobs-registry") <= 1, "duplicate_option")
        print(json.dumps(probe(a.socket, a.jobs_registry, a.teerex)), flush=True)
        return 0
    if a.command == "state":
        return state_command(a)
    if a.command == "inbox" and a.operation == "inspect":
        a.command, a.view, a.once, a.json, a.width = "boards", "inbox", True, True, 80
    return board(a) if a.command == "boards" else mutate(a)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        sys.exit(main())
    except Deadline as e:
        result(kind="boards_error", outcome="deadline_exceeded", reason=str(e), terminal_input_attempted=False,
               retry_safe=False, recovery="inspect_committed_state_before_retry")
        sys.exit(124)
    except (KeyboardInterrupt, Cancelled) as e:
        code = 128 + e.signum if isinstance(e, Cancelled) else 130
        result(kind="boards_error", outcome="cancelled", terminal_input_attempted=False,
               retry_safe=False, recovery="inspect_committed_state_before_retry")
        sys.exit(code)
    except (Refused, OSError, ValueError, KeyError, TypeError, RecursionError) as e:
        result(kind="boards_error", outcome="refused_or_unknown", reason=str(e)[:512], terminal_input_attempted=False,
               retry_safe=False, recovery="inspect_committed_state_and_state.next_before_retry")
        sys.exit(1)
