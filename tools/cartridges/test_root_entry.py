"""Embedded manager parity; every command uses disposable HOME."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import unittest

from test_cartridges import CLI, Lifecycle

BIN = Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve()


class RootEntry(Lifecycle):
    def parity(self, argv):
        direct = subprocess.run([sys.executable, "-I", str(CLI), "--root", str(self.root), *argv], env=self.env, capture_output=True)
        root = subprocess.run([str(BIN), "cartridges", "--root", str(self.root), *argv], env=self.env, capture_output=True)
        self.assertEqual(root.returncode, direct.returncode)
        for actual, expected in ((root.stdout, direct.stdout), (root.stderr, direct.stderr)):
            if actual.startswith(b"usage:"):
                # argparse aligns continuation lines to the length of prog.
                actual = re.sub(rb"(?m)^ +", b"", actual.replace(b"teerex cartridges", b"cartridges.py"))
                expected = re.sub(rb"(?m)^ +", b"", expected)
            self.assertEqual(actual, expected)
        self.assertNotIn(b"Usage: teerex observe", root.stderr)

    def test_root_parity(self):
        self.package("alpha", status="experimental")
        cases = [("--help",), ("install", "--help"), (), ("--unknown",), ("list",),
                 ("install", "--all", "--catalog", str(self.catalog)),
                 ("install", "alpha", "--catalog", str(self.catalog)),
                 ("install", "alpha", "--catalog", str(self.catalog), "--allow-experimental")]
        for argv in cases:
            with self.subTest(argv=argv):
                before = self.snapshot()
                self.parity(argv)
                self.assertEqual(self.snapshot(), before)
        self.install("alpha", extra=["--allow-experimental"])
        for argv in (("install", "alpha", "--catalog", str(self.catalog), "--allow-experimental", "--apply"),
                     ("list",), ("run", "alpha", "--", "literal ; $(false) α", ""),
                     ("remove", "alpha", "--version", "1.0.0"),
                     ("remove", "alpha", "--version", "1.0.0", "--deactivate")):
            self.parity(argv)
        self.invoke("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply")
        self.parity(("restore", "alpha", "--version", "1.0.0"))

    def test_exec_pid_environment_exit_and_signal_passthrough(self):
        self.package("alpha", code='#!/bin/sh\nprintf "%s\\n%s\\n" "$$" "$CUSTOM_ENTRY_TEST"\nprintf "payload stderr\\n" >&2\nexit 23\n')
        self.install("alpha")
        process = subprocess.Popen([str(BIN), "cartridges", "--root", str(self.root), "run", "alpha"],
                                   env=dict(self.env, CUSTOM_ENTRY_TEST="literal ; α"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, error = process.communicate(timeout=10)
        self.assertEqual(out, str(process.pid) + "\nliteral ; α\n")
        self.assertEqual(error, "payload stderr\n")
        self.assertEqual(process.returncode, 23)
        self.package("beta", code='#!/bin/sh\nkill -TERM "$$"\n')
        self.install("beta")
        result = subprocess.run([str(BIN), "cartridges", "--root", str(self.root), "run", "beta"], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, -15)
        self.assertEqual((result.stdout, result.stderr), (b"", b""))

    def test_python_missing_and_named_host_refuse(self):
        empty = self.home / "empty-path"
        empty.mkdir()
        for argv, env in ((["cartridges", "list"], dict(self.env, PATH=str(empty))),
                          (["--config", "/absent", "--host", "remote", "cartridges", "list"], self.env)):
            before = self.snapshot()
            result = subprocess.run([str(BIN), *argv], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            error = json.loads(result.stderr)
            self.assertFalse(error["ok"])
            self.assertEqual(error["schema_version"], 1)
            self.assertTrue(error["next_step"])
            self.assertEqual(self.snapshot(), before)

    def test_help_and_isolation(self):
        result = subprocess.run([str(BIN), "--help"], env=self.env, capture_output=True, text=True)
        self.assertIn("cartridges install|list|run|activate|remove|restore", result.stdout)
        self.assertIn("cartridges doctor|repair", result.stdout)
        (self.home / "json.py").write_text('raise RuntimeError("cwd module executed")')
        result = subprocess.run([str(BIN), "cartridges", "list"], cwd=self.home,
                                env=dict(self.env, PYTHONPATH=str(self.home)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["active"], {})


if __name__ == "__main__":
    # Only run inherited lifecycle cases once, through the embedded entry.
    import test_cartridges
    test_cartridges.PREFIX = [str(BIN), "cartridges"]
    unittest.main(defaultTest="RootEntry")
