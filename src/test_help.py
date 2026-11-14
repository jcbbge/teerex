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
    def test_root_help_points_agents_to_current_guide(self):
        result = subprocess.run([BIN, "--help"], env=isolated_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Guides: docs/agents.md", result.stdout)
        self.assertNotIn("docs/alpha5.md", result.stdout)
        self.assertIn("seat register|resolve|inspect|clear", result.stdout)

    def test_agents_command_is_unknown(self):
        result = subprocess.run([BIN, "agents"], env=isolated_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown command", (result.stdout + result.stderr).lower())
        help_result = subprocess.run([BIN, "run-visible", "--help"], env=isolated_environment(),
                                     capture_output=True, text=True, timeout=10)
        self.assertEqual(help_result.returncode, 0)
        self.assertNotIn("--channel-dir", help_result.stdout)

    def test_seat_help_lists_resolve(self):
        result = subprocess.run([BIN, "seat", "--help"], env=isolated_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("{register,resolve,inspect,clear}", result.stdout)

    def test_embedded_python_help_uses_public_command_names(self):
        commands = [
            ("records",), ("replay",), ("mcp",),
            ("recovery",), ("targets",),
            ("targets", "resolve"), ("targets", "exec"),
            ("cartridges",), ("run-visible",), ("run-visible", "receipt"),
            ("observe", "--state"), ("clutch", "palette"),
            ("surfaces", "palette", "install"),
            ("surfaces", "palette", "agents"), ("surfaces", "palette", "hosts"),
            ("boards", "inbox"), ("boards", "fleet"), ("boards", "calls"),
            ("boards", "probe"), ("boards", "state", "inspect"),
            ("boards", "friction"), ("ask",),
            ("fleet", "install"), ("fleet", "rollback"),
        ]
        commands += [("scratch", op) for op in ("init", "now", "todo", "done", "show", "path", "watch", "hook", "hook-settings")]
        commands += [("records", op) for op in (
            "init", "new", "park", "add", "attach", "set", "close", "show",
            "resume", "navigate", "list", "lint", "export", "forget", "pin",
            "decide", "claim-status", "revalidate")]
        commands += [("boards", "friction", op) for op in (
            "enable", "disable", "status", "forget", "label", "report")]
        commands += [("recovery", op) for op in ("snapshot", "restore", "update", "inspect")]
        commands += [("cartridges", op) for op in (
            "install", "activate", "remove", "restore", "list", "doctor", "repair", "run")]
        commands += [("replay", op) for op in ("record", "play", "live")]
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
