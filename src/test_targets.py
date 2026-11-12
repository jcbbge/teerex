"""Public named-host/version checks; fixtures never contact a personal host."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import unittest

BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[1] / "zig-out/bin/teerex"))


class TargetsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="teerex-targets-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.output = self.root / "observed.json"
        executable = self.root / "teerex fixture"
        executable.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
                              + "Path(" + repr(str(self.output)) + ").write_text(json.dumps(sys.argv[1:]))\nsys.exit(7)\n")
        executable.chmod(0o700)
        self.host = {"host_id": "fixture", "transport": "local", "home": str(self.root),
                     "platform": "linux-x86_64", "socket": str(self.root / "selected socket"),
                     "rex": str(self.root / "pinned rex"), "teerex": str(executable), "store": str(self.root / "private store")}
        self.config = self.root / "hosts.json"
        self.save()

    def save(self):
        self.config.write_text(json.dumps({"schema_version": 1, "hosts": {"hive": self.host}}))

    def call(self, *args):
        return subprocess.run([str(BIN), *args], capture_output=True, text=True, timeout=10,
                              env=dict(os.environ, REX_SERVER="unix:///poisoned", REX_SESSION="wrong"))

    def test_version_and_explicit_resolution(self):
        version = self.call("--version")
        self.assertEqual((version.returncode, version.stdout, version.stderr), (0, "teerex 0.1.0-alpha.5\n", ""))
        resolved = self.call("targets", "resolve", "--config", str(self.config), "--host", "hive")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        result = json.loads(resolved.stdout)
        self.assertEqual(result["host"], dict(self.host, name="hive"))
        self.assertEqual(result["identity_basis"], "explicit_configuration_not_observed_identity")
        self.assertFalse(self.output.exists())

    def test_unknown_host_conflicting_target_and_duplicate_key_do_not_execute(self):
        for extra in (("--host", "absent", "observe"),
                      ("--host", "hive", "observe", "--socket", "/explicit")):
            result = self.call("--config", str(self.config), *extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.output.exists())
        self.config.write_text('{"schema_version":1,"schema_version":1,"hosts":{}}')
        result = self.call("targets", "resolve", "--config", str(self.config), "--host", "hive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate config key", result.stderr)

    def test_selected_host_literal_argv_status_and_no_secret_receipt(self):
        secret = "literal ; touch " + str(self.root / "MUST_NOT_EXIST") + " $(false) α"
        result = self.call("--config", str(self.config), "--host", "hive", "spawn", "--session", "session:test", "--", "sh", "-c", secret)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(self.output.read_text()), ["--rex", self.host["rex"], "spawn", "--socket", self.host["socket"], "--session", "session:test", "--", "sh", "-c", secret])
        self.assertFalse((self.root / "MUST_NOT_EXIST").exists())
        self.assertNotIn(secret, result.stderr)
        receipt = json.loads(result.stderr)
        self.assertEqual(receipt["host_id"], "fixture")
        self.assertIs(receipt["retry"], False)

    def test_named_seat_send_appends_once_and_corrupt_store_never_falls_back(self):
        store = Path(self.host["store"])
        store.mkdir(mode=0o700)
        self.host["teerex"] = str(BIN.resolve())
        self.save()
        target = ["--session", "session:12345678-1234-1234-1234-123456789abc",
                  "--block", "block:abcdef12-1234-1234-1234-123456789abc"]
        prefix = [str(BIN), "--config", str(self.config), "--host", "hive"]
        register = subprocess.run([*prefix, "seat", "register", *target, "--owner", "operator"], capture_output=True, text=True, timeout=5)
        self.assertEqual(register.returncode, 0, register.stderr)
        message = "exact α\noperator draft stays untouched\n\n"
        sent = subprocess.run([*prefix, "send", *target, "--from", "worker", "--message-file", "-", "--timeout-ms", "500"], input=message, capture_output=True, text=True, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        receipt = json.loads(sent.stdout)
        self.assertEqual(receipt["outcome"], "recorded")
        self.assertIs(receipt["terminal_input_attempted"], False)
        state = json.loads((store / "state.json").read_text())
        self.assertEqual([r["body"] for r in state["seats"][0]["records"]], [message])
        (store / "state.json").write_text("corrupt")
        sent = subprocess.run([*prefix, "send", *target, "--from", "worker", "--message-file", "-"], input=message, capture_output=True, text=True, timeout=5)
        self.assertEqual(sent.returncode, 1, sent.stderr)
        self.assertNotIn("explicit Rex executable", sent.stdout)
        self.assertIs(json.loads(sent.stdout)["terminal_input_attempted"], False)
        self.assertEqual((store / "state.json").read_text(), "corrupt")

    def test_embedded_fleet_installs_exact_native_bytes_without_source_tree(self):
        # The installed CLI must carry its reviewed support files, not locate this checkout.
        mac = platform.system() == "Darwin"
        tag = "v0.1.0-alpha.5"
        archive_platform = "aarch64-macos" if mac else "x86_64-linux"
        assets = self.root / "assets"
        assets.mkdir()
        archive = assets / ("teerex-" + tag + "-" + archive_platform + ".tar.gz")
        with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
            for name, data in (("teerex", BIN.read_bytes()), ("README.md", b"test release"), ("RIGHTS.md", b"test rights")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o700 if name == "teerex" else 0o600
                tar.addfile(info, io.BytesIO(data))
        (assets / "SHA256SUMS").write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")
        prefix = self.root / "managed"
        self.host.update(home=str(self.root), platform="macos-arm64" if mac else "linux-x86_64",
                         install={"prefix": str(prefix)})
        self.save()
        env = dict(os.environ, HOME=str(self.root))
        args = ["fleet", "install", "--config", str(self.config), "--host", "hive", "--version", tag, "--from", str(assets)]
        def invoke(binary, *extra):
            result = subprocess.run([str(binary), *args, *extra], cwd=self.root, env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        self.assertFalse(invoke(BIN)["applied"])
        self.assertFalse(prefix.exists())
        applied = invoke(BIN, "--apply")
        self.assertTrue(applied["ok"])
        installed = prefix / "current/teerex"
        self.assertEqual(installed.read_bytes(), BIN.read_bytes())
        self.assertEqual(subprocess.check_output([str(installed), "--version"], text=True), "teerex 0.1.0-alpha.5\n")
        # Executed away from source, this re-plans using only its embedded support bytes.
        self.assertTrue(invoke(installed)["ok"])
        self.assertFalse((self.root / "MUST_NOT_RUN").exists())

    def test_explicit_rex_pin_ignores_poisoned_path_without_retry(self):
        poison = self.root / "rex"
        poison.write_text("#!/bin/sh\nprintf poisoned > " + str(self.root / "MUST_NOT_RUN") + "\nexit 0\n")
        poison.chmod(0o700)
        pinned = self.root / "custom rex"
        pinned.write_text("#!/bin/sh\nprintf 'PINNED_DIAGNOSTIC' >&2\nexit 7\n")
        pinned.chmod(0o700)
        command = [str(BIN), "--rex", str(pinned), "observe", "--socket", "/not-contacted.sock",
                   "--session", "session:12345678-1234-1234-1234-123456789abc",
                   "--block", "block:abcdef12-1234-1234-1234-123456789abc"]
        result = subprocess.run(command, env=dict(os.environ, PATH=str(self.root)), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PINNED_DIAGNOSTIC", result.stderr)
        self.assertIn(str(pinned), result.stderr)
        self.assertFalse((self.root / "MUST_NOT_RUN").exists())

    def test_ssh_requires_explicit_pretrusted_fields_before_launch(self):
        self.host.update(transport="ssh", address="-oProxyCommand=evil", port=22)
        self.save()
        result = self.call("--config", str(self.config), "--host", "hive", "observe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("literal SSH destination", result.stderr)
        self.assertFalse(self.output.exists())
        self.host["address"] = "operator@example.invalid"
        self.save()
        result = self.call("targets", "resolve", "--config", str(self.config), "--host", "hive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("known_hosts", result.stderr)


if __name__ == "__main__":
    unittest.main()
