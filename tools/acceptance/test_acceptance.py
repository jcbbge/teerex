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
from records import ROWS, RUBRIC, readiness, sha, validate, verdict
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
            path.write_text(json.dumps(value))
            state, evidence = readiness("observe", "x86_64-linux", commit, root, "c" * 64)
            self.assertEqual((state, evidence["evidenced_api_revisions"]), ("ready", [13]))
            self.assertEqual(readiness("observe", "x86_64-linux", commit, root, "e" * 64)[0], "stale:payload_sha256")
            (root / "input.zig").write_text("changed\n")
            git("add", "input.zig")
            git("commit", "-qm", "change covered input")
            self.assertEqual(readiness("observe", "x86_64-linux", git("rev-parse", "HEAD"), root)[0], "stale:input.zig")


if __name__ == "__main__":
    unittest.main()
