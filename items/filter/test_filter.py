"""Public filter CLI checks; no Rex executable is needed for these synthetic files."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex"))


def observation():
    return {
        "schema_version": 1, "observation_id": "first",
        "observation_started_at_unix_ms": 20, "observed_at_unix_ms": 25,
        "atomic_snapshot": False,
        "target": {"server": "unix:///tmp/not-contacted.sock",
                   "session_id": "session:12345678-1234-1234-1234-123456789abc",
                   "block_id": "block:abcdef12-1234-1234-1234-123456789abc"},
        "source": {"rex_version": "0.1.0-preview.16", "platform": "darwin/arm64", "api_revision": 13},
        "capture": {"scope": "screen_and_scrollback", "portion": "prefix", "max_bytes": 4096,
                    "complete": True, "content": "building α\n"},
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


class FilterTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tx-filter-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def invoke(self, args):
        return subprocess.run([str(BIN), "filter", *args], capture_output=True, text=True, timeout=10,
                              env=dict(os.environ, PATH="/no-rex-or-other-executables"))

    def paths(self, packets):
        paths = []
        for index, packet in enumerate(packets):
            path = self.root / f"{index}.json"
            path.write_text(json.dumps(packet, sort_keys=index % 2 == 0), encoding="utf-8")
            paths.append(path)
        return paths

    def filtered(self, packets):
        paths = self.paths(packets)
        original = [path.read_bytes() for path in paths]
        result = self.invoke([argument for path in paths for argument in ["--sample", str(path)]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([path.read_bytes() for path in paths], original)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(events), len(packets) + 1)
        self.assertEqual(events[-1]["kind"], "rex_evidence_filter_summary")
        self.assertEqual(events[-1]["outcome"], "processed")
        self.assertEqual(events[-1]["input_bytes"], sum(map(len, original)))
        self.assertTrue(all(event["interpretation"] == "none" for event in events))
        return events, result

    def test_repeats_keep_ids_times_unknown_comparisons_and_final_checkpoint(self):
        packets = [observation() for _ in range(4)]
        for index, packet in enumerate(packets):
            packet.update(observation_id=f"sample-{index}", observed_at_unix_ms=10 - index)
        packets[1]["program_status"]["data"]["records"].reverse()
        events, _ = self.filtered(packets)
        self.assertEqual(events[0]["reason"], "baseline")
        self.assertIsNone(events[0]["comparison"])
        for index in [1, 2]:
            self.assertEqual(events[index]["kind"], "rex_evidence_filter_repeat")
            self.assertNotIn("observation", events[index])
            self.assertEqual(events[index]["evidence_sample_index"], 1)
            self.assertEqual(events[index]["observation_id"], f"sample-{index}")
            self.assertEqual(events[index]["observed_at_unix_ms"], 10 - index)
            comparison = events[index]["comparison"]
            self.assertEqual(comparison["before_observation_id"], f"sample-{index-1}")
            self.assertIsNone(comparison["process"]["last_exit"]["changed"])
            self.assertFalse(comparison["capture"]["full_text_changed"])
        self.assertEqual(events[3]["reason"], "latest_checkpoint")
        self.assertEqual(events[3]["observation"]["observation_id"], "sample-3")
        self.assertEqual(events[3]["observation"]["capture"], packets[3]["capture"])
        self.assertEqual(events[-1]["observation_payloads_emitted"], 2)
        self.assertEqual(events[-1]["observation_payloads_omitted"], 2)
        self.assertEqual(events[-1]["repeated_evidence_samples"], 3)
        self.assertFalse(events[-1]["persistent_cache"])

    def test_partial_and_absent_evidence_remains_unknown_in_every_delta(self):
        packet = observation()
        packet["capture"].update(complete=False, max_bytes=256)
        for field in ["process", "reported_directory", "program_status"]:
            del packet[field]
        packets = [copy.deepcopy(packet) for _ in range(4)]
        packets[-1]["capture"]["max_bytes"] = 257
        events, _ = self.filtered(packets)
        for event in events[1:-1]:
            self.assertIsNone(event["comparison"]["capture"]["full_text_changed"])
            self.assertIsNone(event["comparison"]["program_status"]["changed"])
            self.assertIsNone(event["comparison"]["process"]["foreground"]["changed"])
        self.assertEqual(events[-2]["reason"], "evidence_changed")
        self.assertIsNone(events[-2]["comparison"]["capture"]["captured_text_changed"])
        self.assertEqual(events[1]["kind"], "rex_evidence_filter_repeat")

    def test_no_text_process_status_or_provenance_changes_are_hidden(self):
        changes = [
            (("capture", "content"), "ERROR: failure\n"),
            (("capture", "content"), "Delete everything? [y/N] "),
            (("capture", "content"), "spinner | elapsed 1s"),
            (("capture", "complete"), False), (("capture", "max_bytes"), 8192),
            (("process", "data", "foreground", "pid"), 48),
            (("process", "data", "foreground", "cwd"), "/three"),
            (("process", "data", "child", "name"), "new shell"),
            (("process", "data", "last_exit"), {"exit_code": 7}),
            (("process", "data", "foreground"), None),
            (("reported_directory", "data", "pwd"), "file://localhost/other"),
            (("reported_directory", "reported_at"), "server-later"),
            (("program_status", "data", "records", 0, "state"), "done"),
            (("program_status", "data", "records", 0, "updated_at"), "server-later"),
            (("program_status", "data", "records", 0, "progress"), None),
            (("program_status", "data", "records", 1, "msg"), "allow access?"),
            (("program_status",), None), (("atomic_snapshot",), True),
        ]
        for path, value in changes:
            with self.subTest(path=path, value=value):
                before = observation()
                after = copy.deepcopy(before)
                node = after
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                events, _ = self.filtered([before, after, before])
                self.assertEqual([event["reason"] for event in events[:-1]],
                                 ["baseline", "evidence_changed", "evidence_changed"])
                self.assertEqual(events[-1]["observation_payloads_omitted"], 0)
                self.assertNotIn("completion", events[-1])

    def test_adjacent_comparisons_match_public_compare_even_after_omission(self):
        packets = [observation() for _ in range(4)]
        packets[2]["capture"]["content"] = packets[3]["capture"]["content"] = "changed β\n"
        events, _ = self.filtered(packets)
        for index in range(1, len(packets)):
            result = subprocess.run([str(BIN), "compare", "--before", str(self.root / f"{index-1}.json"),
                                     "--after", str(self.root / f"{index}.json")], capture_output=True,
                                    text=True, timeout=5, env=dict(os.environ, PATH="/no-rex"))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(events[index]["comparison"], json.loads(result.stdout))

    def test_schema_target_source_and_provenance_errors_never_finish_successfully(self):
        changes = [
            (("target", "block_id"), "block:99999999-1234-1234-1234-123456789abc"),
            (("target", "server"), "unix:///tmp/other.sock"),
            (("source", "rex_version"), "changed-version"),
            (("source", "api_revision"), 14), (("schema_version",), 2),
            (("reported_directory", "freshness"), "fresh"),
            (("capture", "portion"), "tail"), (("capture", "content"), "x" * 4096),
            (("program_status", "data", "records", 1, "id"), None),
            (("unexpected_field",), "could be meaningful"),
            (("capture", "unexpected_field"), True),
        ]
        for path, value in changes:
            with self.subTest(path=path):
                invalid = observation()
                node = invalid
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                paths = self.paths([observation(), observation(), invalid])
                result = self.invoke([arg for path in paths for arg in ["--sample", str(path)]])
                self.assertEqual(result.returncode, 1, result.stderr)
                events = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(len(events), 2)
                self.assertFalse(any(event["kind"] == "rex_evidence_filter_summary" for event in events))

    def test_argument_and_sample_count_bounds(self):
        for args in [[], ["--sample"], ["--sample", "x"], ["--unknown", "x", "--sample", "y"],
                     ["--sample", "", "--sample", "y"], ["--sample", "x"] * 129]:
            with self.subTest(args=args[:6]):
                result = self.invoke(args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
        result = self.invoke(["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NOT redacted", result.stdout)

    def test_regular_files_and_malformed_or_oversized_files(self):
        first = self.paths([observation()])[0]
        invalid = self.root / "bad"
        duplicate_key = first.read_bytes()[:-1] + b',"schema_version":1}'
        for data in [b"{}", b"{", b"x" * (1024 * 1024 + 1), duplicate_key]:
            invalid.write_bytes(data)
            result = self.invoke(["--sample", str(first), "--sample", str(invalid)])
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("rex_evidence_filter_summary", result.stdout)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for path in [self.root, self.root / "missing", fifo]:
            result = self.invoke(["--sample", str(first), "--sample", str(path)])
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("rex_evidence_filter_summary", result.stdout)

    def test_exact_file_and_total_byte_bounds(self):
        path = self.paths([observation()])[0]
        content = path.read_bytes()
        path.write_bytes(content + b" " * (1024 * 1024 - len(content)))
        result = self.invoke(["--sample", str(path)] * 16)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["input_bytes"], 16 * 1024 * 1024)
        result = self.invoke(["--sample", str(path)] * 17)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("FilterInputExceedsLimit", result.stderr)
        self.assertNotIn("rex_evidence_filter_summary", result.stdout)

    def test_large_repeated_prefix_reduces_bytes_without_dropping_any_comparison(self):
        packet = observation()
        packet["capture"].update(content="x" * 60000, max_bytes=65536, complete=False)
        packets = [copy.deepcopy(packet) for _ in range(128)]
        for index, sample in enumerate(packets):
            sample["observation_id"] = f"sample-{index}"
        events, result = self.filtered(packets)
        self.assertEqual(events[-1]["observation_payloads_emitted"], 2)
        self.assertEqual(events[-1]["observation_payloads_omitted"], 126)
        self.assertEqual(events[-1]["repeated_evidence_samples"], 127)
        for event in events[1:-1]:
            self.assertIsNone(event["comparison"]["capture"]["full_text_changed"])
        self.assertLess(len(result.stdout.encode()), events[-1]["input_bytes"] // 20)
        self.assertEqual(events[-2]["observation"]["capture"]["content"], "x" * 60000)


if __name__ == "__main__":
    unittest.main()
