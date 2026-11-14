"""Tour lifecycle checks on a disposable Rex, with real public commands."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[1] / "zig-out/bin/teerex")).resolve())


class TourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="tour-test-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.socket = str(cls.root / "rex.sock")
        config = cls.root / "init.lua"
        config.write_text("")
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        cls.log = (cls.root / "rex.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + cls.socket,
                                      "--restore=false", "--config", str(config),
                                      "--state-dir", str(cls.root / "state")], stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop)
        while not Path(cls.socket).exists():
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "rex.log").read_text())
            time.sleep(.05)

    @classmethod
    def stop(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)

    @classmethod
    def rpc(cls, method, **args):
        return json.loads(subprocess.check_output([cls.rex, "--autostart=false", "--server", "unix://" + cls.socket,
                                                  "api", "call", method, json.dumps(args)], text=True))

    def run_tour(self, answers):
        session = self.rpc("session.create", label="tour test")["session_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", session_id=session))
        before = self.rpc("session.list_blocks", session_id=session)
        result = subprocess.run([BIN, "tour", "--socket", self.socket, "--session", session],
                                input=answers, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.rpc("session.list_blocks", session_id=session)
        self.assertEqual(after, before, result.stdout)
        scratch = Path.home() / ".local/state/teerex/scratch" / session
        self.assertFalse(scratch.exists(), str(scratch))
        return result.stdout

    def test_complete_and_cleanup(self):
        output = self.run_tour("\n" * 6)
        self.assertIn("Tour complete", output)
        self.assertEqual(output.count("Closed and verified absent:"), 3)
        self.assertIn("Scratchpad task moved from Now to Done", output)
        self.assertIn("Sent: Hello from the tour!", output)

    def test_quit_at_step_three(self):
        output = self.run_tour("\n\nq\n")
        self.assertIn("3/6", output)
        self.assertNotIn("4/6", output)
        self.assertEqual(output.count("Closed and verified absent:"), 1)

    def test_eof_cleans_up(self):
        output = self.run_tour("\n")
        self.assertIn("Tour stopped", output)
        self.assertEqual(output.count("Closed and verified absent:"), 1)

    def test_quit_with_all_practice_panes_open(self):
        output = self.run_tour("\n" * 5 + "q\n")
        self.assertEqual(output.count("Closed and verified absent:"), 3)
        self.assertNotIn("Tour complete", output)


if __name__ == "__main__":
    unittest.main()
