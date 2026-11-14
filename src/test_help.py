"""Public help names for every embedded Python controller; no Rex or real stores."""
import os
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/acceptance'))
from test_environment import isolated_environment

BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[1] / "zig-out/bin/teerex")).resolve())


class PythonHelpTest(unittest.TestCase):
    def test_embedded_python_help_uses_public_command_names(self):
        commands = [
            ("records",), ("replay",), ("mcp",), ("agents",),
            ("agents", "fence-probe"), ("recovery",), ("targets",),
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
        commands += [("agents", op) for op in (
            "profiles", "shell", "exec", "channel", "hook", "launch", "human", "prune",
            "ack", "deliver", "inspect", "present", "stop", "supervise", "exited")]
        commands += [("cartridges", op) for op in (
            "install", "activate", "remove", "restore", "list", "doctor", "repair", "run")]
        commands += [("replay", op) for op in ("record", "play", "live")]
        with tempfile.TemporaryDirectory(prefix="teerex-help-") as temp:
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
