"""Public help names for every embedded Python controller; no Rex or real stores."""
import os
import sys
from pathlib import Path
import subprocess
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/acceptance'))
import test_resources as resources

from test_environment import isolated_environment

BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[1] / "zig-out/bin/teerex")).resolve())


class PythonHelpTest(unittest.TestCase):
    def test_root_help_describes_rex_utilities(self):
        result = subprocess.run([BIN, "--help"], env=isolated_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Guides: docs/usage.md", result.stdout)
        self.assertNotIn("docs/alpha5.md", result.stdout)
        self.assertNotIn("agent", result.stdout.lower())

    def test_scratch_command_is_unknown(self):
        result = subprocess.run([BIN, "scratch", "--help"], env=isolated_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown command", (result.stdout + result.stderr).lower())

    def test_agents_command_is_unknown(self):
        result = subprocess.run([BIN, "agents"], env=isolated_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown command", (result.stdout + result.stderr).lower())

    def test_retired_commands_are_unknown(self):
        for command in ("tour", "cartridges", "mcp", "replay", "adapters", "maneuver-check",
                        "filter", "offstage", "spawn", "waiting", "board", "boardfeed",
                        "jobs", "log", "docs", "doctor", "run", "run-visible"):
            with self.subTest(command=command):
                result = subprocess.run([BIN, command], env=isolated_environment(),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("unknown", result.stdout + result.stderr)
        result = subprocess.run([BIN, "surfaces", "palette"], env=isolated_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unknown subcommand", result.stdout + result.stderr)

    def test_removed_boards_commands_are_unknown(self):
        for command in ("boards", "seat", "ask", "inbox"):
            with self.subTest(command=command):
                result = subprocess.run([BIN, command], env=isolated_environment(),
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unknown command", (result.stdout + result.stderr).lower())

    def test_embedded_python_help_uses_public_command_names(self):
        commands = [
            ("records",),
            ("recovery",), ("targets",),
            ("targets", "resolve"), ("targets", "exec"),
            ("observe", "--state"), ("clutch", "palette"),
            ("fleet", "install"), ("fleet", "rollback"),
        ]
        commands += [("records", op) for op in (
            "init", "new", "park", "add", "attach", "set", "close", "show",
            "resume", "navigate", "list", "lint", "export", "forget", "pin",
            "decide", "claim-status", "revalidate")]
        commands += [("recovery", op) for op in ("snapshot", "restore", "update", "inspect")]
        with resources.temporary_directory(prefix="teerex-help-") as temp:
            env = dict(isolated_environment(), HOME=temp, XDG_CONFIG_HOME=temp,
                       XDG_STATE_HOME=temp, TEEREX_CALL_LOG_DIR=str(Path(temp) / "calls"),
                       REX_SERVER="unix:///no-server-help-test", REX_SESSION="poison", REX_BLOCK="poison")
            for command in commands:
                with self.subTest(command=" ".join(command)):
                    result = subprocess.run([BIN, *command, "--help"], env=env,
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertTrue(result.stdout.startswith("usage: teerex "), result.stdout)
                    self.assertNotIn("usage: -c", result.stdout + result.stderr)
                    self.assertNotIn("fleet_install.py", result.stdout + result.stderr)
                    if command[:1] == ("records",):
                        self.assertTrue(result.stdout.startswith("usage: teerex " + " ".join(command)), result.stdout)


if __name__ == "__main__":
    unittest.main()
