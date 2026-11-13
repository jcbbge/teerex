"""Acceptance evidence cannot promote inferred or stale results."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import execute
from fail_fixture import ASSERTION, expected
from records import ROWS, RUBRIC, readiness, sha, validate, verdict, input_snapshot, inputs_hash, contract
from baseline import summarize


def record(commit="a" * 40):
    value = dict(schema_version=1, kind="cartridge_readiness", id="observe", platform="x86_64-linux",
        rubric=RUBRIC, rubric_sha256="b" * 64, source_commit=commit, source_tree_dirty=False,
        covered_paths=["input.zig"], payload_sha256="c" * 64, runs=[])
    for n in range(3):
        value["runs"].append(dict(executor="local:hive:independent", independent_executor=True,
            server_instance_sha256=str(n) * 64, rex=dict(api_revision=13, sha256="d" * 64, version="fixture", commit="fixture"),
            os="fixture", arch="fixture", started_at="fixture", finished_at="fixture",
            rows={key: {"pass": True, "detail": "fixture"} for key in ROWS}))
    value.update(covered_files_sha256={"input.zig": "e" * 64}, covered_inputs_sha256=inputs_hash({"input.zig": "e" * 64}))
    value.update(verdict(value))
    return value


class EvidenceTest(unittest.TestCase):
    def test_ready_requires_three_fresh_independent_runs(self):
        value = record()
        self.assertEqual(validate(value)["verdict"], "ready")
        for mutation, failed in ((lambda r: r["runs"].pop(), "R3"),
            (lambda r: r["runs"][0].update(independent_executor=False), "R12"),
            (lambda r: r["runs"][0]["rows"]["R6"].update({"pass": False}), "R6"),
            (lambda r: r["runs"][1].update(server_instance_sha256="0" * 64), "R3")):
            changed = copy.deepcopy(value)
            mutation(changed)
            self.assertIn(failed, verdict(changed)["failed_rows"])
            with self.assertRaises(ValueError):
                validate(changed)

    def test_compare_only_and_doctor_packet_cannot_be_ready(self):
        value = record()
        for run in value["runs"]:
            for row in ("R1", "R5", "R9"):
                run["rows"][row]["pass"] = False
        self.assertEqual(verdict(value)["verdict"], "not_ready")
        self.assertTrue({"R1", "R5", "R9"}.issubset(verdict(value)["failed_rows"]))
        with self.assertRaisesRegex(ValueError, "not_a_readiness_run"):
            validate(dict(advertised_requirements_met=True, kind="doctor_result"))

    def test_agent_shim_blocks_plain_teerex_and_stubs_interruptions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            log = root / "tools.jsonl"
            config.write_text(json.dumps(dict(condition="plain-rex", log=str(log))))
            shim = Path(__file__).with_name("agent_shim.py")
            blocked = subprocess.run([sys.executable, str(shim), str(config), "teerex", "observe", "SECRET_ARGUMENT"], capture_output=True)
            stubbed = subprocess.run([sys.executable, str(shim), str(config), "agent-send", "SECRET_MESSAGE"], capture_output=True)
            self.assertEqual((blocked.returncode, stubbed.returncode), (127, 0))
            entries = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertTrue(entries[0]["blocked"])
            self.assertTrue(entries[1]["interruption"])
            self.assertNotIn("SECRET", log.read_text())

    def test_raw_fixture_prefix_equal_full_tail_and_exit_differ(self):
        first, error = expected("F1")
        second, quiet = expected("F4")
        self.assertEqual(first[:4096], second[:4096])
        self.assertNotEqual(first, second)
        self.assertEqual((error, quiet), (ASSERTION, b""))

    def test_waited_exec_drains_both_streams_and_reports_local_usage(self):
        result, metrics = execute([sys.executable, "-c", "import sys;sys.stdout.write('x'*100000);sys.stderr.write('y'*100000);sys.exit(3)"])
        self.assertEqual(result.returncode, 3)
        self.assertEqual((metrics["stdout_bytes"], metrics["stderr_bytes"]), (100000, 100000))
        self.assertGreater(metrics["maxrss_kib"], 0)
        self.assertGreaterEqual(metrics["cpu_ms"], 0)

    def test_summary_refuses_missing_measurement_domain(self):
        with self.assertRaisesRegex(ValueError, "measurement_domain_required"):
            summarize(dict(measurements={"teerex": {"F1": {}}}, rows={}))

    def test_packaging_absent_malformed_ready_and_stale(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
            git("init", "-q")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "Fixture")
            (root / "input.zig").write_text("fixture\n")
            (root / RUBRIC).parent.mkdir(parents=True)
            (root / RUBRIC).write_text("rubric\n")
            mapping = root / "tools/acceptance/contracts/observe.json"
            mapping.parent.mkdir(parents=True)
            mapping.write_text(json.dumps({"covered_paths": ["input.zig"]}))
            git("add", ".")
            git("commit", "-qm", "fixture")
            commit = git("rev-parse", "HEAD")
            self.assertEqual(readiness("observe", "x86_64-linux", commit, root)[0], "absent")
            path = root / "tools/cartridges/readiness/observe-x86_64-linux.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            with self.assertRaises(ValueError):
                readiness("observe", "x86_64-linux", commit, root)
            value = record(commit)
            value["rubric_sha256"] = sha(root / RUBRIC)
            value["covered_paths"] = contract("observe", root)["covered_paths"]
            value.update(input_snapshot(value["covered_paths"], root))
            legacy = {k: v for k, v in value.items() if k not in ("covered_files_sha256", "covered_inputs_sha256")}
            path.write_text(json.dumps(legacy))
            self.assertEqual(readiness("observe", "x86_64-linux", commit, root)[0], "stale:missing_content_hash")
            path.write_text(json.dumps(value))
            state, evidence = readiness("observe", "x86_64-linux", commit, root, "c" * 64)
            self.assertEqual((state, evidence["evidenced_api_revisions"]), ("ready", [13]))
            self.assertEqual(readiness("observe", "x86_64-linux", commit, root, "e" * 64)[0], "ready")
            # Later unrelated commits, checkout timestamps and absent provenance
            # objects do not invalidate identical covered content.
            (root / "unrelated.md").write_text("later commit\n")
            git("add", "unrelated.md")
            git("commit", "-qm", "unrelated")
            value["source_commit"] = "f" * 40
            path.write_text(json.dumps(value))
            (root / "input.zig").touch()
            self.assertEqual(readiness("observe", "x86_64-linux", git("rev-parse", "HEAD"), root)[0], "ready")
            (root / "input.zig").write_text("fixture\n\n")
            git("add", "input.zig")
            git("commit", "-qm", "change covered input")
            self.assertEqual(readiness("observe", "x86_64-linux", git("rev-parse", "HEAD"), root)[0], "stale:input.zig")
            (root / "tools/cartridges/cartridges.py").write_text("manager change\n")
            self.assertEqual(readiness("observe", "x86_64-linux", git("rev-parse", "HEAD"), root)[0], "stale:input.zig,tools/cartridges/cartridges.py")
            (root / "input.zig").unlink()
            self.assertIn("input.zig", readiness("observe", "x86_64-linux", "0" * 40, root)[0])


if __name__ == "__main__":
    unittest.main()
