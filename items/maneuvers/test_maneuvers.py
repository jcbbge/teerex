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
            (("schema_version",), 2), (("source", "api_revision"), 14),
            (("source", "api_revision"), 10), (("atomic_snapshot",), True),
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


class LibraryTest(unittest.TestCase):
    """Synthetic exact-state domain, not a discovered user workflow or input trace."""

    execute = staticmethod(ManeuverTest.execute)

    def setUp(self):
        ManeuverTest.setUp(self)
        first = copy.deepcopy(self.definition)
        second = copy.deepcopy(first)
        first["id"], second["id"] = "state-one", "state-two"
        second["starting_state"]["capture_content"] = "Distinct synthetic state two β\n"
        self.library = {"schema_version": 1, "kind": "rex_maneuver_library", "id": "synthetic-domain",
                        "definitions": [first, second], "transitions": [{"from": "state-one", "to": "state-two"}]}
        self.library_path = self.root / "library.json"
        self.before_path = self.root / "before.json"
        self.before = copy.deepcopy(self.observation)
        self.observation["observation_id"] = "b" * 32
        self.observation["capture"]["content"] = second["starting_state"]["capture_content"]

    def command(self, *, catalog=False, pair=False):
        command = [str(BIN), "maneuver-check", "--library", str(self.library_path)]
        if catalog:
            return command + ["--list"]
        command += ["--observation", str(self.observation_path), "--socket", str(self.socket),
                    "--session", self.target["session_id"], "--block", self.target["block_id"]]
        return command + (["--before", str(self.before_path)] if pair else [])

    def invoke(self, **options):
        self.library_path.write_text(json.dumps(self.library, ensure_ascii=False), encoding="utf-8")
        self.observation_path.write_text(json.dumps(self.observation, ensure_ascii=False), encoding="utf-8")
        self.before_path.write_text(json.dumps(self.before, ensure_ascii=False), encoding="utf-8")
        before = {p: p.read_bytes() for p in [self.library_path, self.observation_path, self.before_path]}
        result = self.execute(self.command(**options))
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))
        self.assertFalse(self.socket.exists())
        return result

    def checked(self, code, **options):
        result = self.invoke(**options)
        self.assertEqual(result.returncode, code, result.stderr)
        packet = json.loads(result.stdout)
        self.assertFalse(packet["boundaries"]["input_sent"])
        self.assertFalse(packet["boundaries"]["approval_granted"])
        self.assertEqual(packet["boundaries"]["freshness"], "unknown")
        self.assertEqual(packet["boundaries"]["authored_text_authority"], "unauthenticated_data")
        self.assertNotIn("/private/release", result.stdout)
        self.assertNotIn("capture_content", result.stdout)
        self.assertEqual(packet["library_sha256"], hashlib.sha256(self.library_path.read_bytes()).hexdigest())
        return packet

    def test_catalog_is_validated_metadata_not_executable_or_capture_content(self):
        packet = self.checked(0, catalog=True)
        self.assertEqual(packet["kind"], "maneuver_library_catalog")
        self.assertEqual([d["id"] for d in packet["definitions"]], ["state-one", "state-two"])
        self.assertEqual(packet["transitions"], [{"from": "state-one", "to": "state-two"}])
        self.assertEqual(packet["definitions"][0]["stop_before"], self.definition["stop_before"])
        self.observation_path.unlink()
        self.before_path.unlink()
        self.assertEqual(self.execute(self.command(catalog=True)).returncode, 0)

    def test_unique_candidate_and_no_match_are_distinct(self):
        packet = self.checked(0)
        self.assertEqual(packet["recognition"]["selected_definition_id"], "state-two")
        self.assertEqual(packet["recognition"]["matched_definition_ids"], ["state-two"])
        self.assertEqual(packet["recognition"]["unknown_definition_ids"], [])
        self.assertEqual(packet["observation"]["file_sha256"], hashlib.sha256(self.observation_path.read_bytes()).hexdigest())
        self.observation["capture"]["content"] += "extra prompt"
        packet = self.checked(3)
        self.assertEqual(packet["recognition"]["outcome"], "mismatch")
        self.assertIsNone(packet["recognition"]["selected_definition_id"])

    def test_overlapping_definitions_are_ambiguous_not_first_match(self):
        self.library["definitions"][0]["starting_state"] = copy.deepcopy(self.library["definitions"][1]["starting_state"])
        for _ in range(2):
            packet = self.checked(5)
            self.assertEqual(packet["recognition"]["outcome"], "ambiguous")
            self.assertEqual(set(packet["recognition"]["matched_definition_ids"]), {"state-one", "state-two"})
            self.assertIsNone(packet["recognition"]["selected_definition_id"])
            self.library["definitions"].reverse()

    def test_unknown_candidates_are_not_rejected_by_an_unrelated_mismatch(self):
        self.observation["capture"]["complete"] = False
        self.library["definitions"][0]["compatibility"]["rex_version"] = "different-version"
        self.library["transitions"] = []
        packet = self.checked(4)
        self.assertEqual(packet["recognition"]["outcome"], "unknown")
        self.assertEqual(packet["recognition"]["unknown_definition_ids"], ["state-two"])
        self.assertEqual(packet["recognition"]["definitions"][0]["outcome"], "mismatch")
        self.assertIsNone(packet["recognition"]["selected_definition_id"])

    def test_directed_endpoints_do_not_prove_chronology_or_process_continuity(self):
        self.before["observed_at_unix_ms"] = 1000
        self.observation["observed_at_unix_ms"] = -1000
        self.observation["process"]["data"]["foreground"]["pid"] = 999
        packet = self.checked(0, pair=True)
        self.assertEqual(packet["outcome"], "declared_edge_evidence")
        self.assertEqual(packet["selected_edge"], {"from": "state-one", "to": "state-two"})
        self.assertTrue(packet["declared_edge_present"])
        self.assertEqual(packet["sample_order"], "caller_supplied")
        self.assertEqual(packet["process_continuity"], "not_verified")
        self.assertEqual(packet["intermediate_states"], "not_observed")
        self.before, self.observation = self.observation, self.before
        packet = self.checked(3, pair=True)
        self.assertEqual(packet["reason"], "undeclared_endpoint_relation")
        self.assertFalse(packet["declared_edge_present"])
        self.assertEqual(packet["selected_edge"], {"from": "state-two", "to": "state-one"})

    def test_missing_relation_reused_identity_and_incomplete_endpoints(self):
        self.library["transitions"] = []
        self.assertEqual(self.checked(3, pair=True)["reason"], "undeclared_endpoint_relation")
        self.library["transitions"] = [{"from": "state-one", "to": "state-two"}]
        self.observation["observation_id"] = self.before["observation_id"]
        self.assertEqual(self.checked(4, pair=True)["reason"], "reused_observation_identity")
        self.observation["capture"]["complete"] = False
        packet = self.checked(4, pair=True)
        self.assertIsNone(packet["selected_edge"])
        self.before["capture"]["content"] = "not a known state"
        self.assertEqual(self.checked(3, pair=True)["reason"], "unrecognized_endpoint")

    def test_ambiguous_endpoint_does_not_select_a_convenient_declared_edge(self):
        alias = copy.deepcopy(self.library["definitions"][0])
        alias["id"] = "alias"
        self.library["definitions"].append(alias)
        packet = self.checked(5, pair=True)
        self.assertEqual(packet["reason"], "ambiguous_endpoint")
        self.assertIsNone(packet["selected_edge"])

    def test_invalid_library_and_relations_fail_before_any_success_json(self):
        original = copy.deepcopy(self.library)
        mutations = [
            (("input",), "publish\n"), (("kind",), "macro_library"), (("schema_version",), 2),
            (("id",), ""), (("definitions",), []),
            (("definitions",), [self.library["definitions"][0]] * 2),
            (("transitions",), [{"from": "state-one", "to": "missing"}]),
            (("transitions",), [{"from": "state-one", "to": "state-one"}]),
            (("transitions",), [{"from": "state-one", "to": "state-two"}] * 2),
            (("transitions",), [{"from": "state-one", "to": "state-two", "argv": ["/bin/true"]}]),
            (("definitions", 1, "compatibility", "api_revision"), 10),
            (("definitions", 1, "compatibility", "rex_version"), "other"),
            (("definitions", 1, "provenance", "kind"), "learned"),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.library = copy.deepcopy(original)
                node = self.library
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                result = self.invoke(catalog=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_both_packets_use_full_validator_and_api13_target_boundary(self):
        for side in ["before", "observation"]:
            original = copy.deepcopy(getattr(self, side))
            mutations = [(("source", "api_revision"), 10), (("target", "server"), "unix:///different.sock"),
                         (("reported_directory", "freshness"), "fresh"),
                         (("program_status", "data", "records"), [{"state": "done", "updated_at": "t"}] * 2)]
            for path, value in mutations:
                with self.subTest(side=side, path=path):
                    setattr(self, side, copy.deepcopy(original))
                    node = getattr(self, side)
                    for key in path[:-1]:
                        node = node[key]
                    node[path[-1]] = value
                    result = self.invoke(pair=True)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, "")
            setattr(self, side, original)

    def test_library_count_file_and_endpoint_size_bounds(self):
        first = self.library["definitions"][0]
        self.library["definitions"] = [dict(copy.deepcopy(first), id=f"d{i}") for i in range(16)]
        self.library["transitions"] = [{"from": f"d{i}", "to": f"d{j}"} for i in range(16) for j in range(16) if i != j][:64]
        self.checked(0, catalog=True)
        self.library["transitions"].append({"from": "d15", "to": "d0"})
        self.assertEqual(self.invoke(catalog=True).returncode, 1)
        self.library["transitions"] = []
        self.library["definitions"].append(dict(copy.deepcopy(first), id="d16"))
        self.assertEqual(self.invoke(catalog=True).returncode, 1)
        self.library["definitions"].pop()
        self.invoke(catalog=True)
        data = self.library_path.read_bytes()
        self.library_path.write_bytes(data + b" " * (1024 * 1024 - len(data)))
        self.assertEqual(self.execute(self.command(catalog=True)).returncode, 0)
        with self.library_path.open("ab") as file:
            file.write(b" ")
        result = self.execute(self.command(catalog=True))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.invoke(pair=True)
        self.before_path.write_bytes(b" " * (1024 * 1024 + 1))
        result = self.execute(self.command(pair=True))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")

    def test_library_modes_reject_ambiguous_usage(self):
        self.invoke()
        good = self.command()[2:]
        for args in [good + ["--list"], ["--list"], good + ["--definition", str(self.definition_path)],
                     good + ["--library", str(self.library_path)], self.command(catalog=True)[2:] + ["--list"],
                     self.command(pair=True)[2:] + ["--before", str(self.before_path)]]:
            with self.subTest(args=args):
                result = self.execute([str(BIN), "maneuver-check", *args])
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
