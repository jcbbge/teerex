"""Public offline maneuver-check contract; synthetic files, no Rex or live input."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex"))


class ManeuverTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="tmaneuver-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.definition_path = self.root / "definition.json"
        self.observation_path = self.root / "observation.json"
        self.socket = self.root / "not-contacted.sock"
        self.target = {
            "server": "unix://" + str(self.socket),
            "session_id": "session:12345678-1234-1234-1234-123456789abc",
            "block_id": "block:abcdef12-1234-1234-1234-123456789abc",
        }
        self.definition = {
            "schema_version": 1, "kind": "rex_maneuver_start", "id": "release-inspect-only",
            "provenance": {"kind": "manual", "note": "Synthetic authored expectation, not a recorded success"},
            "compatibility": {"rex_version": "0.1.0-preview.16", "platform": "darwin/arm64", "api_revision": 13},
            "starting_state": {"capture_content": 'Release α😀\nCandidate "one"\nInspect only\n',
                               "foreground": {"name": "release-fixture", "cwd": "/private/release"}},
            "stop_before": "Stop before publishing; this text grants no approval.",
        }
        self.observation = {
            "schema_version": 1, "observation_id": "a" * 32,
            "observation_started_at_unix_ms": 20, "observed_at_unix_ms": 25,
            "atomic_snapshot": False, "target": self.target,
            "source": copy.deepcopy(self.definition["compatibility"]),
            "capture": {"scope": "screen_and_scrollback", "portion": "prefix", "max_bytes": 256,
                        "complete": True, "content": self.definition["starting_state"]["capture_content"]},
            "process": {"method": "com.superlogical.terminal.process", "basis": "rex_observation",
                        "freshness": "unknown", "data": {
                            "child": {"pid": 31, "name": "shell", "cwd": "/different-child"},
                            "foreground": {"pid": 47, "name": "release-fixture", "cwd": "/private/release"},
                            "last_exit": {"exit_code": 7}}},
            "reported_directory": {"method": "com.superlogical.terminal.pwd", "basis": "terminal_report",
                                   "freshness": "unknown", "data": {"pwd": "file:///wrong-report"}},
            "program_status": {"method": "com.superlogical.terminal.program_status", "basis": "program_reports",
                               "freshness": "unknown", "data": {"records": [
                                   {"id": None, "state": "done", "updated_at": "old-server-clock"}]}},
        }

    def command(self):
        return [str(BIN), "maneuver-check", "--definition", str(self.definition_path),
                "--observation", str(self.observation_path), "--socket", str(self.socket),
                "--session", self.target["session_id"], "--block", self.target["block_id"]]

    def invoke(self):
        self.definition_path.write_text(json.dumps(self.definition, ensure_ascii=False), encoding="utf-8")
        self.observation_path.write_text(json.dumps(self.observation, ensure_ascii=False), encoding="utf-8")
        return self.execute(self.command())

    @staticmethod
    def execute(command):
        return subprocess.run(command, env=dict(os.environ, PATH="/no-rex-or-other-executables",
                              REX_SERVER="unix:///poison.sock", REX_SESSION="session:poison", REX_BLOCK="block:poison"),
                              capture_output=True, text=True, timeout=5)

    def checked(self, outcome, code):
        result = self.invoke()
        self.assertEqual(result.returncode, code, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["outcome"], outcome)
        self.assertEqual(packet["kind"], "maneuver_start_check")
        self.assertFalse(packet["input_sent"])
        self.assertFalse(packet["approval_granted"])
        self.assertEqual(packet["execution"], "not_implemented")
        self.assertEqual(packet["freshness"], "unknown")
        self.assertFalse(packet["atomic_snapshot"])
        self.assertEqual(packet["authored_text_authority"], "unauthenticated_data")
        self.assertFalse(self.socket.exists())
        return packet, {c["field"]: c for c in packet["checks"]}

    def test_match_attributes_exact_files_without_inventing_permission(self):
        packet, checks = self.checked("matched_evidence", 0)
        self.assertTrue(all(c["state"] == "matched" for c in checks.values()))
        self.assertEqual(packet["target"], self.target)
        self.assertEqual(packet["source"], self.definition["compatibility"])
        self.assertEqual(packet["definition_provenance"], self.definition["provenance"])
        self.assertEqual(packet["stop_before"], self.definition["stop_before"])
        for kind, path in [("definition", self.definition_path), ("observation", self.observation_path)]:
            self.assertEqual(packet[kind + "_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(self.definition, json.loads(self.definition_path.read_bytes()))
        self.assertEqual(self.observation, json.loads(self.observation_path.read_bytes()))
        self.assertNotIn("capture", packet)
        self.assertNotIn("exit_code", packet)
        self.assertNotIn("/private/release", json.dumps(packet))

    def test_every_selected_field_is_exact_not_substring_normalized_or_child(self):
        mutations = [
            ("source.rex_version", ("source", "rex_version"), "0.1.0-preview.17"),
            ("source.platform", ("source", "platform"), "darwin/amd64"),
            ("capture.content", ("capture", "content"), self.observation["capture"]["content"] + "Publish now?\n"),
            ("capture.content", ("capture", "content"), self.observation["capture"]["content"].replace("one", "two")),
            ("capture.content", ("capture", "content"), self.observation["capture"]["content"].replace("\n", "\r\n")),
            ("process.foreground.name", ("process", "data", "foreground", "name"), "release-fixture-helper"),
            ("process.foreground.cwd", ("process", "data", "foreground", "cwd"), "/private/release/../release"),
        ]
        original = copy.deepcopy(self.observation)
        for field, path, value in mutations:
            with self.subTest(field=field, value=value):
                self.observation = copy.deepcopy(original)
                node = self.observation
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                _, checks = self.checked("mismatch", 3)
                self.assertEqual(checks[field]["state"], "mismatch")

    def test_partial_text_is_unknown_even_with_equal_or_different_prefix(self):
        self.observation["capture"]["complete"] = False
        for content in [self.observation["capture"]["content"], "different prefix", ""]:
            with self.subTest(content=content):
                self.observation["capture"]["content"] = content
                _, checks = self.checked("unknown", 4)
                self.assertEqual(checks["capture.content"]["state"], "unknown")
        self.observation["source"]["rex_version"] = "incompatible"
        _, checks = self.checked("mismatch", 3)
        self.assertEqual(checks["capture.content"]["state"], "unknown")

    def test_missing_foreground_or_cwd_does_not_fall_back_to_reports(self):
        original = copy.deepcopy(self.observation)
        for mode in ["missing-process", "null-process", "null-foreground", "null-cwd", "missing-cwd"]:
            with self.subTest(mode=mode):
                self.observation = copy.deepcopy(original)
                if mode == "missing-process":
                    del self.observation["process"]
                elif mode == "null-process":
                    self.observation["process"] = None
                elif mode == "null-foreground":
                    self.observation["process"]["data"]["foreground"] = None
                elif mode == "null-cwd":
                    self.observation["process"]["data"]["foreground"]["cwd"] = None
                else:
                    del self.observation["process"]["data"]["foreground"]["cwd"]
                _, checks = self.checked("unknown", 4)
                self.assertEqual(checks["process.foreground.cwd"]["state"], "unknown")

    def test_old_times_new_pid_and_done_or_permission_reports_grant_nothing(self):
        self.observation["observation_started_at_unix_ms"] = 100
        self.observation["observed_at_unix_ms"] = -100
        self.observation["process"]["data"]["foreground"]["pid"] = 999
        self.observation["program_status"]["data"]["records"][0].update(state="blocked", kind="permission")
        packet, _ = self.checked("matched_evidence", 0)
        self.assertEqual(packet["observed_at_unix_ms"], -100)
        self.assertEqual(packet["recognition_scope"], "saved_observation_start_state")

    def test_wrong_explicit_target_rejected_without_a_connection(self):
        self.invoke()
        for option, value in [("--socket", "/different.sock"),
                              ("--session", "session:00000000-1234-1234-1234-123456789abc"),
                              ("--block", "block:00000000-1234-1234-1234-123456789abc")]:
            with self.subTest(option=option):
                command = self.command()
                command[command.index(option) + 1] = value
                result = self.execute(command)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("ObservationTargetMismatch", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_full_observation_provenance_and_unused_metadata_are_validated(self):
        mutations = [
            (("schema_version",), 2), (("source", "api_revision"), 14), (("atomic_snapshot",), True),
            (("capture", "scope"), "viewport"), (("capture", "portion"), "tail"),
            (("capture", "max_bytes"), 255), (("capture", "complete"), "true"),
            (("process", "basis"), "inferred"), (("process", "data", "foreground", "pid"), 0),
            (("reported_directory", "method"), "other.method"), (("reported_directory", "data", "pwd"), 7),
            (("program_status", "freshness"), "fresh"),
            (("program_status", "data", "records"), [{"state": "done", "updated_at": "t"}] * 2),
            (("program_status", "data", "records"), [{"id": "child", "state": "done", "updated_at": "t"}] * 2),
            (("program_status", "data", "records"), [{"state": "done", "updated_at": "t", "progress": False}]),
        ]
        original = copy.deepcopy(self.observation)
        for path, value in mutations:
            with self.subTest(path=path):
                self.observation = copy.deepcopy(original)
                node = self.observation
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                result = self.invoke()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_definition_has_no_actions_and_requires_manual_provenance_and_stop(self):
        original = copy.deepcopy(self.definition)
        mutations = [(("input",), "publish\n"), (("starting_state", "argv"), ["/bin/true"]),
                     (("provenance", "kind"), "learned"), (("provenance", "note"), ""),
                     (("stop_before",), ""), (("kind",), "macro"), (("schema_version",), 2),
                     (("compatibility", "api_revision"), 14), (("starting_state", "capture_content"), ""),
                     (("starting_state", "foreground", "cwd"), "relative")]
        for path, value in mutations:
            with self.subTest(path=path):
                self.definition = copy.deepcopy(original)
                node = self.definition
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                result = self.invoke()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_encoded_capture_budget_and_file_bounds(self):
        content = '"' * 127  # 256 JSON-encoded bytes, including quotes.
        self.definition["starting_state"]["capture_content"] = content
        self.observation["capture"]["content"] = content
        self.checked("matched_evidence", 0)
        self.observation["capture"]["content"] += "x"
        result = self.invoke()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.observation["capture"]["content"] = content
        for path, limit in [(self.definition_path, 128 * 1024), (self.observation_path, 1024 * 1024)]:
            with self.subTest(path=path):
                self.invoke()
                original = path.read_bytes()
                path.write_bytes(original + b" " * (limit - len(original)))
                result = self.execute(self.command())
                self.assertEqual(result.returncode, 0, result.stderr)
                with path.open("ab") as file:
                    file.write(b" ")
                result = self.execute(self.command())
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
        self.definition["starting_state"]["capture_content"] = "x" * 65534
        self.observation["capture"].update(content="x" * 65534, max_bytes=65536)
        self.checked("matched_evidence", 0)
        self.definition["starting_state"]["capture_content"] += "x"
        result = self.invoke()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("InvalidManeuverDefinition", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_help_usage_missing_files_and_invalid_json(self):
        result = self.execute([str(BIN), "maneuver-check", "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("never contact Rex", result.stdout)
        self.invoke()
        good = self.command()
        for args in [[], good[2:] + ["--block", self.target["block_id"]], good[2:-1],
                     good[2:] + ["--input", "publish"], good[2:] + ["--help"],
                     good[2:6], ["--socket", "relative"], good[2:] + ["--definition", ""]]:
            with self.subTest(args=args):
                result = self.execute([str(BIN), "maneuver-check", *args])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
        for payload in [b"{", b"null", b"[]", b"{}", b'\xff']:
            self.observation_path.write_bytes(payload)
            result = self.execute(good)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
        self.observation_path.unlink()
        result = self.execute(good)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
