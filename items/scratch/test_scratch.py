"""Public scratchpad CLI contracts, private temporary HOME; no personal Rex/state."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/acceptance'))
from test_environment import isolated_environment

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())
SESSION = "session:11111111-1111-1111-1111-111111111111"
BLOCK = "block:22222222-2222-2222-2222-222222222222"


class ScratchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teerex-scratch-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(isolated_environment(), HOME=str(self.root), REX_SESSION=SESSION, REX_BLOCK=BLOCK,
                        TEEREX_CALL_LOG_DIR=str(self.root / "calls"))
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

    def test_done_clears_closed_work_flags_only_when_no_steps_open(self):
        self.init()
        self.cli("now", "First", "--waiting", "review", "--check", "10m")
        self.cli("todo", "Second")
        self.cli("flag", "stuck; tried; need")
        self.cli("done")
        data = self.data()
        self.assertTrue(all(data[k] for k in ("waiting", "check", "blocked")))
        self.cli("now", "Second")
        self.cli("flag", "stuck; tried; need")
        self.cli("done")
        self.assertTrue(all(not self.data()[k] for k in ("waiting", "check", "blocked")))

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
        self.assertEqual(json.loads(first.stdout), dict(decision="block", reason="update your scratchpad (Now/To-do/Done) before ending the turn"))
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
        self.env.pop("LC_AGENT_SCRATCHPAD", None)
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

    def test_waiting_round_trip_render_and_clear(self):
        self.init()
        self.cli("now", "Review", "--waiting", "reviewer · approval")
        self.assertEqual(self.data()["waiting"], "reviewer · approval")
        self.assertIn("Waiting: reviewer", self.cli("show").stdout)
        self.cli("todo", "Later")
        self.assertEqual(self.data()["waiting"], "reviewer · approval")
        self.cli("now", "Resume", "--waiting", "")
        self.assertEqual(self.data()["waiting"], "")
        self.assertNotIn("Waiting:", self.path.read_text())

    def test_contract_headers_flag_and_waiting_check(self):
        self.init()
        self.path.write_text(self.path.read_text() + "\nDone-when: All tests pass\n")
        self.cli("flag", "stuck; tried tests; need review")
        self.assertEqual(self.data()["blocked"], "stuck; tried tests; need review")
        self.cli("todo", "Later")
        self.assertEqual(self.data()["done_when"], "All tests pass")
        self.cli("now", "Review", "--waiting", "reviewer", "--check", "10m")
        self.assertEqual(self.data()["blocked"], "")
        self.assertTrue(self.data()["check"].endswith("Z"))
        self.cli("now", "Review", "--waiting", "", "--check", "2030-01-01T00:00:00Z")
        self.assertEqual(self.data()["check"], "")
        self.cli("flag", "raised")
        self.cli("flag", "")
        self.assertEqual(self.data()["blocked"], "")
        self.assertNotEqual(self.cli("now", "Bad", "--check", "tomorrow", check=False).returncode, 0)
        self.assertNotEqual(self.cli("now", "Bad", "--check", "2030-01-01", check=False).returncode, 0)

    def test_now_todo_done_and_previous_disposition(self):
        self.init()
        self.cli("todo", "Later")
        self.cli("now", "First")
        self.cli("now", "Second")
        self.assertEqual(self.data()["todo"], ["First", "Later"])
        self.cli("now", "Third", "--done")
        self.assertEqual(self.data()["done"], ["Second — unproven"])
        self.cli("done")
        self.cli("done")
        self.assertIsNone(self.data()["now"])
        self.assertEqual(self.data()["done"], ["Third — unproven", "Second — unproven"])
        self.cli("now", "Later")
        self.assertEqual(self.data()["todo"], ["First"])
        self.assertEqual(set(self.data()), {"purpose", "intent", "now", "todo", "done", "updated", "waiting", "done_when", "check", "blocked"})

    def test_completion_proof_survives_render_json_and_later_writes(self):
        self.init()
        self.cli("now", "Verify")
        self.cli("done", "--proof", "ran x: 0 failures")
        entry = "Verify — proof: ran x: 0 failures"
        self.assertEqual(self.data()["done"], [entry])
        self.assertIn("- [x] " + entry, self.path.read_text())
        self.assertIn("proof: ran x: 0 failures", self.cli("show").stdout)
        self.cli("todo", "Next")
        self.assertEqual(self.data()["done"], [entry])
        self.cli("now", "Next")
        before = self.path.read_bytes()
        self.assertNotEqual(self.cli("done", "--proof", "two\nlines", check=False).returncode, 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.cli("now", "Last", "--done", "--proof", "/tmp/result")
        self.assertEqual(self.data()["done"][0], "Next — proof: /tmp/result")
        self.cli("done")
        self.assertEqual(self.data()["done"][0], "Last — unproven")

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

    def test_watch_owner_checks_at_most_once_per_second(self):
        self.init()
        calls = self.root / 'owner-checks'
        rex = self.root / 'rex'
        rex.write_text('#!' + sys.executable + '\nimport os, time\n'
                       + 'assert not any(k in os.environ for k in ("REX_SESSION", "REX_BLOCK", "REX_CLIENT", "REX_SERVER", "LC_REX_SESSION", "LC_REX_BLOCK"))\n'
                       + 'with open(' + repr(str(calls)) + ', "a") as stream: stream.write(str(time.time()) + "\\n")\n'
                       + 'print("live", end="")\n')
        rex.chmod(0o700)
        proc = subprocess.Popen([BIN, 'scratch', 'watch', '--socket', str(self.root / 'rex.sock')],
                                env=dict(self.env, TEEREX_INTERNAL_REX=str(rex)),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            end = time.monotonic() + 6
            while time.monotonic() < end:
                times = [float(v) for v in calls.read_text().splitlines()] if calls.exists() else []
                if len(times) >= 3:
                    break
                self.assertIsNone(proc.poll())
                time.sleep(.03)
            self.assertGreaterEqual(len(times), 3)
            self.assertTrue(all(b - a >= 1 for a, b in zip(times, times[1:])), times)
        finally:
            proc.terminate()
            proc.wait(timeout=5)

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
        for value in ("Show scratchpad", "-- teerex-surface-action:teerex_scratch_show", "ctx.block_id", "--socket", "scratch", "watch"):
            self.assertIn(value, lua)
        self.assertNotEqual(self.cli("palette", "--file", str(path), "--socket", str(self.root / "none.sock"), check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
