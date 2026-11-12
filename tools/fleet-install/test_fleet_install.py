#!/usr/bin/env python3
"""Native disposable-HOME fleet contracts; SSH transport is explicitly controlled, not a personal host."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import fleet_install as fleet

MAC = platform.system() == "Darwin" and platform.machine() == "arm64"
SUPPORTED = MAC or (platform.system() == "Linux" and platform.machine() == "x86_64")
PLATFORM = "macos-arm64" if MAC else "linux-x86_64"
ARCHIVE_PLATFORM = "aarch64-macos" if MAC else "x86_64-linux"
OLD, NEW, BAD = "v9.7.1-test", "v9.7.2-test", "v9.7.3-test"


@unittest.skipUnless(SUPPORTED and os.getuid() != 0, "requires disposable supported non-root host")
class FleetContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_temp = tempfile.TemporaryDirectory(prefix="teerex-fleet-build-")
        cls.build = Path(cls.build_temp.name).resolve()
        cls.binaries = {}
        for tag, output in ((OLD, OLD[1:]), (NEW, NEW[1:]), (BAD, "wrong-version")):
            source = cls.build / (tag + ".c")
            source.write_text('#include <stdio.h>\n#include <string.h>\nint main(int n,char**v){if(n==2&&!strcmp(v[1],"--version")){puts("teerex ' + output + '");return 0;}puts("native fleet help fixture");return 0;}\n')
            binary = cls.build / tag
            subprocess.run(["/usr/bin/cc", str(source), "-o", str(binary)], check=True, capture_output=True)
            cls.binaries[tag] = binary.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.build_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teerex-fleet-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home with spaces"
        self.home.mkdir(mode=0o700)
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.root = self.home / ".local/opt/teerex-managed"
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + ":" + os.environ["PATH"])
        self.host = self.make_host("fixture", self.home)
        self.source = self.base / "assets"
        self.source.mkdir()
        for tag in (OLD, NEW, BAD):
            self.archive(tag)
        self.sentinels = {}
        for name in (".zshrc", ".profile", ".config/rex/init.lua", "manual-install/notes"):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep " + name)
            self.sentinels[path] = path.read_bytes()

    def tearDown(self):
        for path, contents in self.sentinels.items():
            self.assertEqual(path.read_bytes(), contents)
        self.assertFalse((self.home / ".teerex-fleet-install.lock").exists())
        if self.root.exists():
            self.assertFalse((self.root / ".installer-lock").exists())

    def make_host(self, name, home):
        return dict(name=name, host_id=name, transport="local", home=str(home), platform=PLATFORM,
                    socket=str(home / "unused.sock"), rex=str(home / "unused-rex"),
                    teerex=str(home / ".local/bin/teerex"), store=str(home / "unused-store"),
                    install=dict(expected_hostname=platform.node(), expected_user=pwd.getpwuid(os.getuid()).pw_name))

    def archive(self, tag, variant="normal"):
        name = "teerex-" + tag + "-" + ARCHIVE_PLATFORM + ".tar.gz"
        binary = self.binaries[tag]
        if variant == "wrong-architecture":
            binary = bytearray(binary)
            struct.pack_into("<I" if MAC else "<H", binary, 4 if MAC else 18, 0x01000007 if MAC else 183)
        files = [("teerex", binary), ("README.md", b"fixture"), ("RIGHTS.md", b"fixture rights")]
        if variant == "traversal":
            files.append(("../escape", b"no"))
        if variant == "duplicate":
            files.append(files[1])
        with tarfile.open(self.source / name, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
            for filename, data in files:
                member = tarfile.TarInfo(filename)
                member.size = len(data)
                if variant == "symlink" and filename == "README.md":
                    member.type, member.linkname, member.size = tarfile.SYMTYPE, "RIGHTS.md", 0
                    archive.addfile(member)
                else:
                    archive.addfile(member, io.BytesIO(data))
        hashes = self.source / "SHA256SUMS"
        lines = hashes.read_text().splitlines() if hashes.exists() else []
        lines = [line for line in lines if line.split()[-1] != name]
        lines.append(hashlib.sha256((self.source / name).read_bytes()).hexdigest() + "  " + name)
        hashes.write_text("\n".join(lines) + "\n")

    def call(self, tag=OLD, *, hosts=None, ok=True, **options):
        options = dict(version=tag, source=self.source, **options)
        with patch.dict(os.environ, self.env, clear=True):
            result = fleet.run_fleet(hosts or [self.host], options)
        self.assertEqual(result["ok"], ok, json.dumps(result, indent=2))
        return result

    def active(self, tag):
        self.assertEqual(os.readlink(self.root / "current"), "versions/" + tag)
        self.assertEqual(subprocess.check_output([str(self.root / "current/teerex"), "--version"], text=True).strip(), "teerex " + tag[1:])

    def request(self, tag=OLD, **options):
        installer = fleet.INSTALLER.read_bytes()
        return dict(phase="plan", host=self.host, version=tag, installer=base64.b64encode(installer).decode(),
                    installer_sha256=hashlib.sha256(installer).hexdigest(), **options)

    def test_cli_uses_shared_named_configuration(self):
        config = self.base / "targets.json"
        config.write_text(json.dumps(dict(schema_version=1, hosts={"fixture": {k: v for k, v in self.host.items() if k != "name"}})))
        command = [sys.executable, str(fleet.HERE / "fleet_install.py"), "install", "--config", str(config), "--host", "fixture", "--version", OLD]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["hosts"][0]["host_id"], "fixture")
        command[command.index("fixture")] = "unknown"
        failed = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("unknown configured host", json.loads(failed.stdout)["error"])
        self.assertFalse(self.root.exists())

    def test_plan_install_upgrade_repeat_and_explicit_rollback(self):
        plan = self.call(path_consent=True)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.bin / "teerex").exists())
        self.assertFalse(plan["applied"])
        self.assertEqual(plan["hosts"][0]["plan"]["action"], "install")
        installed = self.call(apply=True, path_consent=True)
        self.active(OLD)
        self.assertEqual(installed["hosts"][0]["verified_version"], "teerex " + OLD[1:])
        fixed = installed["hosts"][0]["verified_installation"]
        self.assertEqual(fixed["sha256"], hashlib.sha256(self.binaries[OLD]).hexdigest())
        self.assertEqual(Path(fixed["executable"]), self.root / "versions" / OLD / "teerex")
        self.call(NEW, apply=True, path_consent=True)
        self.active(NEW)
        self.assertTrue((self.root / "versions" / OLD).is_dir())
        repeated = self.call(NEW, apply=True, path_consent=True)
        self.assertEqual(repeated["hosts"][0]["plan"]["action"], "verify")
        self.call(OLD, operation="rollback", apply=True, path_consent=True)
        self.active(OLD)
        self.assertEqual(sorted(p.name for p in (self.root / "versions").iterdir()), [OLD, NEW])

    def test_manual_folder_and_launcher_are_preserved_with_explicit_consent(self):
        manual = self.home / ".local/opt/teerex"
        manual.mkdir(parents=True)
        original = manual / "teerex"
        original.write_bytes(self.binaries[OLD])
        original.chmod(0o700)
        launcher = self.bin / "teerex"
        launcher.symlink_to(original)
        self.call(apply=True, path_consent=True, ok=False)
        self.assertFalse(self.root.exists())
        plan = self.call(path_consent=True, replace_launcher=True)["hosts"][0]["plan"]
        receipt = self.call(apply=True, path_consent=True, replace_launcher=True)["hosts"][0]
        self.assertEqual(receipt["launcher_backup"], plan["launcher_backup"])
        self.assertEqual(os.readlink(receipt["launcher_backup"]), str(original))
        self.assertEqual(original.read_bytes(), self.binaries[OLD])
        self.assertEqual(set(p.name for p in manual.iterdir()), {"teerex"})
        self.active(OLD)

    def test_regular_manual_launcher_backup_and_unknown_root_refusal(self):
        launcher = self.bin / "teerex"
        launcher.write_bytes(b"unknown user file")
        self.root.mkdir(parents=True)
        sentinel = self.root / "user-notes"
        sentinel.write_text("keep")
        self.call(apply=True, path_consent=True, replace_launcher=True, ok=False)
        self.assertEqual(list(self.root.iterdir()), [sentinel])
        sentinel.unlink()
        self.root.rmdir()
        result = self.call(apply=True, path_consent=True, replace_launcher=True)
        self.assertEqual(Path(result["hosts"][0]["launcher_backup"]).read_bytes(), b"unknown user file")

    def test_path_consent_identity_and_path_boundary_fail_closed(self):
        self.env["PATH"] = os.environ["PATH"]
        self.call(apply=True, path_consent=True, ok=False)
        self.assertFalse(self.root.exists())
        # No PATH consent: installing by fixed path is permitted and does not create a launcher.
        self.call(apply=True)
        self.assertFalse(os.path.lexists(self.bin / "teerex"))
        self.host["install"]["expected_hostname"] = "wrong-host.invalid"
        self.call(NEW, apply=True, ok=False)
        self.active(OLD)
        self.host["install"]["expected_hostname"] = platform.node()
        self.host["platform"] = "linux-x86_64" if MAC else "macos-arm64"
        self.call(NEW, apply=True, ok=False)
        self.host["platform"] = PLATFORM
        linked = self.home / "linked"
        linked.symlink_to(self.home / ".local", target_is_directory=True)
        self.host["install"]["prefix"] = str(linked / "elsewhere")
        self.call(NEW, apply=True, ok=False)
        self.assertFalse((self.home / ".local/elsewhere").exists())

    def test_checksum_archive_architecture_and_changed_bytes_preserve_active(self):
        self.call(apply=True)
        sums = self.source / "SHA256SUMS"
        original = sums.read_text()
        sums.write_text("0" * 64 + "  teerex-" + NEW + "-" + ARCHIVE_PLATFORM + ".tar.gz\n")
        result = self.call(NEW, apply=True, ok=False)
        self.assertFalse(result["applied"])
        self.active(OLD)
        sums.write_text(original)
        for variant in ("traversal", "duplicate", "symlink", "wrong-architecture"):
            with self.subTest(variant=variant):
                self.archive(NEW, variant)
                failure = self.call(NEW, apply=True, ok=False)
                self.assertTrue(failure["hosts"][0]["rollback"]["ok"])
                self.active(OLD)
        (self.root / "versions" / OLD / "README.md").write_text("user edits")
        self.call(NEW, apply=True, ok=False)
        self.assertEqual(os.readlink(self.root / "current"), "versions/" + OLD)

    def test_version_mismatch_rolls_back_and_restores_manual_launcher(self):
        self.call(apply=True, path_consent=True)
        failure = self.call(BAD, apply=True, path_consent=True, ok=False)["hosts"][0]
        self.assertTrue(failure["rollback"]["ok"])
        self.active(OLD)
        self.assertTrue((self.root / "versions" / BAD).exists())
        # First-install mismatch returns to inactive, retaining an unrelated manual launcher.
        other = self.base / "other-home"
        other.mkdir(mode=0o700)
        (other / ".local/bin").mkdir(parents=True)
        launcher = other / ".local/bin/teerex"
        launcher.write_text("preserve")
        self.env.update(HOME=str(other), PATH=str(launcher.parent) + ":" + os.environ["PATH"])
        host = self.make_host("other", other)
        result = self.call(BAD, hosts=[host], apply=True, path_consent=True, replace_launcher=True, ok=False)
        self.assertTrue(result["hosts"][0]["rollback"]["ok"])
        self.assertEqual(launcher.read_text(), "preserve")
        self.assertFalse(os.path.lexists(other / ".local/opt/teerex-managed/current"))

    def test_path_shadow_failure_restores_replaced_launcher_and_deactivates(self):
        shadow = self.home / "earlier-bin"
        shadow.mkdir()
        (shadow / "teerex").write_bytes(self.binaries[NEW])
        (shadow / "teerex").chmod(0o700)
        launcher = self.bin / "teerex"
        launcher.write_text("manual executable placeholder")
        launcher.chmod(0o700)
        self.env["PATH"] = str(shadow) + ":" + self.env["PATH"]
        result = self.call(apply=True, path_consent=True, replace_launcher=True, ok=False)["hosts"][0]
        self.assertIn("shadows", result["error"])
        self.assertTrue(result["rollback"]["ok"])
        self.assertEqual(launcher.read_text(), "manual executable placeholder")
        self.assertFalse(launcher.is_symlink())
        self.assertFalse(os.path.lexists(self.root / "current"))
        self.assertEqual(list(self.bin.glob("teerex.before-fleet-*")), [])

    def test_stale_plan_and_busy_refuse_without_installing(self):
        request = self.request(path_consent=True, replace_launcher=True)
        with patch.dict(os.environ, self.env, clear=True):
            plan = fleet.invoke(self.host, request)["plan"]
            (self.bin / "teerex").write_text("new user file")
            result = fleet.invoke(self.host, dict(request, phase="apply", plan=plan, assets=fleet.bundle(plan, self.source)))
        self.assertFalse(result["ok"])
        self.assertEqual((self.bin / "teerex").read_text(), "new user file")
        self.assertFalse(self.root.exists())
        (self.bin / "teerex").unlink()
        self.call(apply=True)
        (self.root / ".installer-lock").mkdir()
        self.call(NEW, apply=True, ok=False)
        (self.root / ".installer-lock").rmdir()
        self.active(OLD)

    def controlled_ssh(self):
        transport_bin = self.base / "transport-bin"
        transport_bin.mkdir()
        script = transport_bin / "ssh"
        # Deliberately not SSH authentication: execute exactly the quoted remote command
        # through a controlled process and set each disposable host's HOME/PATH.
        script.write_text('#!' + sys.executable + '\nimport json,os,subprocess,sys\nr=json.load(sys.stdin)\nh=r["host"]\ne=dict(os.environ,HOME=h["home"],PATH=h["home"]+"/.local/bin:"+os.environ["PATH"])\nif r["phase"]=="apply" and h["name"]==os.environ.get("FLEET_TEST_DROP"): sys.exit(255)\np=subprocess.run(["/bin/sh","-c",sys.argv[-1]],input=json.dumps(r),text=True,env=e)\nsys.exit(p.returncode)\n')
        script.chmod(0o700)
        self.env["PATH"] = str(transport_bin) + ":" + self.env["PATH"]
        hosts = []
        key, known = self.base / "fixture-key", self.base / "known_hosts"
        key.write_text("controlled-transport-not-a-credential")
        known.write_text("controlled-transport-not-a-host-key")
        for name in ("m5", "hive", "m1"):
            home = self.base / name
            home.mkdir(mode=0o700)
            (home / ".local/bin").mkdir(parents=True)
            host = self.make_host(name, home)
            host.update(transport="ssh", address=pwd.getpwuid(os.getuid()).pw_name + "@fixture.invalid", port=2222,
                        identity_file=str(key), known_hosts=str(known))
            hosts.append(host)
        return hosts

    def test_three_named_hosts_strict_transport_and_partial_failure(self):
        hosts = self.controlled_ssh()
        args = fleet.transport_argv(hosts[0])
        for setting in ("StrictHostKeyChecking=yes", "BatchMode=yes", "IdentitiesOnly=yes", "ForwardAgent=no", "GlobalKnownHostsFile=/dev/null"):
            self.assertIn(setting, args)
        self.assertEqual(args[args.index("-F") + 1], "/dev/null")
        self.env["FLEET_TEST_DROP"] = "hive"
        result = self.call(hosts=hosts, apply=True, path_consent=True, ok=False)
        self.assertTrue(result["hosts"][0]["ok"])
        self.assertEqual(result["hosts"][1]["outcome"], "unknown")
        self.assertEqual(result["hosts"][2]["outcome"], "skipped_after_failure")
        self.assertTrue((Path(hosts[0]["home"]) / ".local/bin/teerex").is_symlink())
        self.assertFalse((Path(hosts[2]["home"]) / ".local/opt/teerex-managed").exists())
        del self.env["FLEET_TEST_DROP"]
        completed = self.call(hosts=hosts, apply=True, path_consent=True)
        self.assertEqual([h["verified_version"] for h in completed["hosts"]], ["teerex " + OLD[1:]] * 3)

    def test_all_host_preflight_stops_any_mutation(self):
        hosts = self.controlled_ssh()
        hosts[1]["install"]["expected_user"] = "wrong-user"
        result = self.call(hosts=hosts, apply=True, path_consent=True, ok=False)
        self.assertFalse(result["applied"])
        for host in hosts:
            self.assertFalse((Path(host["home"]) / ".local/opt/teerex-managed").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
