"""Public CLI checks: offline comparisons and disposable Rex, never the default server."""

import copy
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest


BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex"))


def compare_packets(root, before, after):
    first, second = root / "before.json", root / "after.json"
    first.write_text(json.dumps(before), encoding="utf-8")
    second.write_text(json.dumps(after, sort_keys=True), encoding="utf-8")
    return subprocess.run(
        [str(BIN), "compare", "--before", str(first), "--after", str(second)],
        env=dict(os.environ, PATH="/no-rex-or-other-executables"),
        capture_output=True, text=True, timeout=5,
    )


class CompareTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="tc03-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.before = {
            "schema_version": 1, "observation_id": "a" * 32,
            "observation_started_at_unix_ms": 20, "observed_at_unix_ms": 25,
            "atomic_snapshot": False,
            "target": {"server": "unix:///tmp/not-contacted.sock",
                       "session_id": "session:12345678-1234-1234-1234-123456789abc",
                       "block_id": "block:abcdef12-1234-1234-1234-123456789abc"},
            "source": {"rex_version": "0.1.0-preview.16", "platform": "darwin/arm64", "api_revision": 13},
            "capture": {"scope": "screen_and_scrollback", "portion": "prefix", "max_bytes": 256,
                        "complete": True, "content": "unchanged α\n"},
            "process": {"method": "com.superlogical.terminal.process", "basis": "rex_observation",
                        "freshness": "unknown", "data": {
                            "child": {"pid": 31, "name": "shell", "cwd": "/one"},
                            "foreground": {"pid": 47, "name": "worker", "cwd": "/two"}, "last_exit": None}},
            "reported_directory": {"method": "com.superlogical.terminal.pwd", "basis": "terminal_report",
                                   "freshness": "unknown", "reported_at": None,
                                   "data": {"pwd": "file://localhost/reported", "owner": {"pid": 31, "name": "shell"}}},
            "program_status": {"method": "com.superlogical.terminal.program_status", "basis": "program_reports",
                               "freshness": "unknown", "data": {"records": [
                                   {"id": None, "state": "working", "progress": 0, "updated_at": "server-time-a"},
                                   {"id": "child", "state": "blocked", "kind": "permission", "updated_at": "server-time-b"}]}},
        }
        self.after = copy.deepcopy(self.before)
        self.after.update(observation_id="b" * 32, observation_started_at_unix_ms=10, observed_at_unix_ms=15)

    def compared(self):
        result = compare_packets(self.root, self.before, self.after)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_equal_evidence_ignores_packet_times_ids_and_object_key_order(self):
        packet = self.compared()
        self.assertEqual(packet["kind"], "observation_changes")
        self.assertEqual(packet["before_observation_id"], "a" * 32)
        self.assertEqual(packet["after_observation_id"], "b" * 32)
        self.assertEqual(packet["interpretation"], "none")
        self.assertIs(packet["capture"]["full_text_changed"], False)
        self.assertIs(packet["capture"]["captured_text_changed"], False)
        for node in [packet["process"]["foreground"], packet["process"]["child"],
                     packet["reported_directory"], packet["program_status"]]:
            self.assertEqual(node, {"before_available": True, "after_available": True,
                                    "availability_changed": False, "changed": False})
        self.assertIsNone(packet["process"]["last_exit"]["changed"])
        self.assertNotIn("content", packet["capture"])
        self.assertNotIn("completion", packet)
        self.assertEqual((self.root / "before.json").read_text(encoding="utf-8"), json.dumps(self.before))
        self.assertEqual((self.root / "after.json").read_text(encoding="utf-8"), json.dumps(self.after, sort_keys=True))

    def test_distinct_changes_and_new_exit_evidence_are_not_completion(self):
        self.after["capture"]["content"] = "different β\n"
        self.after["process"]["data"]["foreground"]["cwd"] = "/three"
        self.after["process"]["data"]["last_exit"] = {"exit_code": 7}
        self.after["reported_directory"]["data"]["pwd"] = "file://localhost/different"
        self.after["program_status"]["data"]["records"][0]["state"] = "done"
        packet = self.compared()
        self.assertIs(packet["capture"]["full_text_changed"], True)
        self.assertIs(packet["process"]["foreground"]["changed"], True)
        self.assertIs(packet["process"]["child"]["changed"], False)
        self.assertIs(packet["reported_directory"]["changed"], True)
        self.assertIs(packet["program_status"]["changed"], True)
        self.assertEqual(packet["process"]["last_exit"], {
            "before_available": False, "after_available": True, "availability_changed": True, "changed": None})
        self.assertEqual(packet["interpretation"], "none")

    def test_partial_prefixes_and_different_capture_limits(self):
        self.before["capture"]["complete"] = self.after["capture"]["complete"] = False
        packet = self.compared()["capture"]
        self.assertIs(packet["captured_text_changed"], False)
        self.assertIsNone(packet["full_text_changed"])
        self.after["capture"]["content"] = "different prefix"
        packet = self.compared()["capture"]
        self.assertIs(packet["captured_text_changed"], True)
        self.assertIsNone(packet["full_text_changed"])
        self.after["capture"]["max_bytes"] = 257
        packet = self.compared()["capture"]
        self.assertIsNone(packet["captured_text_changed"])
        self.assertIsNone(packet["full_text_changed"])
        self.after["capture"]["complete"] = True
        self.assertIsNone(self.compared()["capture"]["full_text_changed"])
        self.before["capture"]["complete"] = True
        packet = self.compared()["capture"]
        self.assertIs(packet["captured_text_changed"], True)
        self.assertIs(packet["full_text_changed"], True)

    def test_unknown_and_disappearing_evidence_is_not_unchanged(self):
        self.after["process"]["data"]["foreground"] = None
        self.after["reported_directory"]["data"] = {}
        del self.before["program_status"]
        packet = self.compared()
        for node in [packet["process"]["foreground"], packet["reported_directory"]]:
            self.assertEqual(node, {"before_available": True, "after_available": False,
                                    "availability_changed": True, "changed": None})
        self.assertEqual(packet["program_status"], {
            "before_available": False, "after_available": True, "availability_changed": True, "changed": None})
        for packet_input in [self.before, self.after]:
            for key in ["process", "reported_directory", "program_status"]:
                packet_input.pop(key, None)
        packet = self.compared()
        self.assertEqual(packet["program_status"], {
            "before_available": False, "after_available": False, "availability_changed": False, "changed": None})
        self.assertIsNone(packet["process"]["foreground"]["changed"])

    def test_report_order_is_irrelevant_but_timestamp_and_zero_are_evidence(self):
        self.after["program_status"]["data"]["records"].reverse()
        self.assertIs(self.compared()["program_status"]["changed"], False)
        self.after["program_status"]["data"]["records"][1]["updated_at"] = "server-time-c"
        self.assertIs(self.compared()["program_status"]["changed"], True)
        self.after = copy.deepcopy(self.before)
        del self.after["program_status"]["data"]["records"][0]["progress"]
        self.assertIs(self.compared()["program_status"]["changed"], True)
        self.before["program_status"]["data"]["records"] = []
        self.after["program_status"]["data"]["records"] = []
        self.assertEqual(self.compared()["program_status"], {
            "before_available": True, "after_available": True, "availability_changed": False, "changed": False})

    def test_api_range_preserves_revision_and_refuses_outside_bounds(self):
        for revision in [10, 11, 12, 13]:
            with self.subTest(revision=revision):
                self.before["source"]["api_revision"] = revision
                self.after["source"]["api_revision"] = revision
                self.assertEqual(self.compared()["source"]["api_revision"], revision)
        for revision in [9, 14]:
            with self.subTest(revision=revision):
                self.before["source"]["api_revision"] = revision
                self.after["source"]["api_revision"] = revision
                result = compare_packets(self.root, self.before, self.after)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn(f"revision {revision}", result.stderr)
        self.before["source"]["api_revision"] = 10
        self.after["source"]["api_revision"] = 12
        self.assertEqual(compare_packets(self.root, self.before, self.after).returncode, 1)

    def test_incompatible_targets_versions_and_provenance_fail_closed(self):
        for path, value in [
            (("target", "server"), "unix:///tmp/other.sock"),
            (("target", "session_id"), "session:99999999-1234-1234-1234-123456789abc"),
            (("target", "block_id"), "block:99999999-1234-1234-1234-123456789abc"),
            (("target", "block_id"), "block:partial"),
            (("source", "rex_version"), "other-version"), (("source", "platform"), "other-platform"),
            (("source", "api_revision"), 14), (("schema_version",), 2),
            (("capture", "scope"), "viewport"), (("capture", "portion"), "tail"),
            (("capture", "max_bytes"), 255), (("capture", "content"), "x" * 255),
            (("process", "basis"), "inferred"), (("reported_directory", "freshness"), "fresh"),
            (("program_status", "method"), "other.method"),
        ]:
            with self.subTest(path=path):
                other = copy.deepcopy(self.after)
                node = other
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                result = compare_packets(self.root, self.before, other)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        self.after["program_status"]["data"]["records"].append(
            copy.deepcopy(self.after["program_status"]["data"]["records"][0]))
        result = compare_packets(self.root, self.before, self.after)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DuplicateStatusId", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_file_limits_malformed_packets_and_arguments(self):
        valid, invalid = self.root / "valid.json", self.root / "invalid.json"
        valid.write_text(json.dumps(self.before), encoding="utf-8")
        for data in [b"not json", b"{}", b'[{"partial":', b" " * (1024 * 1024 + 1)]:
            with self.subTest(size=len(data)):
                invalid.write_bytes(data)
                result = subprocess.run([str(BIN), "compare", "--before", str(valid), "--after", str(invalid)],
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        for args in [[], ["--before"], ["--before", str(valid)], ["--after", str(valid)],
                     ["--before", str(self.root / "does-not-exist")],
                     ["--before", str(valid), "--after", str(valid), "--after", str(valid)],
                     ["--before", str(valid), "--unknown", str(valid)]]:
            with self.subTest(args=args):
                result = subprocess.run([str(BIN), "compare", *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")


class ObserveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = shutil.which("rex")
        if not cls.rex or not BIN.is_file():
            raise RuntimeError("Build teerex and put the test Rex binary on PATH first")
        cls.tmp = tempfile.TemporaryDirectory(prefix="tx-", dir="/tmp")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.endpoint = "unix://" + str(cls.socket)
        cls.base = [cls.rex, "--autostart=false", "--server", cls.endpoint, "--timeout", "2s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen(
            [cls.rex, "server", "run", "--listen", cls.endpoint, "--restore=false",
             "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
            stdout=cls.log, stderr=cls.log,
        )
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Test server did not create its isolated socket")
        cls.a = cls.fixture('TEEREX_ALPHA "quoted" α\n')
        cls.b = cls.fixture("TEEREX_BETA\n")
        cls.long = cls.fixture('TEEREX_LONG α " \\ \t\n' * 1000)
        cls.edge_text = "a" * 70 + "\n" + "b" * 70 + "\n" + "c" * 70 + "\n" + "d" * 39
        cls.edge = cls.fixture(cls.edge_text)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def rex_json(cls, *args):
        result = subprocess.run(cls.base + list(args), capture_output=True, text=True, timeout=10, check=True)
        return json.loads(result.stdout)

    @classmethod
    def fixture(cls, text, *, cwd=None, after_output="time.sleep(120)", marker=None):
        script = "import os,sys,time;"
        if cwd is not None:
            script += f"os.chdir({str(cwd)!r});"
        script += "sys.stdout.write(sys.argv[1]);sys.stdout.flush();" + after_output
        created = cls.rex_json(
            "new", "--json", "--keep-open", "--shell=none", "--", sys.executable, "-c",
            script, text,
        )
        target = (created["session_id"], created["initial_windows"][0]["block_ids"][0])
        cls.wait_for(target, "format", lambda value: (marker or text.split()[0]) in value["content"])
        return target

    @classmethod
    def wait_for(cls, target, method, predicate):
        args = {"format": "text", "max_bytes": 4096} if method == "format" else {}
        for _ in range(100):
            value = cls.rex_json("api", "call", "com.superlogical.terminal." + method, json.dumps({
                "session_id": target[0], "block_id": target[1],
                "args": args,
            }))
            if predicate(value):
                return value
            time.sleep(.05)
        raise RuntimeError("Fixture did not reach expected " + method + " state")

    def observe(self, target, *extra, socket=None):
        env = dict(os.environ, REX_SERVER="unix:///tmp/not-the-selected-server.sock",
                   REX_SESSION=self.b[0], REX_BLOCK=self.b[1])
        return subprocess.run(
            [str(BIN), "observe", "--socket", str(socket or self.socket),
             "--session", target[0], "--block", target[1], *extra],
            env=env, capture_output=True, text=True, timeout=15,
        )

    def baseline(self, target, *extra):
        result = self.observe(target, *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / f"baseline-{time.monotonic_ns()}.json"
        path.write_text(result.stdout, encoding="utf-8")
        return path, json.loads(result.stdout)

    def watch_command(self, target, baseline, *, timeout=3000, interval=50, socket=None,
                      status_state=None, status_id=None):
        command = [str(BIN), "watch", "--socket", str(socket or self.socket),
                   "--session", target[0], "--block", target[1], "--baseline", str(baseline),
                   "--interval-ms", str(interval)]
        command += ["--no-deadline"] if timeout is None else ["--timeout-ms", str(timeout)]
        if status_state is not None:
            for state in ([status_state] if isinstance(status_state, str) else status_state):
                command += ["--status-state", state]
        if status_id is not None:
            command += ["--status-id", status_id]
        return command

    def gated_fixture(self, text, action):
        gate = self.root / f"gate-{time.monotonic_ns()}"
        script = ("deadline=time.monotonic()+120\n"
                  f"while not os.path.exists({str(gate)!r}) and time.monotonic()<deadline: time.sleep(.01)\n"
                  + action + "\ntime.sleep(120)")
        return self.fixture("TEEREX_WATCH_READY\n" + text, after_output=script,
                            marker="TEEREX_WATCH_READY"), gate

    def triggered_watch(self, target, baseline, gate, **options):
        process = subprocess.Popen(self.watch_command(target, baseline, **options),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(.25)
            gate.touch()
            stdout, stderr = process.communicate(timeout=8)
            return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=3)

    def test_explicit_target_and_read_only_result(self):
        before = self.rex_json("session", "ls", "--json")
        blocks_before = self.rex_json("block", "ls", "--session", self.a[0], "--json")
        result = self.observe(self.a)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["schema_version"], 1)
        self.assertEqual(packet["target"], {
            "server": self.endpoint, "session_id": self.a[0], "block_id": self.a[1],
        })
        self.assertIn('TEEREX_ALPHA "quoted" α', packet["capture"]["content"])
        self.assertNotIn("TEEREX_BETA", packet["capture"]["content"])
        self.assertTrue(packet["capture"]["complete"])
        self.assertFalse(packet["atomic_snapshot"])
        self.assertEqual(packet["source"]["api_revision"], self.rex_json("api", "call", "server.version")["api_revision"])
        self.assertEqual(packet["source"]["rex_version"], self.rex_json("api", "call", "server.version")["rex_version"])
        self.assertEqual(packet["capture"]["scope"], "screen_and_scrollback")
        self.assertEqual(len(bytes.fromhex(packet["observation_id"])), 16)
        self.assertGreater(packet["observed_at_unix_ms"], 0)
        self.assertEqual(self.rex_json("session", "ls", "--json"), before)
        self.assertEqual(self.rex_json("block", "ls", "--session", self.a[0], "--json"), blocks_before)
        again = json.loads(self.observe(self.a).stdout)
        self.assertEqual(again["capture"], packet["capture"])
        self.assertNotEqual(again["observation_id"], packet["observation_id"])
        comparison = compare_packets(self.root, packet, again)
        self.assertEqual(comparison.returncode, 0, comparison.stderr)
        changes = json.loads(comparison.stdout)
        self.assertIs(changes["capture"]["full_text_changed"], False)
        self.assertIs(changes["process"]["foreground"]["changed"], False)
        self.assertIs(changes["program_status"]["changed"], False)
        self.assertIsNone(changes["reported_directory"]["changed"])
        self.assertEqual(changes["interpretation"], "none")

    def test_missing_reports_remain_unknown_not_idle(self):
        result = self.observe(self.a)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertIsNone(packet["reported_directory"]["data"]["pwd"])
        self.assertIsNone(packet["reported_directory"]["data"]["owner"])
        self.assertIsNone(packet["reported_directory"]["reported_at"])
        self.assertEqual(packet["program_status"]["data"]["records"], [])
        self.assertIsNone(packet["process"]["data"]["last_exit"])
        for key, method, basis in [
            ("process", "process", "rex_observation"),
            ("reported_directory", "pwd", "terminal_report"),
            ("program_status", "program_status", "program_reports"),
        ]:
            self.assertEqual(packet[key]["method"], "com.superlogical.terminal." + method)
            self.assertEqual(packet[key]["basis"], basis)
            self.assertEqual(packet[key]["freshness"], "unknown")
        self.assertIsInstance(packet["observation_started_at_unix_ms"], int)

    def test_reports_do_not_follow_actual_process_directory(self):
        first, later = self.root / "actual first", self.root / "actual later"
        first.mkdir()
        later.mkdir()
        gate = self.root / "move"
        reported = "file://localhost/not-the-process-cwd%20reported"
        reports = (
            f"\x1b]7;{reported}\x07"
            "\x1b]7501;state=working:app=teerex-test:progress=0\x1b\\"
            "\x1b]7501;state=blocked:id=child:kind=permission:progress=71:msg=UmV2aWV3IG9ubHk=\x1b\\"
            "TEEREX_REPORTER\n"
        )
        after_output = (
            "print('TEEREX_PID='+str(os.getpid()),flush=True)\n"
            "deadline=time.monotonic()+120\n"
            f"while not os.path.exists({str(gate)!r}) and time.monotonic()<deadline: time.sleep(.01)\n"
            f"os.chdir({str(later)!r})\n"
            "print('TEEREX_MOVED',flush=True)\n"
            "time.sleep(120)"
        )
        target = self.fixture(reports, cwd=first, after_output=after_output, marker="TEEREX_REPORTER")
        screen = self.wait_for(target, "format", lambda v: "TEEREX_PID=" in v["content"])
        pid = int(re.search(r"TEEREX_PID=(\d+)", screen["content"])[1])
        result = self.observe(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        foreground = packet["process"]["data"]["foreground"]
        self.assertEqual(foreground["pid"], pid)
        self.assertEqual(Path(foreground["cwd"]), first.resolve())
        self.assertNotIn("argv0", foreground)
        self.assertNotIn("home", packet["process"]["data"])
        self.assertEqual(packet["process"]["data"]["child"]["pid"], pid)
        directory = packet["reported_directory"]["data"]
        self.assertEqual(directory["pwd"], reported)
        self.assertEqual(directory["owner"], {"pid": pid, "name": foreground["name"]})
        records = packet["program_status"]["data"]["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual((records[0]["id"], records[0]["state"], records[0]["progress"]), (None, "working", 0))
        self.assertEqual((records[1]["id"], records[1]["state"], records[1]["progress"]), ("child", "blocked", 71))
        self.assertEqual(records[1]["kind"], "permission")
        self.assertEqual(records[1]["msg"], "Review only")
        self.assertEqual(records[1]["effective_app"], "teerex-test")
        self.assertEqual(records[1]["owner"], directory["owner"])
        self.assertTrue(records[1]["updated_at"])
        gate.touch()
        self.wait_for(target, "format", lambda v: "TEEREX_MOVED" in v["content"])
        moved = self.observe(target)
        self.assertEqual(moved.returncode, 0, moved.stderr)
        moved_packet = json.loads(moved.stdout)
        self.assertEqual(Path(moved_packet["process"]["data"]["foreground"]["cwd"]), later.resolve())
        self.assertEqual(moved_packet["reported_directory"], packet["reported_directory"])
        self.assertEqual(moved_packet["program_status"], packet["program_status"])
        self.assertFalse(moved_packet["atomic_snapshot"])
        comparison = compare_packets(self.root, packet, moved_packet)
        self.assertEqual(comparison.returncode, 0, comparison.stderr)
        changes = json.loads(comparison.stdout)
        self.assertIs(changes["capture"]["full_text_changed"], True)
        self.assertIs(changes["process"]["foreground"]["changed"], True)
        self.assertIs(changes["reported_directory"]["changed"], False)
        self.assertIs(changes["program_status"]["changed"], False)
        self.assertEqual(changes["interpretation"], "none")

    def test_retained_done_report_is_not_successful_exit(self):
        reported = "file://localhost/exited-reporter"
        gate = self.root / "exit"
        done = "\x1b]7501;state=done:app=teerex-test\x1b\\TEEREX_EXITED\n"
        target = self.fixture(
            f"\x1b]7;{reported}\x07\x1b]7501;state=working:app=teerex-test\x1b\\TEEREX_STARTED\n",
            after_output=("deadline=time.monotonic()+120\n"
                          f"while not os.path.exists({str(gate)!r}) and time.monotonic()<deadline: time.sleep(.01)\n"
                          f"sys.stdout.write({done!r});sys.stdout.flush();sys.exit(7)"),
            marker="TEEREX_STARTED",
        )
        before = self.observe(target)
        self.assertEqual(before.returncode, 0, before.stderr)
        before_packet = json.loads(before.stdout)
        self.assertEqual(before_packet["program_status"]["data"]["records"][0]["state"], "working")
        gate.touch()
        self.wait_for(target, "process", lambda v: v.get("last_exit") is not None)
        result = self.observe(target)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["process"]["data"]["last_exit"], {"exit_code": 7})
        self.assertIsNone(packet["process"]["data"]["foreground"])
        self.assertIsNone(packet["process"]["data"]["child"])
        self.assertEqual(packet["reported_directory"]["data"]["pwd"], reported)
        records = packet["program_status"]["data"]["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["state"], "done")
        self.assertIsNone(records[0]["progress"])
        self.assertEqual(packet["program_status"]["freshness"], "unknown")
        comparison = compare_packets(self.root, before_packet, packet)
        self.assertEqual(comparison.returncode, 0, comparison.stderr)
        changes = json.loads(comparison.stdout)
        self.assertEqual(changes["process"]["foreground"], {
            "before_available": True, "after_available": False, "availability_changed": True, "changed": None})
        self.assertEqual(changes["process"]["last_exit"], {
            "before_available": False, "after_available": True, "availability_changed": True, "changed": None})
        self.assertIs(changes["reported_directory"]["changed"], False)
        self.assertIs(changes["program_status"]["changed"], True)
        self.assertEqual(changes["interpretation"], "none")

    def test_bounded_utf8_capture_marks_partial_prefix(self):
        result = self.observe(self.long, "--max-bytes", "256")
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = json.loads(result.stdout)["capture"]
        self.assertTrue(capture["content"].startswith('TEEREX_LONG α "'))
        self.assertFalse(capture["complete"])
        self.assertEqual(capture["portion"], "prefix")
        self.assertEqual(capture["max_bytes"], 256)
        self.assertLessEqual(len(json.dumps(capture["content"], ensure_ascii=False).encode()), 256)
        self.assertNotIn("\ufffd", capture["content"])
        whole = self.observe(self.long, "--max-bytes", "65536")
        self.assertEqual(whole.returncode, 0, whole.stderr)
        self.assertTrue(json.loads(whole.stdout)["capture"]["complete"])

    def test_exact_encoded_string_boundary(self):
        self.assertEqual(len(json.dumps(self.edge_text).encode()), 257)
        partial = self.observe(self.edge, "--max-bytes", "256")
        self.assertEqual(partial.returncode, 0, partial.stderr)
        self.assertFalse(json.loads(partial.stdout)["capture"]["complete"])
        whole = self.observe(self.edge, "--max-bytes", "257")
        self.assertEqual(whole.returncode, 0, whole.stderr)
        capture = json.loads(whole.stdout)["capture"]
        self.assertTrue(capture["complete"])
        self.assertEqual(capture["content"], self.edge_text)
        comparison = compare_packets(self.root, json.loads(partial.stdout), json.loads(whole.stdout))
        self.assertEqual(comparison.returncode, 0, comparison.stderr)
        changes = json.loads(comparison.stdout)
        self.assertIsNone(changes["capture"]["captured_text_changed"])
        self.assertIsNone(changes["capture"]["full_text_changed"])
        self.assertIs(changes["process"]["foreground"]["changed"], False)

    def test_wrong_block_is_not_replaced_by_focus(self):
        result = self.observe((self.a[0], self.b[1]))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("failed", result.stderr)

    def test_missing_target_diagnostics_keep_requested_route_and_watch_unknown(self):
        baseline, before = self.baseline(self.a)
        absent_session = "session:00000000-0000-0000-0000-000000000001"
        absent_block = "block:00000000-0000-0000-0000-000000000002"
        env = dict(os.environ, REX_SERVER="unix:///tmp/not-the-selected-server.sock",
                   REX_SESSION=self.b[0], REX_BLOCK=self.b[1], REX_CLIENT="other-client")
        sessions_before = self.rex_json("session", "ls", "--json")
        for target in [(absent_session, self.a[1]), (self.a[0], absent_block), (self.a[0], self.b[1])]:
            with self.subTest(target=target):
                changed = copy.deepcopy(before)
                changed["target"].update(session_id=target[0], block_id=target[1])
                baseline.write_text(json.dumps(changed), encoding="utf-8")
                for command in [
                    [str(BIN), "observe", "--socket", str(self.socket),
                     "--session", target[0], "--block", target[1]],
                    self.watch_command(target, baseline),
                ]:
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    for expected in [self.endpoint, *target, "--server", "PATH", "No alternate host"]:
                        self.assertIn(expected, result.stderr)
                    if command[1] == "observe":
                        self.assertEqual(result.stdout, "")
                    else:
                        packet = json.loads(result.stdout)
                        self.assertEqual(packet["outcome"], "observation_failed")
                        self.assertEqual(packet["failure_reason"], "ObservationCommandFailed")
                        self.assertEqual(packet["target"], changed["target"])
                        self.assertEqual(packet["observations_compared"], 0)
                        self.assertIsNone(packet["last_comparison"])
                        self.assertIsNone(packet["changed_fields"])
        self.assertEqual(self.rex_json("session", "ls", "--json"), sessions_before)
        self.assertIn("TEEREX_ALPHA", self.observe(self.a).stdout)
        self.assertIn("TEEREX_BETA", self.observe(self.b).stdout)

    def test_missing_server_is_not_autostarted(self):
        missing = self.root / "missing.sock"
        result = self.observe(self.a, socket=missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(missing.exists())

    def test_invalid_options_are_rejected(self):
        for extra in [("--max-bytes", "255"), ("--max-bytes", "65537"),
                      ("--max-bytes", "-1"), ("--max-bytes", "NaN"), ("--max-bytes",),
                      ("--timeout-ms", "99"), ("--timeout-ms", "60001"),
                      ("--timeout-ms", "-1"), ("--timeout-ms", "NaN"), ("--timeout-ms",),
                      ("--timeout-ms", "1000", "--timeout-ms", "1000"),
                      ("--block", self.b[1]), ("--unknown", "x")]:
            with self.subTest(extra=extra):
                result = self.observe(self.a, *extra)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
        for target, socket in [(self.a, Path("relative")), (("partial", self.a[1]), self.socket),
                               ((self.a[0], "block:short-id"), self.socket)]:
            with self.subTest(target=target, socket=socket):
                result = self.observe(target, socket=socket)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
        for args in [("observe",), ("observe", "--socket", "relative"), ("missing",)]:
            with self.subTest(args=args):
                result = subprocess.run([str(BIN), *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_watch_quiet_deadline_is_not_completion_or_known_missing_evidence(self):
        baseline, before = self.baseline(self.a)
        original = baseline.read_bytes()
        env = dict(os.environ, REX_SERVER="unix:///tmp/wrong.sock", REX_SESSION=self.b[0], REX_BLOCK=self.b[1])
        result = subprocess.run(self.watch_command(self.a, baseline, timeout=650),
                                env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 124, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["kind"], "observation_wait")
        self.assertEqual(packet["outcome"], "deadline_exceeded")
        self.assertEqual(packet["target"], before["target"])
        self.assertEqual(packet["baseline_source"], before["source"])
        self.assertEqual(packet["baseline_observation_id"], before["observation_id"])
        self.assertEqual(packet["changed_fields"], [])
        self.assertEqual(packet["availability_changed_fields"], [])
        self.assertEqual(set(packet["unknown_fields"]), {"process.last_exit", "reported_directory"})
        self.assertGreaterEqual(packet["observations_compared"], 2)
        self.assertGreaterEqual(packet["elapsed_ms"], 650)
        self.assertLess(packet["elapsed_ms"], 2000)
        self.assertLess(packet["last_comparison_elapsed_ms"], 650)
        self.assertIs(packet["last_comparison"]["capture"]["full_text_changed"], False)
        self.assertIsNone(packet["last_comparison"]["process"]["last_exit"]["changed"])
        self.assertEqual(packet["interpretation"], "none")
        self.assertNotIn("completion", packet)
        self.assertNotIn("TEEREX_ALPHA", result.stdout)
        self.assertEqual(baseline.read_bytes(), original)

    def test_watch_text_change_keeps_target_running_and_does_not_repeat_text(self):
        target, gate = self.gated_fixture("", "print('PRIVATE_WATCH_CHANGED',flush=True)")
        baseline, before = self.baseline(target)
        sessions = self.rex_json("session", "ls", "--json")
        result = self.triggered_watch(target, baseline, gate)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["outcome"], "change_observed")
        self.assertEqual(packet["changed_fields"], ["capture.captured_text", "capture.full_text"])
        self.assertEqual(packet["availability_changed_fields"], [])
        self.assertEqual(packet["last_comparison"]["before_observation_id"], before["observation_id"])
        self.assertNotEqual(packet["last_comparison"]["after_observation_id"], before["observation_id"])
        self.assertNotIn("PRIVATE_WATCH_CHANGED", result.stdout)
        self.assertEqual(packet["cleanup_scope"], "collection_process_group_not_observed_terminal")
        after = json.loads(self.observe(target).stdout)
        self.assertIn("PRIVATE_WATCH_CHANGED", after["capture"]["content"])
        self.assertEqual(after["process"]["data"], before["process"]["data"])
        self.assertEqual(self.rex_json("session", "ls", "--json"), sessions)
        self.assertEqual(packet["interpretation"], "none")

    def test_watch_metadata_only_directory_change(self):
        later = self.root / "watch actual cwd"
        later.mkdir()
        report = "\x1b]7;file://localhost/retained-not-actual\x07"
        target, gate = self.gated_fixture(report, f"os.chdir({str(later)!r})")
        self.wait_for(target, "pwd", lambda v: v.get("pwd") is not None)
        baseline, before = self.baseline(target)
        result = self.triggered_watch(target, baseline, gate)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(set(packet["changed_fields"]), {"process.foreground", "process.child"})
        self.assertEqual(packet["availability_changed_fields"], [])
        self.assertIs(packet["last_comparison"]["reported_directory"]["changed"], False)
        self.assertIs(packet["last_comparison"]["capture"]["full_text_changed"], False)
        after = json.loads(self.observe(target).stdout)
        self.assertEqual(after["capture"]["content"], before["capture"]["content"])
        self.assertEqual(Path(after["process"]["data"]["foreground"]["cwd"]), later.resolve())
        self.assertEqual(after["reported_directory"], before["reported_directory"])

    def test_watch_done_report_does_not_mean_the_process_exited(self):
        working = "\x1b]7501;state=working:app=teerex-watch\x1b\\"
        done = "\x1b]7501;state=done:app=teerex-watch\x1b\\"
        target, gate = self.gated_fixture(working, f"sys.stdout.write({done!r});sys.stdout.flush()")
        self.wait_for(target, "program_status", lambda v: any(r.get("id") is None and r.get("state") == "working"
                                                             for r in v.get("records", [])))
        baseline, before = self.baseline(target)
        result = self.triggered_watch(target, baseline, gate)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["changed_fields"], ["program_status"])
        self.assertEqual(packet["availability_changed_fields"], [])
        self.assertEqual(packet["interpretation"], "none")
        after = json.loads(self.observe(target).stdout)
        self.assertEqual(after["capture"]["content"], before["capture"]["content"])
        self.assertEqual(after["program_status"]["data"]["records"][0]["state"], "done")
        self.assertEqual(after["process"]["data"], before["process"]["data"])
        self.assertIsNone(after["process"]["data"]["last_exit"])

    def test_watch_new_exit_evidence_is_an_availability_change(self):
        target, gate = self.gated_fixture("", "sys.exit(7)")
        baseline, before = self.baseline(target)
        self.assertIsNotNone(before["process"]["data"]["child"])
        self.assertIsNotNone(before["process"]["data"]["foreground"])
        self.assertIsNone(before["process"]["data"]["last_exit"])
        # Rex can lose process records before publishing last_exit. Establish the
        # exit fixture first: watch must still return on any first change.
        gate.touch()
        self.wait_for(target, "process", lambda v: (v.get("last_exit") or {}).get("exit_code") == 7
                      and v.get("child") is None and v.get("foreground") is None)
        result = subprocess.run(self.watch_command(target, baseline),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["outcome"], "change_observed")
        self.assertEqual(packet["changed_fields"], [])
        self.assertEqual(set(packet["availability_changed_fields"]),
                         {"process.foreground", "process.child", "process.last_exit"})
        self.assertEqual(packet["last_comparison"]["process"]["last_exit"], {
            "before_available": False, "after_available": True, "availability_changed": True, "changed": None})
        self.assertIn("process.last_exit", packet["unknown_fields"])
        self.assertEqual(packet["interpretation"], "none")
        self.assertNotIn("completion", packet)
        after = json.loads(self.observe(target).stdout)
        self.assertEqual(after["process"]["data"]["last_exit"], {"exit_code": 7})

    def test_watch_process_disappearance_and_exit_evidence_can_arrive_separately(self):
        baseline, before = self.baseline(self.a)
        raw = {"version": before["source"], "capture": {"content": before["capture"]["content"], "eof": True},
               "process": {"child": None, "foreground": None, "last_exit": None},
               "directory": before["reported_directory"]["data"], "status": before["program_status"]["data"]}
        first = json.dumps({"event": "sample", "data": raw}) + "\n"
        raw["process"]["last_exit"] = {"exit_code": 7}
        frames = first + '{"event":"collecting"}\n' + json.dumps({"event": "sample", "data": raw}) + "\n"
        directory = self.root / "split-exit-transport"
        directory.mkdir()
        shim = directory / "rex"
        shim.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({frames!r})\n", encoding="utf-8")
        shim.chmod(0o700)
        env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"])
        # Both frames are ready together. The first watch must stop at process
        # disappearance, not coalesce it with the later exit report. Starting
        # from that unavailable baseline must then wake on exit evidence alone.
        for exit_available in [False, True]:
            with self.subTest(exit_available=exit_available):
                if exit_available:
                    before["process"]["data"] = {"child": None, "foreground": None, "last_exit": None}
                    baseline.write_text(json.dumps(before), encoding="utf-8")
                result = subprocess.run(self.watch_command(self.a, baseline), env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                packet = json.loads(result.stdout)
                self.assertEqual(packet["outcome"], "change_observed")
                self.assertEqual(packet["observations_compared"], 2 if exit_available else 1)
                self.assertEqual(packet["changed_fields"], [])
                self.assertEqual(set(packet["availability_changed_fields"]),
                                 {"process.last_exit"} if exit_available else {"process.child", "process.foreground"})
                self.assertEqual(packet["last_comparison"]["process"]["last_exit"], {
                    "before_available": False, "after_available": exit_available,
                    "availability_changed": exit_available, "changed": None})
                self.assertIn("process.last_exit", packet["unknown_fields"])
                self.assertEqual(packet["interpretation"], "none")
                self.assertNotIn("completion", packet)

    def test_watch_changed_tail_outside_prefix_stays_unknown(self):
        target, gate = self.gated_fixture("stable prefix α\n" * 100,
                                         "print('UNOBSERVED_TAIL_CHANGED',flush=True)")
        baseline, before = self.baseline(target, "--max-bytes", "256")
        self.assertFalse(before["capture"]["complete"])
        result = self.triggered_watch(target, baseline, gate, timeout=800)
        self.assertEqual(result.returncode, 124, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["outcome"], "deadline_exceeded")
        self.assertEqual(packet["changed_fields"], [])
        self.assertIn("capture.full_text", packet["unknown_fields"])
        self.assertIs(packet["last_comparison"]["capture"]["captured_text_changed"], False)
        self.assertIsNone(packet["last_comparison"]["capture"]["full_text_changed"])
        self.assertEqual(packet["limits"]["max_encoded_content_bytes"], 256)
        full = self.observe(target, "--max-bytes", "65536")
        self.assertIn("UNOBSERVED_TAIL_CHANGED", json.loads(full.stdout)["capture"]["content"])
        self.assertEqual(packet["interpretation"], "none")

    def test_watch_status_predicate_matches_exact_new_report_not_completion(self):
        for record_id, state in [(None, "done"), ("root", "blocked"), ("new", "working")]:
            with self.subTest(record_id=record_id, state=state):
                prefix = "" if record_id is None else f"id={record_id}:"
                unrelated = "id=other:" if record_id is None else ""
                old = (f"\x1b]7501;{prefix}state={state}:msg=T0xEX1JFUE9SVA==\x1b\\"
                       if record_id != "new" else "")
                other = f"\x1b]7501;{unrelated}state={state}\x1b\\"
                fresh = f"\x1b]7501;{prefix}state={state}:kind=permission:msg=TkVXX1JFUE9SVA==\x1b\\"
                second_gate = self.root / f"status-second-{record_id}"
                action = (f"sys.stdout.write({other!r});sys.stdout.flush()\n"
                          f"while not os.path.exists({str(second_gate)!r}): time.sleep(.01)\n"
                          f"sys.stdout.write({fresh!r});sys.stdout.flush()")
                target, first_gate = self.gated_fixture(old, action)
                self.wait_for(target, "program_status", lambda v: (v["records"] == [] if record_id == "new"
                              else any(r.get("id") == record_id and r["state"] == state for r in v["records"])))
                baseline, before = self.baseline(target)
                # A retained match is not new evidence relative to the baseline.
                stale = subprocess.run(self.watch_command(target, baseline, timeout=250,
                                        status_state=state, status_id=record_id),
                                       capture_output=True, text=True, timeout=5)
                self.assertEqual(stale.returncode, 124, stale.stderr)
                self.assertIsNone(json.loads(stale.stdout)["matched_status_report"])
                command = self.watch_command(target, baseline, status_state=state, status_id=record_id)
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    time.sleep(.15)
                    first_gate.touch()
                    self.wait_for(target, "program_status", lambda v: any(
                        r.get("id") == ("other" if record_id is None else None) for r in v["records"]))
                    time.sleep(.15)
                    self.assertIsNone(process.poll(), "Unrelated record incorrectly satisfied the predicate")
                    second_gate.touch()
                    stdout, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, stderr)
                    packet = json.loads(stdout)
                    self.assertEqual(packet["outcome"], "status_report_matched")
                    self.assertEqual(packet["condition"], {
                        "record_id": record_id, "state": state,
                        "states": [state], "matched_state": state,
                        "requirement": "different_report_evidence_from_baseline"})
                    report = packet["matched_status_report"]
                    self.assertEqual((report["record_id"], report["state"]), (record_id, state))
                    self.assertTrue(report["updated_at"])
                    self.assertEqual(packet["interpretation"], "none")
                    self.assertNotIn("NEW_REPORT", stdout)
                    self.assertNotIn("completion", packet)
                    after = json.loads(self.observe(target).stdout)
                    self.assertEqual(after["process"]["data"], before["process"]["data"])
                    self.assertIsNone(after["process"]["data"]["last_exit"])
                    old_report = next((r for r in before["program_status"]["data"]["records"]
                                       if r["id"] == record_id), None)
                    if old_report is not None:
                        self.assertNotEqual(report["updated_at"], old_report["updated_at"])
                finally:
                    second_gate.touch()
                    if process.poll() is None:
                        process.terminate()
                        process.communicate(timeout=3)

    def test_watch_multiple_states_and_status_deadlines(self):
        for state, timeout in [("done", 60001), ("error", 86400000), ("done", None)]:
            with self.subTest(state=state, timeout=timeout):
                report = f"\x1b]7501;id=worker:state={state}\x1b\\"
                target, gate = self.gated_fixture("", f"sys.stdout.write({report!r});sys.stdout.flush()")
                baseline, _ = self.baseline(target)
                result = self.triggered_watch(target, baseline, gate, timeout=timeout,
                                              status_state=["done", "error"], status_id="worker")
                self.assertEqual(result.returncode, 0, result.stderr)
                packet = json.loads(result.stdout)
                self.assertEqual(packet["outcome"], "status_report_matched")
                self.assertEqual(packet["condition"]["states"], ["done", "error"])
                self.assertEqual(packet["condition"]["matched_state"], state)
                self.assertEqual(packet["matched_status_report"]["state"], state)
                self.assertEqual(packet["limits"]["timeout_ms"], timeout)

    def test_watch_no_deadline_cancellation_and_usage(self):
        baseline, _ = self.baseline(self.a)
        command = self.watch_command(self.a, baseline, timeout=None, status_state=["done", "error"])
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(.3)
            self.assertIsNone(process.poll())
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr)
            packet = json.loads(stdout)
            self.assertEqual(packet["outcome"], "cancel_requested")
            self.assertEqual(packet["cancellation_signal"], signal.SIGTERM)
            self.assertIsNone(packet["limits"]["timeout_ms"])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)
        missing = self.root / "unlimited-missing.sock"
        packet = json.loads(baseline.read_text())
        packet["target"]["server"] = "unix://" + str(missing)
        baseline.write_text(json.dumps(packet))
        failed = subprocess.run(self.watch_command(self.a, baseline, timeout=None,
                                status_state="done", socket=missing),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["outcome"], "observation_failed")
        for invalid in [command + ["--timeout-ms", "1000"], command + ["--no-deadline"],
                        command + ["--status-state", "error"],
                        self.watch_command(self.a, baseline, timeout=None),
                        self.watch_command(self.a, baseline, timeout=86400001, status_state="done")]:
            result = subprocess.run(invalid, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, "")

    def test_watch_target_source_transport_and_usage_fail_closed(self):
        baseline, before = self.baseline(self.a)
        mismatch = subprocess.run(self.watch_command(self.b, baseline), capture_output=True, text=True, timeout=5)
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("DifferentObservationTargets", mismatch.stderr)
        self.assertEqual(mismatch.stdout, "")
        other = copy.deepcopy(before)
        other["source"]["rex_version"] = "not-this-version"
        baseline.write_text(json.dumps(other), encoding="utf-8")
        mismatch = subprocess.run(self.watch_command(self.a, baseline), capture_output=True, text=True, timeout=5)
        self.assertEqual(mismatch.returncode, 1, mismatch.stderr)
        packet = json.loads(mismatch.stdout)
        self.assertEqual(packet["outcome"], "observation_failed")
        self.assertEqual(packet["failure_reason"], "DifferentObservationSources")
        self.assertIsNone(packet["last_comparison"])
        self.assertIsNone(packet["changed_fields"])
        self.assertEqual(packet["observations_compared"], 0)
        missing = self.root / "watch-missing.sock"
        before["target"]["server"] = "unix://" + str(missing)
        baseline.write_text(json.dumps(before), encoding="utf-8")
        for env in [None, dict(os.environ, PATH="/no-rex-available")]:
            with self.subTest(env=env is None):
                result = subprocess.run(self.watch_command(self.a, baseline, socket=missing), env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1, result.stderr)
                packet = json.loads(result.stdout)
                self.assertEqual(packet["outcome"], "observation_failed")
                self.assertEqual(packet["failure_reason"], "ObservationCommandFailed")
                self.assertIsNone(packet["last_comparison"])
                self.assertIsNone(packet["unknown_fields"])
                self.assertFalse(missing.exists())
        command = self.watch_command(self.a, baseline)
        for extra in [["--timeout-ms", "1000"], ["--max-bytes", "4096"], ["--unknown", "x"], ["--interval-ms"]]:
            with self.subTest(extra=extra):
                result = subprocess.run(command + extra, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
        for extra in [["--status-id", "child"], ["--status-state", "complete"],
                      ["--status-state", ""], ["--status-state", "done", "--status-id", ""],
                      ["--status-state", "done", "--status-state", "done"], ["--status-state"]]:
            with self.subTest(extra=extra):
                result = subprocess.run(command + extra, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
        for timeout, interval in [(99, 50), (60001, 50), (3000, 49), (3000, 5001), ("NaN", 50), (-1, 50)]:
            with self.subTest(timeout=timeout, interval=interval):
                result = subprocess.run(self.watch_command(self.a, baseline, timeout=timeout, interval=interval),
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_deadline_and_cancellation_stop_stalled_collection_not_target(self):
        baseline, before = self.baseline(self.a)
        for kind, stop in ((kind, stop) for kind in ["observe", "watch"]
                           for stop in [None, signal.SIGINT, signal.SIGTERM]):
            with self.subTest(kind=kind, stop=stop):
                directory = self.root / f"hung-transport-{kind}-{stop}"
                directory.mkdir()
                pids_path = directory / "owned.pids"
                fake = directory / "rex"
                fake.write_text(
                    f"#!{sys.executable}\nimport os,signal,time\n"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                    "os.close(1);os.close(2)\n"
                    "os.fork()\n"
                    f"with open({str(pids_path)!r},'a') as f: f.write(str(os.getpid())+'\\n')\n"
                    "time.sleep(60)\n", encoding="utf-8",
                )
                fake.chmod(0o700)
                env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"])
                timeout = 400 if stop is None else 3000
                command = (self.watch_command(self.a, baseline, timeout=timeout) if kind == "watch" else
                           [str(BIN), "observe", "--socket", str(self.socket), "--session", self.a[0],
                            "--block", self.a[1], "--timeout-ms", str(timeout)])
                started = time.monotonic()
                process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    if stop is not None:
                        for _ in range(200):
                            if pids_path.exists() and len(pids_path.read_text().split()) == 2:
                                break
                            if process.poll() is not None:
                                self.fail(process.communicate())
                            time.sleep(.01)
                        else:
                            self.fail("Stalled transport fixture did not start both processes")
                        process.send_signal(stop)
                    stdout, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 124 if stop is None else 128 + stop, stderr)
                    self.assertLess(time.monotonic() - started, 2)
                    if kind == "observe":
                        self.assertEqual(stdout, "")
                        self.assertIn("no complete observation emitted", stderr)
                    else:
                        packet = json.loads(stdout)
                        self.assertEqual(packet["outcome"], "deadline_exceeded" if stop is None else "cancel_requested")
                        self.assertEqual(packet["cancellation_signal"], stop)
                        self.assertTrue(packet["last_sample_interrupted"])
                        self.assertEqual(packet["observations_compared"], 0)
                        self.assertEqual(packet["collection_attempts"], 1)
                        for key in ["last_comparison", "changed_fields", "availability_changed_fields", "unknown_fields"]:
                            self.assertIsNone(packet[key])
                        self.assertIsNone(packet["failure_reason"])
                        self.assertLess(packet["elapsed_ms"], 2000)
                        self.assertIsNotNone(packet["last_collection_cleanup"]["group_sigkill"])
                        self.assertFalse(packet["all_descendants_verified_gone"])
                    pids = [int(pid) for pid in pids_path.read_text().split()]
                    self.assertEqual(len(pids), 2)
                    for _ in range(100):
                        live = [pid for pid in pids if (status := subprocess.run(
                            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True,
                        ).stdout.strip()) and not status.startswith("Z")]
                        if not live:
                            break
                        time.sleep(.02)
                    self.assertEqual(live, [], "Collection descendants still executing")
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.communicate(timeout=3)
                    if pids_path.exists():
                        for pid in map(int, pids_path.read_text().split()):
                            args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)],
                                                  capture_output=True, text=True).stdout
                            if str(fake) in args:
                                try:
                                    os.kill(pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
        after = json.loads(self.observe(self.a).stdout)
        self.assertEqual(after["process"]["data"], before["process"]["data"])
        self.assertEqual(after["capture"]["content"], before["capture"]["content"])

    def test_watch_fragmented_large_samples_and_broken_frames(self):
        baseline, before = self.baseline(self.long, "--max-bytes", "65536")
        directory = self.root / "fragmented-transport"
        directory.mkdir()
        shim = directory / "rex"
        shim.write_text(
            f"#!{sys.executable}\nimport os,subprocess,sys\n"
            f"p=subprocess.Popen([{self.rex!r},*sys.argv[1:]],stdout=subprocess.PIPE)\n"
            "while True:\n"
            "    chunk=os.read(p.stdout.fileno(),113)\n"
            "    if not chunk: break\n"
            "    os.write(1,chunk)\n"
            "sys.exit(p.wait())\n", encoding="utf-8",
        )
        shim.chmod(0o700)
        env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"])
        result = subprocess.run(self.watch_command(self.long, baseline, timeout=400), env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 124, result.stderr)
        packet = json.loads(result.stdout)
        self.assertGreaterEqual(packet["observations_compared"], 2)
        self.assertEqual(packet["changed_fields"], [])
        self.assertIs(packet["last_comparison"]["capture"]["full_text_changed"], False)
        self.assertNotIn("TEEREX_LONG", result.stdout)
        raw = {"version": before["source"], "capture": {"content": before["capture"]["content"], "eof": True},
               "process": before["process"]["data"], "directory": before["reported_directory"]["data"],
               "status": before["program_status"]["data"]}
        first = json.dumps({"event": "sample", "data": raw}).encode() + b"\n"
        for tail, failure in [(b'{"event":"collecting"}\n{"event":', "InvalidObservationFrame"),
                              (b'{"event":"collecting"}\n{"event":"sample","data":null}\n', "InvalidObservationFrame"),
                              (b'{"event":"collecting"}\n' + b"x" * (5 * 128 * 1024 + 321), "ObservationExceedsLimit"),
                              (b"", "ObservationCommandFailed")]:
            with self.subTest(failure=failure, size=len(tail)):
                data = directory / "frames"
                data.write_bytes(first + tail)
                shim.write_text(f"#!{sys.executable}\nimport sys\n"
                                f"sys.stdout.buffer.write(open({str(data)!r},'rb').read())\n",
                                encoding="utf-8")
                result = subprocess.run(self.watch_command(self.long, baseline), env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1, result.stderr)
                packet = json.loads(result.stdout)
                self.assertEqual(packet["outcome"], "observation_failed")
                self.assertEqual(packet["failure_reason"], failure)
                self.assertEqual(packet["observations_compared"], 1)
                self.assertEqual(packet["changed_fields"], [])
                self.assertIs(packet["last_comparison"]["capture"]["full_text_changed"], False)
                self.assertLessEqual(packet["last_comparison_elapsed_ms"], packet["elapsed_ms"])
                self.assertNotIn("TEEREX_LONG", result.stdout)

    def test_watch_poll_gap_cancel_and_later_failure_keep_last_comparison(self):
        baseline, before = self.baseline(self.a)
        for stop in [signal.SIGINT, signal.SIGTERM, None]:
            with self.subTest(stop=stop):
                gate = self.root / f"fail-transport-{stop}"
                directory = self.root / f"passing-transport-{stop}"
                directory.mkdir()
                shim = directory / "rex"
                fault = ("local original = rex.call; rex.call = function(...) "
                         f"local f = io.open({json.dumps(str(gate))}, 'r'); "
                         "if f then f:close(); error('CONTROLLED_QUERY_FAILURE') end; "
                         "return original(...) end\n")
                shim.write_text(
                    f"#!{sys.executable}\nimport os,sys\n"
                    "i=sys.argv.index('-e')+1\n"
                    f"sys.argv[i]={fault!r}+sys.argv[i]\n"
                    f"os.execv({self.rex!r},[{self.rex!r},*sys.argv[1:]])\n", encoding="utf-8",
                )
                shim.chmod(0o700)
                env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"])
                command = self.watch_command(self.a, baseline, timeout=6000, interval=5000 if stop else 50)
                process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    # A long poll gap exposes handlers incorrectly scoped to one collection.
                    time.sleep(1)
                    if stop is None:
                        gate.touch()
                    else:
                        process.send_signal(stop)
                    stdout, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 1 if stop is None else 128 + stop, stderr)
                    packet = json.loads(stdout)
                    self.assertEqual(packet["outcome"], "observation_failed" if stop is None else "cancel_requested")
                    self.assertEqual(packet["failure_reason"], "ObservationCommandFailed" if stop is None else None)
                    self.assertEqual(packet["cancellation_signal"], stop)
                    self.assertGreaterEqual(packet["observations_compared"], 1)
                    self.assertLess(packet["last_comparison_elapsed_ms"], packet["elapsed_ms"])
                    self.assertEqual(packet["last_comparison"]["before_observation_id"], before["observation_id"])
                    self.assertEqual(packet["changed_fields"], [])
                    self.assertEqual(packet["interpretation"], "none")
                    if stop is None:
                        self.assertIn("CONTROLLED_QUERY_FAILURE", stderr)
                        self.assertGreater(packet["collection_attempts"], packet["observations_compared"])
                    else:
                        self.assertFalse(packet["last_sample_interrupted"])
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
