"""Check the public command surface without contacting Rex."""
import os
from pathlib import Path
import subprocess
import unittest


BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[1] / "zig-out/bin/teerex")).resolve())


class HelpTest(unittest.TestCase):
    def call(self, *args):
        return subprocess.run([BIN, *args], capture_output=True, text=True, timeout=10)

    def test_root_and_retained_help(self):
        for args, expected in ((("--help",), "clutch take|release|status|queue|drain"),
                               (("send", "--help"), "teerex send"),
                               (("clutch", "--help"), "teerex clutch")):
            with self.subTest(args=args):
                result = self.call(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)

    def test_removed_commands_and_selectors_are_unknown(self):
        for verb in ("surfaces", "observe", "watch", "compare", "records", "recovery", "snapshot",
                     "restore", "update", "fleet", "targets", "--config", "--host"):
            with self.subTest(verb=verb):
                result = self.call(verb)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("unknown command", result.stderr)
        for verb in ("palette", "prune"):
            with self.subTest(verb=verb):
                self.assertEqual(self.call("clutch", verb).returncode, 2)


if __name__ == "__main__":
    unittest.main()
