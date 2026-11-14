"""Focus queue on a disposable Rex server; response-loss cases explicitly inject transport faults."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "send"))
import test_send as fixtures


class FocusQueueTest(fixtures.SendTest):
    def clutch(self, operation, target, *extra, check=True):
        result = subprocess.run([fixtures.BIN, "clutch", operation, "--socket", str(self.socket),
            "--session", target[0], "--pane", target[1], *extra], env=self.env,
            text=True, capture_output=True, timeout=40)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result, json.loads(result.stdout)

    def queued(self, target, body=b"hello", sender="worker"):
        result, packet = self.send(target, body, sender)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(packet["outcome"], "queued")
        self.assertTrue(packet["queue_id"])
        self.assertFalse(packet["backend_invoked"])
        self.assertFalse(packet["paste"]["attempted"] or packet["enter"]["attempted"])
        return packet["queue_id"]

    def inject_second(self, uncertain=False):
        wrapper = self.work / "wrapper"
        wrapper.mkdir()
        counter = self.work / "dispatch-count"
        script = f'''#!{sys.executable}
import json, os, subprocess, sys
from pathlib import Path
counter=Path({str(counter)!r})
n=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(n))
if n==2 and not {uncertain!r}:
    print(json.dumps(dict(event="refused", reason="injected_before_input")),flush=True)
    sys.exit(0)
p=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True)
if n==2:
    for line in p.stdout.splitlines():
        if json.loads(line).get("event")!="finished": print(line.decode(),flush=True)
    sys.exit(1)
sys.stdout.buffer.write(p.stdout)
sys.stderr.buffer.write(p.stderr)
sys.exit(p.returncode)
'''
        (wrapper / "rex").write_text(script)
        (wrapper / "rex").chmod(0o700)
        self.env["PATH"] = str(wrapper) + os.pathsep + self.env["PATH"]
        return counter

    def test_held_queue_private_inspection_ordered_drain_and_repeat_release(self):
        # Every CLI invocation is a new process: no sender survives to release.
        target, raw = self.fixture()
        _, hold = self.clutch("take", target)
        ids = [self.queued(target, b"first\nPRIVATE_SECOND_LINE", "alpha"), self.queued(target, b"second", "beta"), self.queued(target, b"third", "gamma")]
        self.assertEqual(raw.read_bytes(), b"")
        result, queue = self.clutch("queue", target, "--json")
        self.assertEqual([v["id"] for v in queue["messages"]], ids)
        self.assertEqual([v["state"] for v in queue["messages"]], ["pending", "pending", "pending"])
        self.assertEqual(queue["messages"][0]["sender"], "alpha")
        self.assertGreaterEqual(queue["messages"][0]["age_ms"], 0)
        self.assertNotIn("PRIVATE_SECOND_LINE", result.stdout)
        shown, _ = self.clutch("queue", target, "--json", "--show")
        self.assertIn("PRIVATE_SECOND_LINE", shown.stdout)
        directory = Path(hold["state_file"]).with_suffix(".queue")
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in directory.iterdir()))
        _, released = self.clutch("release", target)
        self.assertEqual(released["queue"]["delivered"], ids)
        self.assertEqual(released["queue"]["pending"], 0)
        expected = self.pasted(b"first\nPRIVATE_SECOND_LINE", "alpha") + self.pasted(b"second", "beta") + self.pasted(b"third", "gamma")
        self.received(raw, expected)
        _, repeated = self.clutch("release", target)
        self.assertEqual(repeated["queue"]["delivered"], [])
        self.received(raw, expected)
        self.assertEqual(self.clutch("queue", target)[1]["messages"], [])

    def test_failed_mid_drain_is_pending_and_next_release_never_repeats_first(self):
        target, raw = self.fixture()
        self.clutch("take", target)
        ids = [self.queued(target, body) for body in (b"one", b"two", b"three")]
        counter = self.inject_second()
        process, released = self.clutch("release", target, check=False)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(released["queue"]["delivered"], ids[:1])
        self.assertEqual(released["queue"]["pending"], 2)
        self.assertTrue(released["queue"]["stopped"]["retry_safe"])
        self.received(raw, self.pasted(b"one"))
        _, next_release = self.clutch("release", target)
        self.assertEqual(next_release["queue"]["delivered"], ids[1:])
        self.assertEqual(counter.read_text(), "4")
        self.received(raw, b"".join(self.pasted(body) for body in (b"one", b"two", b"three")))

    def test_ack_loss_keeps_inflight_and_subsequent_release_does_not_duplicate(self):
        target, raw = self.fixture()
        self.clutch("take", target)
        ids = [self.queued(target, body) for body in (b"one", b"two", b"three")]
        counter = self.inject_second(uncertain=True)
        process, released = self.clutch("release", target, check=False)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(released["queue"]["delivered"], ids[:1])
        self.assertEqual((released["queue"]["pending"], released["queue"]["inflight"]), (1, 1))
        self.assertFalse(released["queue"]["stopped"]["retry_safe"])
        self.received(raw, self.pasted(b"one") + self.pasted(b"two"))
        _, queue = self.clutch("queue", target, "--json")
        self.assertEqual([v["state"] for v in queue["messages"]], ["inflight", "pending"])
        process, repeat = self.clutch("release", target, check=False)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(repeat["queue"]["stopped"]["reason"], "delivery_uncertain")
        self.assertEqual(counter.read_text(), "2")
        self.received(raw, self.pasted(b"one") + self.pasted(b"two"))

    def test_no_queue_wait_then_refuse_unchanged(self):
        target, raw = self.fixture()
        self.clutch("take", target)
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        start = time.monotonic()
        process = subprocess.run(self.command(target) + ["--no-queue", "--draft-wait-ms", "200",
                                 "--store", str(store), "--host", "test"], env=self.env,
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(json.loads(process.stdout)["failure_reason"], "pane_held_by_human")
        self.assertGreaterEqual(time.monotonic() - start, .18)
        self.assertEqual(raw.read_bytes(), b"")
        self.assertEqual(self.clutch("queue", target)[1]["messages"], [])

    def test_concurrent_enqueues_preserve_claim_order_without_duplicates(self):
        target, raw = self.fixture()
        self.clutch("take", target)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(pool.map(lambda i: self.queued(target, f"task {i}".encode()), range(12)))
        self.assertEqual(len(set(ids)), 12)
        _, queue = self.clutch("queue", target, "--json")
        expected = b"".join(self.pasted(v["first_line"].encode(), v["sender"]) for v in queue["messages"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.clutch("release", target, check=False), range(2)))
        self.assertTrue(any(process.returncode == 0 for process, packet in results))
        self.received(raw, expected)
        self.clutch("release", target)
        self.received(raw, expected)

    def test_queue_symlink_and_corruption_refuse_without_disclosure_or_input(self):
        target, raw = self.fixture()
        _, hold = self.clutch("take", target)
        directory = Path(hold["state_file"]).with_suffix(".queue")
        outside = self.work / "outside"
        outside.mkdir(mode=0o700)
        directory.symlink_to(outside, target_is_directory=True)
        process, packet = self.send(target)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(packet["failure_reason"], "QueueWriteFailed")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(raw.read_bytes(), b"")
        directory.unlink()
        identity = self.queued(target)
        file = directory / (identity + ".pending.json")
        file.chmod(0o644)
        process, packet = self.clutch("release", target, check=False)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(packet["failure_reason"], "queue_not_private_owned")
        self.assertTrue(file.exists())
        self.assertEqual(raw.read_bytes(), b"")

    def test_hold_appearing_during_guard_creates_queue_without_clearing_draft(self):
        target, log = self.prompt()
        self.type_draft(target, "operator unfinished")
        self.assertFalse(Path(self.env["TEEREX_CLUTCH_DIR"]).exists())
        process = subprocess.Popen(self.command(target) + ["--draft-wait-ms", "3000"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 3
            while not self.lock(target).exists():
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            self.clutch("take", target)
            out, err = process.communicate(timeout=6)
            self.assertEqual(process.returncode, 0, out + err)
            packet = json.loads(out)
            self.assertEqual(packet["outcome"], "queued")
            self.assertFalse(packet["paste"]["attempted"])
            self.assertIsNone(packet["draft"]["cleared"])
            self.assertIn("operator unfinished", self.prompt_text(target))
            self.assertEqual(log.read_text(), "")
            self.clutch("release", target)
            self.assertIn("operator unfinished", self.prompt_text(target))
            self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: hello"])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_ask_uses_same_queue(self):
        target, raw = self.fixture()
        self.clutch("take", target)
        process = subprocess.run([fixtures.BIN, "ask", "--socket", str(self.socket), "--session", target[0],
            "--block", target[1], "--host", "test", "--from", "worker", "--answer", "ASK_QUEUE_PROBE"],
            env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        packet = json.loads(process.stdout)
        self.assertEqual(packet["outcome"], "queued")
        self.assertEqual(raw.read_bytes(), b"")
        _, released = self.clutch("release", target)
        self.assertEqual(released["queue"]["delivered"], [packet["queue_id"]])
        self.received(raw, self.pasted(b"Answer: ASK_QUEUE_PROBE"))


def load_tests(loader, suite, pattern):
    return unittest.TestSuite(FocusQueueTest(name) for name in FocusQueueTest.__dict__ if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
