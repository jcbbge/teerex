"""Explicit, bounded Rex replay controller; no daemon, retries or implicit target.

Invariants: input targets only our created block; captures require consent; fixtures
never execute code; tokens never enter output; foreign live clients fail closed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

STOP = 0
SLUG = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}\Z")
SESSION = re.compile(r"session:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
GATE = "import os,sys,time;from pathlib import Path\np=Path(sys.argv[1])\nwhile not p.exists():time.sleep(.005)\nos.execvp(sys.argv[2],sys.argv[2:])"


class Refused(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as output:
        os.chmod(temporary, 0o600)
        output.write(data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode())
    temporary.rename(path)


def read_bounded(path, limit):
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise Refused("input_size_or_type_limit")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise Refused("input_size_or_type_limit")
    return data


def load(path, limit):
    value = json.loads(read_bounded(path, limit))
    if not isinstance(value, dict):
        raise Refused("input_object_required")
    return value


class Stream:
    """Incremental nonce-bound APC removal; keep foreign APCs as program bytes."""
    def __init__(self, ws, nonce, maximum):
        self.ws = ws
        self.received_bytes = 0
        self.nonce = nonce
        self.prefix = b"\x1b_rex1;" + str(nonce).encode() + b";"
        self.pending = bytearray()
        self.snapshot = None
        self.data = bytearray()
        self.chunks = []
        self.events = []
        self.start = time.monotonic()
        self.maximum = maximum
        self.end = None

    def append(self, data, elapsed):
        if not data:
            return
        if len(self.data) + len(data) > self.maximum or len(self.chunks) >= 65536:
            raise Refused("byte_limit")
        self.chunks.append([len(self.data), len(data), elapsed])
        self.data.extend(data)

    def pump(self, wait=.1):
        if not select.select([self.ws.sock], [], [], wait)[0]:
            return
        try:
            message = self.ws.receive()
        except (OSError, EOFError) as error:
            if "4000" in str(error):
                raise Refused("block_closed")
            if "1013" in str(error):
                raise Refused("stream_lost")
            old = self.ws
            old.sock.close()
            try:
                self.ws, nonce = data_resume(old.path, old.reconnect_token, self.received_bytes)
                if nonce != self.nonce:
                    raise Refused("stream_lost")
                return
            except (ValueError, OSError, EOFError):
                raise Refused("stream_lost")
        self.received_bytes += len(message)
        elapsed = int((time.monotonic() - self.start) * 1000)
        self.pending.extend(message)
        if len(self.pending) > self.maximum + 65536:
            raise Refused("byte_limit")
        if self.snapshot is None:
            index = self.pending.find(self.prefix)
            if index == -1:
                return
            self.snapshot = bytes(self.pending[:index])
            del self.pending[:index]
        output = bytearray()
        while self.pending:
            index = self.pending.find(self.prefix)
            if index == -1:
                # Retain only a potential marker prefix spanning messages.
                keep = min(len(self.pending), len(self.prefix) - 1)
                while keep and not self.prefix.startswith(self.pending[-keep:]):
                    keep -= 1
                count = len(self.pending) - keep
                output.extend(self.pending[:count])
                del self.pending[:count]
                break
            output.extend(self.pending[:index])
            del self.pending[:index]
            end = self.pending.find(b"\x1b\\", len(self.prefix))
            if end == -1:
                break
            event = json.loads(self.pending[len(self.prefix):end])
            del self.pending[:end + 2]
            if len(self.events) >= 4096:
                raise Refused("byte_limit")
            offset = len(self.data) + len(output)
            if event.get("type") == "resize":
                event = dict(type="resize", columns=event["cols"], rows=event["rows"])
            self.events.append(dict(event, offset=offset, t_ms=elapsed))
            if event.get("type") == "child_exited":
                self.end = "child_exited"
        self.append(output, elapsed)

    def exit_code(self):
        return next((e["exit_code"] for e in self.events if e["type"] == "child_exited"), None)


def fixture_write(destination, args, stream, version, end):
    destination = Path(destination)
    if destination.exists():
        raise Refused("output_exists")
    with tempfile.TemporaryDirectory(prefix=".replay-fixture-", dir=str(destination.parent)) as temporary:
        root = Path(temporary)
        snapshot = stream.snapshot or b""
        checkpoints = []
        if args.checkpoint_every_bytes:
            checkpoints = [dict(id="byte-" + str(offset), offset=offset) for offset in
                           range(args.checkpoint_every_bytes, len(stream.data) + 1, args.checkpoint_every_bytes)]
        if len(checkpoints) > 255:
            raise Refused("checkpoint_limit")
        checkpoints.append(dict(id="end", offset=len(stream.data)))
        manifest = dict(schema_version=1, kind="teerex_tty_fixture", id=args.id,
            provenance=dict(basis="sensitive", captured_by="teerex replay record", consent="allow_sensitive_capture_flag", rex=version),
            application=dict(name=Path(args.argv[0]).name, version="unknown", version_basis="unknown"),
            terminal=dict(start="blank_verified", initial=dict(columns=args.columns, rows=args.rows)),
            stream=dict(bytes=len(stream.data), sha256=digest(stream.data), snapshot_sha256=digest(snapshot),
                        complete=end in {"child_exited", "deadline", "cancelled"} and not stream.pending, end=end),
            chunks=stream.chunks, events=stream.events, checkpoints=checkpoints,
            omissions=[dict(what="theme", why="not replayed in v1")])
        save(root / "stream.bin", bytes(stream.data))
        save(root / "snapshot.bin", snapshot)
        save(root / "fixture.json", manifest)
        if (root / "fixture.json").stat().st_size > 4194304:
            raise Refused("manifest_limit")
        # Atomic publication without replacing an existing directory.
        if destination.exists():
            raise Refused("output_exists")
        root.rename(destination)
    return manifest


def fixture_load(root):
    root = Path(root)
    value = load(root / "fixture.json", 4194304)
    if value.get("kind") != "teerex_tty_fixture" or value.get("schema_version") != 1:
        raise Refused("fixture_schema_invalid")
    if not isinstance(value.get("stream"), dict) or not isinstance(value.get("terminal"), dict):
        raise Refused("fixture_schema_invalid")
    initial = value["terminal"].get("initial")
    if not isinstance(initial, dict) or set(initial) != {"columns", "rows"} or any(type(x) is not int or not 1 <= x <= 65535 for x in initial.values()):
        raise Refused("fixture_terminal_invalid")
    if not isinstance(value.get("events"), list) or not isinstance(value.get("checkpoints"), list):
        raise Refused("fixture_schema_invalid")
    if value.get("stream", {}).get("complete") is not True:
        raise Refused("fixture_incomplete")
    data = read_bounded(root / "stream.bin", 16777216)
    snapshot = read_bounded(root / "snapshot.bin", 16777216)
    if data is None or snapshot is None or len(data) != value["stream"]["bytes"] or digest(data) != value["stream"]["sha256"] or digest(snapshot) != value["stream"]["snapshot_sha256"]:
        raise Refused("fixture_hash_mismatch")
    offset = 0
    chunks = value["chunks"]
    if not isinstance(chunks, list) or len(chunks) > 65536:
        raise Refused("fixture_chunks_invalid")
    for chunk in chunks:
        if not isinstance(chunk, list) or len(chunk) != 3 or any(type(x) is not int for x in chunk) or chunk[0] != offset or chunk[1] <= 0 or chunk[2] < 0:
            raise Refused("fixture_chunks_invalid")
        offset += chunk[1]
    if offset != len(data):
        raise Refused("fixture_chunks_invalid")
    previous = 0
    for event in value["events"]:
        if not isinstance(event, dict):
            raise Refused("fixture_event_invalid")
        if type(event.get("offset")) is not int or not previous <= event["offset"] <= len(data) or type(event.get("t_ms")) is not int or event["t_ms"] < 0:
            raise Refused("fixture_event_invalid")
        previous = event["offset"]
        if event.get("type") == "resize" and any(type(event.get(k)) is not int or not 1 <= event[k] <= 65535 for k in ("columns", "rows")):
            raise Refused("fixture_resize_invalid")
    if len(value["events"]) > 4096 or len(value["checkpoints"]) > 256:
        raise Refused("fixture_event_limit")
    ids = set()
    for checkpoint in value["checkpoints"]:
        if not SLUG.fullmatch(checkpoint.get("id", "")) or checkpoint["id"] in ids or type(checkpoint.get("offset")) is not int or not 0 <= checkpoint["offset"] <= len(data):
            raise Refused("fixture_checkpoint_invalid")
        ids.add(checkpoint["id"])
    return value, data


def script_validate(value):
    if value.get("kind") != "teerex_live_script" or value.get("schema_version") != 1 or value.get("model_turns") != 0:
        raise Refused("script_schema_invalid")
    if not isinstance(value.get("steps"), list) or len(value["steps"]) > 512:
        raise Refused("script_steps_invalid")
    if sum(len(step.get("expect", [])) for step in value["steps"] if isinstance(step, dict)) > 512:
        raise Refused("script_facts_limit")
    verbs = {"write", "paste", "key", "resize", "checkpoint", "expect", "effect", "sleep_ms"}
    for step in value["steps"]:
        if not isinstance(step, dict) or len(set(step) & verbs) != 1 or set(step) - verbs - {"within_ms", "local_only", "basis", "needs_authoring"}:
            raise Refused("script_step_invalid")
        if "local_only" in step and (not isinstance(step["local_only"], str) or not step["local_only"].strip()):
            raise Refused("script_local_only_reason_invalid")
        if step.get("needs_authoring"):
            continue
        if "key" in step and (not isinstance(step["key"], dict) or not isinstance(step["key"].get("key"), str)):
            raise Refused("script_key_invalid")
        if "expect" in step:
            validate(step["expect"])
            if type(step.get("within_ms")) is not int or not 100 <= step["within_ms"] <= 60000:
                raise Refused("script_expect_deadline_invalid")
        if "sleep_ms" in step and (type(step["sleep_ms"]) is not int or not 0 <= step["sleep_ms"] <= 5000):
            raise Refused("script_sleep_invalid")
        for key in ("write", "paste"):
            if key in step:
                if not isinstance(step[key], str):
                    raise Refused("script_input_invalid")
                if any(c in step[key] for c in "\r\n") and not step.get("local_only"):
                    raise Refused("script_submits_without_local_only")
        if "key" in step and not step.get("local_only"):
            # Deny Enter conservatively, including raw control encodings.
            key = json.dumps(step["key"]).lower()
            if any(x in key for x in ("enter", "return", "\\r", "\\n", "\\u000d", "\\u000a")):
                raise Refused("script_submits_without_local_only")
        if "checkpoint" in step and (not isinstance(step["checkpoint"], dict) or not isinstance(step["checkpoint"].get("id"), str) or not SLUG.fullmatch(step["checkpoint"]["id"])):
            raise Refused("script_checkpoint_invalid")
        if "resize" in step and (not isinstance(step["resize"], dict) or set(step["resize"]) != {"columns", "rows"} or any(type(x) is not int or not 1 <= x <= 65535 for x in step["resize"].values())):
            raise Refused("script_resize_invalid")
        if "effect" in step:
            effect = step["effect"]
            if not isinstance(effect, dict) or effect.get("relative_to") != "cwd" or len(set(effect) & {"path_exists", "path_absent", "file_sha256"}) != 1:
                raise Refused("script_effect_invalid")
            entry = next(effect[x] for x in ("path_exists", "path_absent", "file_sha256") if x in effect)
            if "file_sha256" in effect and (not isinstance(entry, dict) or set(entry) != {"path", "sha256"} or not isinstance(entry["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"])):
                raise Refused("script_effect_hash_invalid")
            path = entry["path"] if isinstance(entry, dict) else entry
            if not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts:
                raise Refused("script_effect_path_invalid")


class Runner:
    def __init__(self, args, binary, player, packet):
        self.args, self.binary, self.player, self.packet = args, binary, player, packet
        self.control = None
        self.block = None
        self.stream = None
        self.work = tempfile.TemporaryDirectory(prefix="teerex-replay-", dir="/tmp")
        self.root = Path(self.work.name)
        self.deadline = time.monotonic() + args.timeout_ms / 1000
        self.version = None

    def check(self):
        if STOP:
            raise Refused("cancelled")
        if time.monotonic() >= self.deadline:
            raise Refused("deadline")

    def wait(self, predicate, until=None):
        while not predicate():
            self.check()
            if until and time.monotonic() >= until:
                raise Refused("resize_not_applied")
            self.stream.pump(.05)

    def connect(self):
        self.control = Control(self.args.socket)
        raw_call = self.control.call
        def guarded_call(method, payload):
            __import__('teerex_pane_guard').authorize('unix://' + self.args.socket, method, payload, raw_call)
            value = raw_call(method, payload)
            __import__('teerex_pane_guard').record_created('unix://' + self.args.socket, method, payload, value)
            return value
        self.control.call = guarded_call
        self.version = self.control.call("server.version", {})
        self.packet["rex"] = self.version
        self.control.call("session.attach", dict(session_id=self.args.session))
        if self.args.mode == "live" and not self.args.allow_attached_viewers:
            clients = self.control.call("session.list_clients", dict(session_id=self.args.session))["clients"]
            if len(clients) != 1:
                raise Refused("foreign_client_attached")

    def terminal(self, method, args=None):
        return self.control.call("com.superlogical.terminal." + method,
                                 dict(session_id=self.args.session, block_id=self.block, args=args or {}))

    def create(self, argv, playing=False):
        options = dict(shell="none", login=False, interactive=False, command=[sys.executable, "-c", GATE, str(self.root / "go"), *argv],
                       cwd=self.args.cwd or str(Path.cwd()), size=dict(columns=self.args.columns, rows=self.args.rows),
                       exit=dict(on_completion=False))
        if self.args.layout == "tab":
            made = self.control.call("session.new_window", dict(session_id=self.args.session,
                window_label=self.args.label, focus=False, layout=dict(block=dict(
                    flavor="com.superlogical.terminal.shell", options=options, label=self.args.label))))
            self.block = made["block_ids"][0]
        else:
            self.block = self.control.call("session.new_block", dict(session_id=self.args.session,
                flavor="com.superlogical.terminal.shell", options=options, label=self.args.label))["block_id"]
        self.packet["target"]["block_id"] = self.block
        self.control.call("session.own_block", dict(session_id=self.args.session, block_ids=[self.block], mode="take"))
        if self.args.layout == "offstage":
            self.terminal("resize", dict(columns=self.args.columns, rows=self.args.rows))
        ws, nonce = data_connect(self.control, self.args.socket, self.args.session, self.block)
        self.stream = Stream(ws, nonce, 16777216 if playing else self.args.max_bytes)
        self.wait(lambda: self.stream.events)
        initial = next(e for e in self.stream.events if e["type"] == "resize")
        self.args.columns, self.args.rows = initial["columns"], initial["rows"]
        captured = self.terminal("format", dict(format="text", max_bytes=65536))
        if captured.get("content", "").strip() or captured.get("eof") is False:
            raise Refused("not_blank")
        save(self.root / "go", b"go")

    def observation(self, name, facts, exit_code=None):
        self.check()
        command = [self.args.teerex or self.binary, "observe", "--socket", self.args.socket,
                   "--session", self.args.session, "--block", self.block, "--max-bytes", str(self.args.max_bytes if self.args.mode == "play" else 65536)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=min(10, max(.1, self.deadline - time.monotonic())))
        if result.returncode:
            raise Refused("observation_failed")
        observation = json.loads(result.stdout)
        path = Path(self.args.observations_out) / (name + ".observation.json")
        # Expectations overwrite their last sample atomically, never append unbounded history.
        save(path, observation)
        evaluated = evaluate(facts, observation, self.terminal("size"), self.terminal("modes"), exit_code)
        return dict(id=name, observation_path=str(path), facts=evaluated)

    def record(self):
        self.create(self.args.argv)
        end = "child_exited"
        try:
            self.wait(lambda: self.stream.end == "child_exited")
        except (Refused, EOFError) as error:
            end = str(error) if str(error) in {"deadline", "cancelled", "byte_limit", "block_closed"} else "stream_lost"
        fixture = fixture_write(self.args.out, self.args, self.stream, self.version, end)
        self.packet.update(fixture_path=self.args.out, stream=fixture["stream"])
        if STOP:
            return 128 + STOP, "cancelled"
        return (0, "recorded") if end == "child_exited" else (124, "deadline") if end == "deadline" else (1, end)

    def play(self, fixture, data, facts):
        self.args.columns, self.args.rows = fixture["terminal"]["initial"]["columns"], fixture["terminal"]["initial"]["rows"]
        player = self.root / "player.py"
        save(player, self.player.encode())
        self.create([sys.executable, str(player), str(self.root)], playing=True)
        checkpoints = list(fixture["checkpoints"])
        if not any(c["id"] == "end" for c in checkpoints):
            checkpoints.append(dict(id="end", offset=len(data)))
        boundaries = sorted({0, len(data), *(x[0] + x[1] for x in fixture["chunks"]),
                             *(x["offset"] for x in fixture["events"]), *(x["offset"] for x in checkpoints)})
        index = 0
        offset = 0
        started = time.monotonic()
        for boundary in boundaries:
            self.check()
            if boundary > offset:
                if self.args.pace == "recorded":
                    target = next((c[2] for c in fixture["chunks"] if c[0] <= offset < c[0] + c[1]), 0)
                    while time.monotonic() - started < min(60, target / 1000):
                        self.check()
                        self.stream.pump(.05)
                save(self.root / (str(index) + ".json"), dict(bytes=base64.b64encode(data[offset:boundary]).decode()))
                index += 1
                self.wait(lambda: len(self.stream.data) >= boundary)
                if self.stream.data[:boundary] != data[:boundary]:
                    raise Refused("replay_stream_mismatch")
                offset = boundary
            for event in fixture["events"]:
                if event["offset"] == boundary and event["type"] == "resize":
                    if self.args.pace == "recorded":
                        while time.monotonic() - started < min(60, event.get("t_ms", 0) / 1000):
                            self.check()
                            self.stream.pump(.05)
                    expected = dict(columns=event["columns"], rows=event["rows"])
                    current = self.terminal("size")
                    if any(current.get(k) != v for k, v in expected.items()):
                        before = len(self.stream.events)
                        self.terminal("resize", expected)
                        self.wait(lambda: any(e["type"] == "resize" and all(e.get(k) == v for k, v in expected.items()) for e in self.stream.events[before:]), time.monotonic() + 2)
                    actual = self.terminal("size")
                    if any(actual.get(k) != v for k, v in expected.items()):
                        raise Refused("resize_not_applied")
            for checkpoint in checkpoints:
                if checkpoint["offset"] == boundary:
                    exit_code = next((e["exit_code"] for e in fixture["events"] if e["type"] == "child_exited" and e["offset"] <= boundary), None)
                    self.packet["checkpoints"].append(self.observation(checkpoint["id"], facts.get(checkpoint["id"], []), exit_code))
        self.packet["stream_check"] = dict(compared_bytes=len(data), equal=bytes(self.stream.data) == data)
        if not self.packet["stream_check"]["equal"]:
            raise Refused("replay_stream_mismatch")
        values = [f["value"] for c in self.packet["checkpoints"] for f in c["facts"]]
        return (3, "facts_failed") if False in values else (3, "facts_unknown") if "unknown" in values else (0, "replay_faithful")

    def live(self, script):
        self.create(self.args.argv)
        for index, step in enumerate(script["steps"]):
            self.check()
            name = "step-" + str(index)
            if step.get("needs_authoring"):
                self.packet["not_run"].append(dict(id=name, reason="needs_authoring"))
                continue
            self.stream.pump(0)
            if "expect" in step:
                until = min(self.deadline, time.monotonic() + step["within_ms"] / 1000)
                while True:
                    self.stream.pump(0)
                    record = self.observation(name, step["expect"], self.stream.exit_code())
                    if all(f["value"] is True for f in record["facts"]):
                        break
                    if time.monotonic() >= until:
                        self.packet["steps"].append(record)
                        return 3, "live_divergence"
                    self.stream.pump(.1)
                self.packet["steps"].append(record)
            elif "write" in step:
                self.terminal("write", dict(data=step["write"]))
            elif "paste" in step or "key" in step:
                verb = "paste" if "paste" in step else "key"
                self.control.call("block.event", dict(session_id=self.args.session, block_id=self.block,
                                  event=dict(type=verb, payload=dict(text=step[verb]) if verb == "paste" else step[verb])))
            elif "resize" in step:
                self.terminal("resize", step["resize"])
                if any(self.terminal("size").get(k) != v for k, v in step["resize"].items()):
                    raise Refused("resize_not_applied")
            elif "checkpoint" in step:
                self.packet["steps"].append(self.observation(step["checkpoint"]["id"], [], self.stream.exit_code()))
            elif "effect" in step:
                effect = step["effect"]
                key = next(k for k in ("path_exists", "path_absent", "file_sha256") if k in effect)
                entry = effect[key]
                path = Path(self.args.cwd or os.getcwd()) / (entry["path"] if isinstance(entry, dict) else entry)
                base = Path(self.args.cwd or os.getcwd()).resolve()
                if base not in path.resolve().parents:
                    raise Refused("effect_outside_cwd")
                valid = path.exists() if key == "path_exists" else not path.exists() if key == "path_absent" else path.is_file() and path.stat().st_size <= 16777216 and digest(path.read_bytes()) == entry["sha256"]
                self.packet["steps"].append(dict(id=name, facts=[dict(id=key, value=valid, reason="filesystem_observation")]))
                if not valid:
                    return 3, "live_divergence"
            elif "sleep_ms" in step:
                until = time.monotonic() + step["sleep_ms"] / 1000
                while time.monotonic() < until:
                    self.check()
                    self.stream.pump(min(.05, until - time.monotonic()))
        if self.packet["not_run"]:
            return 3, "steps_not_run"
        return 0, "live_pass"

    def close(self):
        try:
            if self.stream:
                self.stream.ws.close()
            if self.block and not self.args.keep_open:
                self.control.call("block.close", dict(session_id=self.args.session, block_id=self.block))
                blocks = self.control.call("session.list_blocks", dict(session_id=self.args.session))["blocks"]
                self.packet["cleanup"]["block_absence_verified"] = all(b["block_id"] != self.block for b in blocks)
                if not self.packet["cleanup"]["block_absence_verified"]:
                    raise Refused("close_uncertain")
        finally:
            if self.control:
                self.control.close()
            self.work.cleanup()


def parse(argv):
    parser = argparse.ArgumentParser(prog='teerex replay', description="Capture Rex output, replay through Rex, or check a live program. Play and live are independent results. Python3.9+, explicit API13 Unix socket/session, same-host paths. No task completion inferred.")
    parser.add_argument("mode", choices=["record", "play", "live"])
    parser.add_argument("--socket", required=True)
    parser.add_argument("--session", required=True)
    for name in ("out", "id", "fixture", "facts", "observations-out", "script", "record-out", "cwd", "teerex"):
        parser.add_argument("--" + name)
    parser.add_argument("--layout", choices=["tab", "offstage"])
    parser.add_argument("--label", default="teerex replay")
    parser.add_argument("--columns", type=int, default=80)
    parser.add_argument("--rows", type=int, default=24)
    parser.add_argument("--timeout-ms", type=int)
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--checkpoint-every-bytes", type=int, default=0)
    parser.add_argument("--pace", choices=["fast", "recorded"], default="fast")
    parser.add_argument("--allow-sensitive-capture", action="store_true")
    parser.add_argument("--allow-attached-viewers", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    if "--" in argv:
        cut = argv.index("--")
        options, command = argv[:cut], argv[cut + 1:]
    else:
        options, command = argv, []
    args = parser.parse_args(options)
    args.argv = command
    if args.timeout_ms is None:
        args.timeout_ms = 300000 if args.mode == "live" else 60000
    for name in ("socket", "out", "fixture", "facts", "observations_out", "script", "record_out", "cwd", "teerex"):
        value = getattr(args, name)
        if value and not Path(value).is_absolute():
            parser.error("--" + name.replace("_", "-") + " must be absolute")
    if not SESSION.fullmatch(args.session):
        parser.error("full session:UUID required")
    if args.cwd and not Path(args.cwd).is_dir():
        parser.error("cwd must exist on command host")
    if not 1 <= args.columns <= 65535 or not 1 <= args.rows <= 65535 or not 100 <= args.timeout_ms <= 300000:
        parser.error("size/deadline out of range")
    if args.max_bytes is None:
        args.max_bytes = 65536 if args.mode == "play" else 4194304
    if not (256 <= args.max_bytes <= 65536 if args.mode == "play" else 65536 <= args.max_bytes <= 16777216):
        parser.error("max-bytes out of range")
    if args.checkpoint_every_bytes < 0:
        parser.error("checkpoint interval must be nonnegative")
    if args.mode in {"record", "live"} and not command:
        parser.error("literal argv after -- required")
    if args.mode == "record" and (not args.out or not args.id or not SLUG.fullmatch(args.id) or not args.allow_sensitive_capture):
        parser.error("record requires --out NEW_ABS_DIR --id SLUG --allow-sensitive-capture")
    if args.mode in {"play", "live"} and not args.observations_out:
        parser.error("--observations-out NEW_ABS_DIR required")
    if args.mode == "play" and (not args.fixture or command):
        parser.error("play requires --fixture and takes no argv")
    if args.mode == "live" and (not args.script or (args.record_out and not args.allow_sensitive_capture)):
        parser.error("live requires --script; --record-out requires --allow-sensitive-capture")
    if args.layout is None:
        args.layout = "tab" if args.mode == "record" else "offstage"
    return args


def main(argv, binary, player):
    args = parse(argv)
    packet = dict(schema_version=1, kind="replay_result", mode=args.mode, outcome="not_started",
                  target=dict(server="unix://" + args.socket, session_id=args.session, block_id=None),
                  checkpoints=[], steps=[], not_run=[], cleanup=dict(block_absence_verified=False),
                  retry_safe=False, task_completion="not_assessed", interpretation="none", model_turns="not_observed")
    runner = None
    code = 1
    try:
        fixture = data = script = None
        facts = {}
        for output in (args.out, args.observations_out, args.record_out):
            if output and Path(output).exists():
                raise Refused("output_exists")
        if args.mode == "play":
            fixture, data = fixture_load(args.fixture)
            packet["fixture"] = dict(id=fixture["id"], sha256=digest(read_bounded(Path(args.fixture) / "fixture.json", 4194304)))
            facts_path = args.facts or (str(Path(args.fixture) / "facts.json") if (Path(args.fixture) / "facts.json").exists() else None)
            if facts_path:
                document = load(facts_path, 262144)
                if document.get("schema_version") != 1 or document.get("kind") != "teerex_display_facts" or not isinstance(document.get("at"), dict):
                    raise Refused("facts_schema_invalid")
                facts = document["at"]
                if sum(len(x) for x in facts.values()) > 512:
                    raise Refused("facts_limit")
                for group in facts.values():
                    validate(group)
                if set(facts) - {c["id"] for c in fixture["checkpoints"]} - {"end"}:
                    raise Refused("facts_checkpoint_missing")
        if args.mode == "live":
            script = load(args.script, 262144)
            script_validate(script)
            packet["script"] = dict(id=script["id"], sha256=digest(read_bounded(args.script, 262144)))
        if args.observations_out:
            Path(args.observations_out).mkdir(mode=0o700)
        runner = Runner(args, binary, player, packet)
        runner.connect()
        if args.mode == "record":
            code, packet["outcome"] = runner.record()
        elif args.mode == "play":
            code, packet["outcome"] = runner.play(fixture, data, facts)
        else:
            code, packet["outcome"] = runner.live(script)
            if args.record_out:
                args.id = script["id"]
                manifest = fixture_write(args.record_out, args, runner.stream, runner.version, runner.stream.end or "cancelled")
                packet["fixture_path"] = args.record_out
                packet["stream"] = manifest["stream"]
    except (Refused, ValueError, OSError, EOFError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, Refused) else "wire_or_input_failure"
        packet["outcome"] = reason
        code = 128 + STOP if STOP else 124 if reason == "deadline" else 1
    finally:
        if runner:
            try:
                runner.close()
            except (ValueError, OSError, EOFError, Refused, KeyError):
                packet["outcome"] = "close_uncertain"
                code = 1
    print(json.dumps(packet, ensure_ascii=False))
    return code


def stop(signum, frame):
    global STOP
    STOP = signum


if __name__ == "__main__":
    # Zig embeds support sources as argv; direct source invocation is for development.
    if len(sys.argv) >= 5 and sys.argv[2].startswith('"""Rex'):
        binary, wire_source, facts_source, player_source = sys.argv[1:5]
        exec(compile(wire_source, "replay/wire.py", "exec"), globals())
        exec(compile(facts_source, "replay/facts.py", "exec"), globals())
        arguments = sys.argv[5:]
    else:
        from wire import Control, data_connect, data_resume
        from facts import evaluate, validate
        binary = os.environ.get("TEEREX_BIN", str(Path("zig-out/bin/teerex").resolve()))
        player_source = Path(__file__).with_name("player.py").read_text()
        arguments = sys.argv[1:]
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    sys.exit(main(arguments, binary, player_source))
