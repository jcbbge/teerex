"""Cooperative clutch contracts against a disposable Rex server only."""
import fcntl
import hashlib
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "send"))
import test_send as fixtures


class ClutchTest(fixtures.SendTest):
    def orphan_record(self, source, socket):
        """Prune fixtures describe gone endpoints; they never take a nonexistent pane."""
        value = json.loads(source.read_text())
        value.update(socket=str(socket), held=False)
        name = hashlib.sha256('\0'.join(value[k] for k in ('socket', 'session', 'pane')).encode()).hexdigest() + '.json'
        path = Path(self.env['TEEREX_CLUTCH_DIR']) / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path
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
        result = subprocess.run(self.command(target) + ["--no-queue", "--draft-wait-ms", str(wait), *extra], env=self.env,
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
        self.assertIsNone(repeated["record"])
        self.assertFalse(state.exists())

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
        process = subprocess.Popen(self.command(target) + ["--no-queue", "--draft-wait-ms", "3000"], env=self.env,
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
        process = subprocess.Popen(self.command(target) + ["--no-queue", "--draft-wait-ms", "600"], env=self.env,
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

    def test_unsafe_state_is_unknown_and_socket_alias_shares_confirmed_hold(self):
        target, raw = self.fixture()
        _, packet = self.clutch("take", target)
        # Keep the same path length as rex.sock: Darwin sockaddr_un has a short fixed limit.
        alias = self.socket.with_name("app sock")
        alias.symlink_to(self.socket)
        command = self.command(target) + ["--no-queue", "--draft-wait-ms", "0"]
        command[command.index("--socket") + 1] = str(alias)
        result = subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=5)
        self.assertEqual(json.loads(result.stdout)["failure_reason"], "pane_held_by_human")
        state = Path(packet["state_file"])
        state.chmod(0o644)
        result, refusal = self.clutch("release", target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(refusal["state"], "unknown")
        self.assertEqual(refusal["failure_reason"], "ClutchStateNotPrivateOwned")
        result = subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["clutch"]["state"], "unknown")
        self.assertEqual(packet["clutch"]["failure_reason"], "ClutchStateNotPrivateOwned")
        self.assertNotIn("Unexpected", result.stdout + result.stderr)
        self.received(raw, self.pasted(b"hello"))

    def test_store_open_and_corrupt_record_failures_do_not_block_ordinary_send(self):
        target, raw = self.fixture()
        root = Path(self.env["TEEREX_CLUTCH_DIR"])
        root.write_text("not a directory")
        result, packet = self.bounded_send(target, 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(packet["clutch"]["state"], "unknown")
        self.assertTrue(packet["clutch"]["failure_reason"])
        self.assertNotIn("Unexpected", result.stdout + result.stderr)
        self.received(raw, self.pasted(b"hello"))
        root.unlink()
        result, held = self.clutch("take", target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        Path(held["state_file"]).write_text("corrupt JSON")
        result, packet = self.bounded_send(target, 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(packet["clutch"]["state"], "unknown")
        self.assertTrue(packet["clutch"]["failure_reason"])
        self.received(raw, self.pasted(b"hello") * 2)

    def test_send_ignores_mutation_lock_and_does_not_initialize_state(self):
        target, raw = self.fixture()
        root = Path(self.env["TEEREX_CLUTCH_DIR"])
        root.mkdir(mode=0o700)
        lock = root / "clutch.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, packet = self.send(target, timeout=1000)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(packet["clutch"]["state"], "released")
            self.assertEqual(list(root.glob("*.json")), [])
            self.received(raw, self.pasted(b"hello"))
        finally:
            os.close(fd)

    def test_record_becoming_unreadable_during_draft_wait_is_nonblocking(self):
        target, log = self.prompt()
        self.type_draft(target, "keep this draft")
        result, saved = self.clutch("release", target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        process = subprocess.Popen(self.command(target) + ["--draft-wait-ms", "500"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: self.cleanup_process(process))
        time.sleep(.2)
        Path(saved["state_file"]).write_text("corrupt JSON")
        stdout, stderr = process.communicate(timeout=6)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        packet = json.loads(stdout)
        self.assertEqual(packet["clutch"]["state"], "unknown")
        self.assertEqual(packet["clutch"]["failure_reason"], "clutch_state_invalid")
        self.assertTrue(packet["draft"]["restore_verified"])
        self.assertIn("keep this draft", self.prompt_text(target))

    def prune(self, *extra):
        result = subprocess.run([fixtures.BIN, "clutch", "prune", *extra], env=self.env,
                                capture_output=True, text=True, timeout=15)
        return result, json.loads(result.stdout)

    def test_send_and_status_create_no_store_and_release_deletes_record(self):
        target, raw = self.fixture()
        root = Path(self.env["TEEREX_CLUTCH_DIR"])
        self.clutch("status", target)
        result, packet = self.bounded_send(target, 0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(packet["clutch"]["state"], "released")
        self.assertFalse(root.exists())
        _, taken = self.clutch("take", target)
        self.assertTrue(Path(taken["state_file"]).exists())
        self.clutch("release", target)
        self.assertFalse(Path(taken["state_file"]).exists())
        self.assertEqual(list(root.iterdir()), [root / "clutch.lock"])

    def test_prune_plans_then_removes_only_released_gone_records(self):
        live, _ = self.fixture()
        dead, _ = self.fixture()
        held, _ = self.fixture()
        files = []
        for target in (live, dead, held):
            _, value = self.clutch("take", target)
            file = Path(value["state_file"])
            if target != held:
                record = json.loads(file.read_text()); record["held"] = False
                file.write_text(json.dumps(record))
            files.append(file)
        self.rpc("block.close", {"session_id": dead[0], "block_id": dead[1]})
        self.rpc("block.close", {"session_id": held[0], "block_id": held[1]})
        missing = self.work / "gone.sock"
        orphan = self.orphan_record(files[0], missing)
        before = {p.name: p.read_bytes() for p in orphan.parent.iterdir()}
        result, plan = self.prune()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({p["file"] for p in plan["selected"]}, {files[1].name, orphan.name})
        self.assertEqual(plan["removed"], [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in orphan.parent.iterdir()})
        result, applied = self.prune("--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(set(applied["removed"]), {files[1].name, orphan.name})
        self.assertTrue(files[0].exists() and files[2].exists())

    def test_prune_preserves_corrupt_linked_unknown_and_concurrently_taken_records(self):
        target, _ = self.fixture()
        _, taken = self.clutch("take", target)
        file = Path(taken["state_file"])
        # A take between plan and apply must win, even after a prior released plan.
        record = json.loads(file.read_text()); record["held"] = False
        file.write_text(json.dumps(record))
        self.rpc("block.close", {"session_id": target[0], "block_id": target[1]})
        _, plan = self.prune()
        self.assertEqual(len(plan["selected"]), 1)
        self.clutch("take", target)
        _, applied = self.prune("--apply")
        self.assertEqual(applied["removed"], [])
        original = file.read_bytes()
        outside = self.work / "outside"; outside.write_bytes(original)
        file.unlink(); file.symlink_to(outside)
        _, applied = self.prune("--apply")
        self.assertEqual(applied["removed"], [])
        self.assertEqual(outside.read_bytes(), original)
        file.unlink(); file.write_text("invalid JSON"); file.chmod(0o600)
        _, applied = self.prune("--apply")
        self.assertEqual(applied["removed"], [])
        file.unlink()
        # An existing non-socket endpoint is uncertain, never proof of disappearance.
        socket = self.work / "uncertain.sock"; socket.write_text("not a socket")
        source = self.work / 'prune-record-source.json'
        source.write_bytes(original)
        file = self.orphan_record(source, socket)
        source.unlink()
        _, applied = self.prune("--apply")
        self.assertEqual(applied["removed"], [])
        self.assertTrue(file.exists())

    def test_palette_fragment_is_exclusive_and_uses_invoking_pane(self):
        fragment = self.work / "clutch.lua"
        controller = self.work / 'pinned-clutch'
        controller.write_text('#!/bin/sh\nexec ' + shlex.join([fixtures.BIN, '--rex', self.rex]) + ' "$@"\n')
        controller.chmod(0o700)
        result = subprocess.run([fixtures.BIN, "clutch", "palette", "--file", str(fragment), "--socket", str(self.socket), '--teerex', str(controller)],
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
