"""Cooperative clutch contracts against a disposable Rex server only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "send"))
import test_send as fixtures


class ClutchTest(fixtures.SendTest):
    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def clutch(self, operation, target, *extra):
        result = subprocess.run([fixtures.BIN, "clutch", operation, "--socket", str(self.socket), "--session", target[0],
                                 "--pane", target[1], *extra], capture_output=True, text=True, env=self.env, timeout=5)
        return result, json.loads(result.stdout) if result.stdout else None

    def bounded_send(self, target, wait=150, *extra):
        result = subprocess.run(self.command(target) + ["--draft-wait-ms", str(wait), *extra], env=self.env,
                                capture_output=True, text=True, timeout=8)
        return result, json.loads(result.stdout)

    def test_take_status_release_idempotence_and_private_state(self):
        target, _ = self.fixture()
        result, held = self.clutch("take", target, "--reason", "operator edits β")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(held["held"] and held["changed"])
        self.assertFalse(held["server_enforced"])
        state = Path(held["state_file"])
        self.assertEqual(state.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        _, repeated = self.clutch("take", target, "--reason", "another reason")
        self.assertFalse(repeated["changed"])
        self.assertEqual(repeated["record"], held["record"])
        _, status = self.clutch("status", target)
        self.assertEqual(status["record"], held["record"])
        _, released = self.clutch("release", target, "--reason", "finished editing")
        self.assertTrue(released["changed"])
        self.assertFalse(released["held"])
        _, repeated = self.clutch("release", target)
        self.assertFalse(repeated["changed"])
        self.assertEqual(repeated["record"], released["record"])

    def test_held_refuses_with_no_input_even_when_draft_is_ignored_then_release_delivers(self):
        target, raw = self.fixture()
        self.clutch("take", target)
        started = time.monotonic()
        result, packet = self.bounded_send(target, 200, "--draft", "ignore")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(packet["failure_reason"], "pane_held_by_human")
        self.assertTrue(packet["retry_safe"])
        self.assertFalse(packet["paste"]["attempted"] or packet["enter"]["attempted"])
        self.assertGreaterEqual(time.monotonic() - started, .18)
        self.assertTrue(packet["clutch"]["held_observed"])
        self.assertTrue(packet["clutch"]["bound_reached"])
        self.assertEqual(raw.read_bytes(), b"")
        self.clutch("release", target)
        result, packet = self.bounded_send(target, 0, "--draft", "ignore")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.received(raw, self.pasted(b"hello"))

    def test_release_unblocks_waiting_sender_without_retry(self):
        target, raw = self.fixture()
        self.clutch("take", target)
        process = subprocess.Popen(self.command(target) + ["--draft-wait-ms", "3000"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: self.cleanup_process(process))
        time.sleep(.3)
        self.assertIsNone(process.poll())
        self.assertEqual(raw.read_bytes(), b"")
        result, released = self.clutch("release", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        stdout, stderr = process.communicate(timeout=6)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertTrue(json.loads(stdout)["clutch"]["held_observed"])
        self.received(raw, self.pasted(b"hello"))

    def test_hold_preserves_typed_draft_and_blocks_take_during_draft_wait(self):
        target, log = self.prompt()
        draft = "operator unfinished β"
        self.type_draft(target, draft)
        process = subprocess.Popen(self.command(target) + ["--draft-wait-ms", "600"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: self.cleanup_process(process))
        time.sleep(.2)
        self.clutch("take", target)
        stdout, stderr = process.communicate(timeout=6)
        self.assertEqual(process.returncode, 1, stdout + stderr)
        packet = json.loads(stdout)
        self.assertEqual(packet["failure_reason"], "pane_held_by_human")
        self.assertTrue(packet["retry_safe"])
        self.assertFalse(packet["paste"]["attempted"])
        self.assertIn(draft, self.prompt_text(target))
        self.assertFalse(any(isinstance(json.loads(line), str) and json.loads(line) for line in log.read_text().splitlines()))

    def test_closed_pane_hold_does_not_block_new_identity_or_other_server(self):
        old, _ = self.fixture()
        self.clutch("take", old)
        self.rpc("block.close", {"session_id": old[0], "block_id": old[1]})
        new, raw = self.fixture()
        self.assertNotEqual(old[1], new[1])
        result, packet = self.bounded_send(new, 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.received(raw, self.pasted(b"hello"))
        other_socket = str(self.socket) + ".other"
        result = subprocess.run([fixtures.BIN, "clutch", "status", "--socket", other_socket, "--session", old[0], "--pane", old[1]],
                                capture_output=True, text=True, env=self.env, timeout=5)
        self.assertFalse(json.loads(result.stdout)["held"])

    def test_unsafe_state_fails_closed_and_socket_alias_shares_hold(self):
        target, raw = self.fixture()
        _, packet = self.clutch("take", target)
        alias = self.work / "alias.sock"
        alias.symlink_to(self.socket)
        command = self.command(target) + ["--draft-wait-ms", "0"]
        command[command.index("--socket") + 1] = str(alias)
        result = subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=5)
        self.assertEqual(json.loads(result.stdout)["failure_reason"], "pane_held_by_human")
        state = Path(packet["state_file"])
        state.chmod(0o644)
        result, _ = self.clutch("release", target)
        self.assertNotEqual(result.returncode, 0)
        result = subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(raw.read_bytes(), b"")

    def test_palette_fragment_is_exclusive_and_uses_invoking_pane(self):
        fragment = self.work / "clutch.lua"
        result = subprocess.run([fixtures.BIN, "clutch", "palette", "--file", str(fragment), "--socket", str(self.socket)],
                                capture_output=True, text=True, env=self.env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        source = fragment.read_text()
        self.assertIn("Take control of this pane", source)
        self.assertIn("Hand back", source)
        self.assertIn("ctx.session_id", source)
        self.assertIn("ctx.block_id", source)
        self.assertIn("-- teerex-surface-action:teerex_clutch_take", source)
        result = subprocess.run([fixtures.BIN, "clutch", "palette", "--file", str(fragment), "--socket", str(self.socket)],
                                capture_output=True, text=True, env=self.env, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fragment.read_text(), source)
        target, raw = self.fixture()
        plan_file = self.work / "palette-plan.json"
        command = [fixtures.BIN, "surfaces", "palette", "install", "--socket", str(self.socket),
                   "--init", str(self.config), "--file", str(fragment), "--plan", str(plan_file)]
        result = subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads(result.stdout)
        result = subprocess.run(command + ["--apply", plan["plan_sha256"]], capture_output=True, text=True, env=self.env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "registered_and_verified")
        for action, expected in (("teerex_clutch_take", True), ("teerex_clutch_release", False)):
            result = self.rex_json("do", "--session", target[0], "--block", target[1], action)
            self.assertEqual(result["held"], expected)
            _, status = self.clutch("status", target)
            self.assertEqual(status["held"], expected)
        self.assertEqual(raw.read_bytes(), b"")
        self.config.write_text("")
        self.rpc("server.config_reload", {})



def load_tests(loader, suite, pattern):
    # Reuse only the disposable fixture helpers, not a second copy of the send suite.
    return unittest.TestSuite(ClutchTest(name) for name in ClutchTest.__dict__ if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
