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
        self.assertEqual(set(self.data()), {"purpose", "intent", "now", "todo", "done", "updated"})

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
