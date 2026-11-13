"""Public scratchpad CLI contracts, private temporary HOME; no personal Rex/state."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())
SESSION = "session:11111111-1111-1111-1111-111111111111"
BLOCK = "block:22222222-2222-2222-2222-222222222222"


class ScratchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teerex-scratch-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, HOME=str(self.root), REX_SESSION=SESSION, REX_BLOCK=BLOCK,
                        TEEREX_CALL_LOG_DIR=str(self.root / "calls"))
        self.env.pop("AGENT_SCRATCHPAD", None)
        self.env.pop("LC_AGENT_SCRATCHPAD", None)
        self.path = self.root / ".local/state/teerex/scratch" / SESSION / (BLOCK + ".md")

    def cli(self, *args, check=True):
        p = subprocess.run([BIN, "scratch", *args], env=self.env, text=True, capture_output=True, timeout=15)
        if check:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def init(self):
        self.cli("init", "--name", "worker β", "--purpose", "Build scratchpad", "--intent", "All gates pass")

    def data(self):
        return json.loads(self.cli("show", "--json").stdout)

    def hook(self, kind, **fields):
        return subprocess.run([BIN, "scratch", "hook"], env=self.env, input=json.dumps(dict(hook_event_name=kind, **fields)),
                              text=True, capture_output=True, timeout=15)

    def test_seat_hook_stale_blocks_once_per_turn_and_records_second_stop(self):
        self.init()
        self.env["AGENT_SCRATCHPAD"] = str(self.path)
        settings = json.loads(self.cli("hook-settings", "--teerex", BIN).stdout)
        self.assertEqual(set(settings["hooks"]), {"UserPromptSubmit", "Stop"})
        self.assertIn(" scratch hook", settings["hooks"]["Stop"][0]["hooks"][0]["command"])
        self.assertEqual(self.hook("UserPromptSubmit").returncode, 0)
        self.path.write_text(self.path.read_text().replace(self.data()["updated"], "2000-01-01T00:00:00Z"))
        first = self.hook("Stop")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout), dict(decision="block", reason="say what you are waiting on: teerex scratch wait --on … --what …"))
        second = self.hook("Stop", stop_hook_active=True)
        self.assertEqual(json.loads(second.stdout)["scratchpad_check"]["status"], "stale")
        self.assertEqual(json.loads(second.stdout)["scratchpad_check"]["action"], "allow")
        sidecar = Path(str(self.path) + ".turn.json")
        self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)
        self.assertTrue(json.loads(sidecar.read_text())["scratchpad_check"]["already_reminded"])
        self.hook("UserPromptSubmit")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["decision"], "block")

    def test_seat_hook_fresh_missing_and_opt_out(self):
        self.init()
        self.env["AGENT_SCRATCHPAD"] = str(self.path)
        self.hook("UserPromptSubmit")
        self.cli("now", "Update during turn")
        check = json.loads(self.hook("Stop").stdout)["scratchpad_check"]
        self.assertEqual((check["status"], check["action"]), ("fresh", "allow"))
        self.hook("UserPromptSubmit")
        self.path.unlink()
        self.assertEqual(json.loads(self.hook("Stop").stdout)["decision"], "block")
        self.env.pop("AGENT_SCRATCHPAD")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["scratchpad_check"]["status"], "not_checked")

    def test_init_path_permissions_and_idempotence(self):
        self.init()
        self.assertEqual(self.cli("path").stdout.strip(), str(self.path))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.path.parent.parent.stat().st_mode), 0o700)
        self.cli("now", "Keep this")
        self.init()
        self.assertEqual(self.data()["now"], "Keep this")
        self.assertIn("# worker β\nPurpose: Build scratchpad\nIntent: All gates pass\nUpdated: ", self.path.read_text())

    def test_now_todo_done_and_previous_disposition(self):
        self.init()
        self.cli("todo", "Later")
        self.cli("now", "First")
        self.cli("now", "Second")
        self.assertEqual(self.data()["todo"], ["First", "Later"])
        self.cli("now", "Third", "--done")
        self.assertEqual(self.data()["done"], ["Second"])
        self.cli("done")
        self.cli("done")
        self.assertIsNone(self.data()["now"])
        self.assertEqual(self.data()["done"], ["Third", "Second"])
        self.cli("now", "Later")
        self.assertEqual(self.data()["todo"], ["First"])
        self.assertEqual(set(self.data()), {"purpose", "intent", "now", "todo", "done", "updated", "steps", "waiting"})

    def test_handwritten_missing_sections_blank_lines_round_trip(self):
        self.init()
        self.path.write_text("# Hand written\n\nPurpose: Keep edits\nIntent: Finish\n\n\n## Now\n\n- [ ] Work\n- [ ] Extra now\n\n## Done\n- [X] Before\n")
        self.cli("todo", "After")
        self.assertEqual(self.data()["now"], "Work")
        self.assertEqual(self.data()["todo"], ["Extra now", "After"])
        self.assertEqual(self.data()["done"], ["Before"])
        self.assertIn("\n\n## To-do\n- [ ] Extra now\n- [ ] After\n\n## Done\n- [x] Before\n", self.path.read_text())
        self.assertEqual(self.path.read_text().count("Updated:"), 1)

    def test_concurrent_writers_preserve_all_tasks(self):
        self.init()
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda i: self.cli("todo", "Task " + str(i)), range(40)))
        self.assertEqual(set(self.data()["todo"]), {"Task " + str(i) for i in range(40)})
        self.assertEqual(len(self.data()["todo"]), 40)
        self.assertFalse(list(self.path.parent.glob(".scratch-*")))

    def test_watch_once_and_live_redraw(self):
        self.init()
        self.cli("now", "Done")
        self.cli("done")
        self.cli("now", "Current " + "word " * 20)
        self.cli("todo", "Later")
        frame = self.cli("watch", "--once").stdout
        for value in ("✓ Done", "▶ Current", "☐ Later", "updated 0 min ago"):
            self.assertIn(value, frame)
        self.assertTrue(all(len(line) <= 40 for line in frame.splitlines()))
        with tempfile.TemporaryFile() as log:
            proc = subprocess.Popen([BIN, "scratch", "watch"], env=self.env, stdout=log, stderr=log)
            try:
                time.sleep(.4)
                self.cli("todo", "Changed live")
                end = time.monotonic() + 5
                while time.monotonic() < end:
                    log.seek(0)
                    if b"Changed live" in log.read():
                        break
                    time.sleep(.1)
                else:
                    self.fail("watch failed to redraw")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_annotations_order_and_legacy_steps(self):
        self.init()
        self.cli("now", "Read", "--by", "opus high")
        self.cli("now", "Build", "--done", "--outcome", "understood", "--by", "computer")
        self.cli("done", "--outcome", "fixed")
        self.cli("todo", "Integrate", "--by", "computer", "--handoff", "codex-board")
        self.cli("now", "Review", "--by", "gpt-5 xhigh")
        steps = self.data()["steps"]
        self.assertEqual([(v["state"], v["text"]) for v in steps],
                         [("done", "Read"), ("done", "Build"), ("now", "Review"), ("todo", "Integrate")])
        self.assertEqual(steps[0]["outcome"], "understood")
        self.assertEqual(steps[1]["by"], "computer")
        self.assertEqual(steps[1]["outcome"], "fixed")
        self.assertEqual(steps[3]["handoff"], "codex-board")
        self.init()
        self.assertEqual(self.data()["steps"], steps)
        for text in ("■ fixed", "⇥ codex-board", "opus high"):
            self.assertIn(text, self.cli("show").stdout)
        self.cli("now", "Integrate")
        self.assertEqual(self.data()["steps"][-2]["by"], "computer")
        self.path.write_text("# Legacy\n## Done\n- [x] old\n## Now\n- [ ] work\n")
        self.assertEqual(self.data()["steps"], [dict(state="done", text="old", by=None, outcome=None, handoff=None),
                                               dict(state="now", text="work", by=None, outcome=None, handoff=None)])

    def test_waiting_round_trip_clear_now_and_discovery(self):
        self.init()
        self.cli("wait", "--on", "teerex", "--what", "integration report")
        waiting = self.data()["waiting"]
        self.assertEqual((waiting["on"], waiting["what"]), ("teerex", "integration report"))
        self.assertTrue(waiting["since"].endswith("Z"))
        self.assertIn("Waiting: teerex · integration report · since ", self.path.read_text())
        self.assertIn("⧗ teerex", self.cli("show").stdout)
        self.init()
        self.assertEqual(self.data()["waiting"], waiting)
        self.assertEqual(json.loads(self.cli("waiters", "--on", "teerex", "--json").stdout),
                         [dict(session=SESSION, block=BLOCK, name="worker β")])
        self.cli("wait", "--clear")
        self.assertIsNone(self.data()["waiting"])
        self.cli("wait", "--on", "teerex", "--what", "answer")
        self.cli("now", "Continue")
        self.assertIsNone(self.data()["waiting"])
        self.assertEqual(json.loads(self.cli("waiters", "--on", "teerex", "--json").stdout), [])
        original = self.path.read_bytes()
        for args in (("--on", "a"), ("--on", "a", "--what", "x\ny"),
                     ("--on", "a · b", "--what", "x"), ("--clear", "--what", "x")):
            self.assertNotEqual(self.cli("wait", *args, check=False).returncode, 0)
            self.assertEqual(self.path.read_bytes(), original)

    def test_hook_requires_progress_or_waiting_not_timestamp(self):
        self.init()
        self.env["AGENT_SCRATCHPAD"] = str(self.path)
        self.cli("now", "Working")
        self.hook("UserPromptSubmit")
        self.cli("todo", "Only planning")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["decision"], "block")
        self.hook("UserPromptSubmit")
        self.cli("done", "--outcome", "fixed")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["scratchpad_check"]["action"], "allow")
        self.hook("UserPromptSubmit")
        self.cli("wait", "--on", "teerex", "--what", "review")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["scratchpad_check"]["action"], "allow")
        self.hook("UserPromptSubmit")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["scratchpad_check"]["action"], "allow")

    def test_hook_done_only_progress_and_missing_snapshot(self):
        self.init()
        self.env["AGENT_SCRATCHPAD"] = str(self.path)
        self.hook("UserPromptSubmit")
        self.path.write_text(self.path.read_text().replace("## Done\n", "## Done\n- [x] Completed externally\n"))
        self.assertEqual(json.loads(self.hook("Stop").stdout)["scratchpad_check"]["action"], "allow")
        self.hook("UserPromptSubmit")
        self.path.write_text(self.path.read_text().replace("- [x] Completed externally\n", ""))
        self.assertEqual(json.loads(self.hook("Stop").stdout)["decision"], "block")
        Path(str(self.path) + ".turn.json").unlink()
        self.cli("now", "Fresh timestamp with no baseline")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["decision"], "block")
        Path(str(self.path) + ".turn.json").unlink()
        self.cli("wait", "--on", "teerex", "--what", "integration")
        self.assertEqual(json.loads(self.hook("Stop").stdout)["scratchpad_check"]["action"], "allow")

    def test_watch_exits_zero_when_shown_file_archived_or_removed(self):
        for archive in (True, False):
            self.init()
            proc = subprocess.Popen([BIN, "scratch", "watch"], env=self.env, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                # First line proves the viewer read the file before it disappears.
                self.assertEqual(proc.stdout.readline().strip(), "worker β")
                if archive:
                    self.path.rename(self.root / "archived.md")
                else:
                    self.path.unlink()
                out, err = proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, 0, out + err)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()

    def test_one_shot_wait_notifies_filters_and_times_out(self):
        self.init()
        import importlib.util
        spec = importlib.util.spec_from_file_location("scratch_library", Path(__file__).with_name("scratch.py"))
        library = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(library)
        self.assertFalse(library.scratch_wake(self.path))
        for until in ("done", "report"):
            proc = subprocess.Popen([BIN, "scratch", "wait", "--on", "teerex", "--what", "answer",
                                     "--until", until, "--timeout-ms", "5000"], env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                end = time.monotonic() + 4
                while not Path(str(self.path) + ".wait.fifo").exists():
                    self.assertLess(time.monotonic(), end)
                    time.sleep(.01)
                # The write lock fences registration, so notification cannot race publication.
                with library.scratch_lock(self.path):
                    self.assertTrue(library.scratch_wake(self.path, "done"))
                if until == "report":
                    self.assertIsNone(proc.poll())
                    self.assertTrue(library.scratch_wake(self.path, "report"))
                out, err = proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, 0, err)
                self.assertEqual(json.loads(out)["outcome"], "notified")
                self.assertFalse(Path(str(self.path) + ".wait.fifo").exists())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
        result = self.cli("wait", "--on", "teerex", "--what", "answer", "--until", "done",
                          "--timeout-ms", "1", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["outcome"], "timeout")
        self.assertIsNotNone(self.data()["waiting"])

    def test_annotation_validation_and_fifo_refuses_existing_file(self):
        self.init()
        original = self.path.read_bytes()
        for args in (("now", "work", "--by", "one\ntwo"),
                     ("todo", "later", "--handoff", "a · b"),
                     ("now", "work", "--outcome", "not completed")):
            self.assertNotEqual(self.cli(*args, check=False).returncode, 0)
            self.assertEqual(self.path.read_bytes(), original)
        fifo = Path(str(self.path) + ".wait.fifo")
        other = self.root / "untouched"
        other.write_text("keep")
        fifo.symlink_to(other)
        self.assertNotEqual(self.cli("wait", "--on", "teerex", "--what", "answer", "--until", "done",
                                     "--timeout-ms", "10", check=False).returncode, 0)
        self.assertEqual(other.read_text(), "keep")
        self.assertTrue(fifo.is_symlink())
        self.assertEqual(self.path.read_bytes(), original)

    def test_explicit_target_and_lc_environment(self):
        self.init()
        self.env.update(REX_SESSION="poison", REX_BLOCK="poison")
        self.assertEqual(self.cli("path", "--session", SESSION, "--block", BLOCK).stdout.strip(), str(self.path))
        self.env.pop("REX_SESSION")
        self.env.pop("REX_BLOCK")
        self.env.update(LC_REX_SESSION=SESSION, LC_REX_BLOCK=BLOCK)
        self.assertEqual(self.data()["purpose"], "Build scratchpad")
        self.assertNotEqual(self.cli("path", "--block", "../escape", check=False).returncode, 0)

    def test_refuse_symlink_and_multiline_task_without_damage(self):
        self.init()
        original = self.path.read_bytes()
        self.assertNotEqual(self.cli("now", "one\ntwo", check=False).returncode, 0)
        self.assertEqual(self.path.read_bytes(), original)
        target = self.root / "other"
        target.write_text("keep")
        self.path.unlink()
        self.path.symlink_to(target)
        self.assertNotEqual(self.cli("todo", "no", check=False).returncode, 0)
        self.assertEqual(target.read_text(), "keep")

    def test_palette_rex_pin_is_literal_and_relative_pin_refuses(self):
        path = self.root / "pinned.lua"
        pin = str(self.root / "rex pin")
        self.cli("palette", "--file", str(path), "--socket", str(self.root / "none.sock"), "--rex", pin)
        self.assertIn("--rex", path.read_text())
        self.assertIn(pin, path.read_text())
        refused = self.root / "refused.lua"
        self.assertNotEqual(self.cli("palette", "--file", str(refused), "--socket", "/tmp/none.sock",
                                     "--rex", "relative", check=False).returncode, 0)
        self.assertFalse(refused.exists())

    def test_palette_prepared_fragment_without_overwrite(self):
        path = self.root / "scratch.lua"
        p = self.cli("palette", "--file", str(path), "--socket", str(self.root / "none.sock"))
        self.assertFalse(json.loads(p.stdout)["installed"])
        lua = path.read_text()
        for value in ("Show scratchpad", "-- teerex-surface-action:teerex_scratch_show", "ctx.block_id", "'scratch','watch'"):
            self.assertIn(value, lua)
        self.assertNotEqual(self.cli("palette", "--file", str(path), "--socket", str(self.root / "none.sock"), check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
