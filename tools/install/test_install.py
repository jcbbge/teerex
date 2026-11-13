#!/usr/bin/env python3
"""Public installer contract tests; never uses a personal installation or Rex.

Fixture archives contain a tiny native --help stub, not a teerex feature build.
Pass --public to additionally download and install the real alpha.1 release.
"""
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest


INSTALLER = Path(__file__).with_name("teerex-install").resolve()
MAC = platform.system() == "Darwin" and platform.machine() == "arm64"
LINUX = platform.system() == "Linux" and platform.machine() == "x86_64"
SUPPORTED = MAC or LINUX
ASSET_PLATFORM = "aarch64-macos" if MAC else "x86_64-linux"
PUBLIC = "--public" in sys.argv
if PUBLIC:
    sys.argv.remove("--public")
OLD = "v9.8.7-alpha.1"
NEW = "v9.8.8-beta.2"


def fixture_compiler():
    if "CC" in os.environ:
        command = shlex.split(os.environ["CC"])
        if not command:
            raise RuntimeError("CC is set but empty; select a C compiler for fixture builds")
        return command
    for name in ("cc", "clang"):
        compiler = shutil.which(name)
        if compiler:
            return [compiler]
    if importlib.util.find_spec("ziglang") is not None:
        return [sys.executable, "-m", "ziglang", "cc"]
    raise RuntimeError("Fixture builds require CC, cc/clang on PATH, or an importable ziglang package")


class PlatformContract(unittest.TestCase):
    def test_help_and_unsupported_platform(self):
        result = subprocess.run(["/bin/bash", str(INSTALLER), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cartridges", result.stdout)
        if not SUPPORTED:
            result = subprocess.run(["/bin/bash", str(INSTALLER), "install", "--version", OLD], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported hosts", result.stderr)


@unittest.skipUnless(SUPPORTED, "requires disposable Darwin arm64 or Linux x86_64")
class Lifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = fixture_compiler()
        cls.build_temp = tempfile.TemporaryDirectory(prefix="teerex-installer-stubs-")
        build = Path(cls.build_temp.name)
        cls.binaries = {}
        for label, status in (("old", 0), ("new", 0), ("broken", 17)):
            source = build / (label + ".c")
            source.write_text('#include <stdio.h>\n#include <stdlib.h>\nint main(void) { '
                              'const char *probe = getenv("TEEREX_INSTALL_EXEC_PROBE"); '
                              'if (probe) { FILE *f = fopen(probe, "a"); if (f) { fputs("executed\\n", f); fclose(f); } } '
                              'puts("installer fixture ' + label + '"); return ' + str(status) + '; }\n')
            binary = build / label
            subprocess.run([*compiler, str(source), "-o", str(binary)], check=True, capture_output=True)
            cls.binaries[label] = binary.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.build_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="teerex-installer-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.prefix = self.home / "space in path" / "teerex"
        self.env = dict(os.environ, HOME=str(self.home))
        self.sentinels = {}
        for name in (".zshrc", ".zprofile", ".config/rex/init.lua", ".local/bin/teerex"):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("user-owned " + name + "\n")
            self.sentinels[path] = path.read_bytes()
        self.old_source = self.archive(OLD, "old")
        self.new_source = self.archive(NEW, "new")

    def tearDown(self):
        for path, original in self.sentinels.items():
            self.assertEqual(path.read_bytes(), original, str(path))
        if self.prefix.exists():
            self.assertFalse((self.prefix / ".installer-lock").exists())
            self.assertEqual(list(self.prefix.glob(".stage.*")), [])

    def archive(self, tag, label, variant="regular"):
        source = self.home / ("download-" + tag + "-" + variant)
        source.mkdir(exist_ok=True)
        name = "teerex-" + tag + "-" + ASSET_PLATFORM + ".tar.gz"
        archive = source / name
        entries = [("teerex", self.binaries[label]), ("README.md", ("fixture " + label).encode()), ("RIGHTS.md", b"fixture rights")]
        if variant == "wrong-architecture":
            foreign = bytearray(self.binaries[label])
            if MAC:
                struct.pack_into("<I", foreign, 4, 0x01000007)  # x86_64, not arm64
            else:
                struct.pack_into("<H", foreign, 18, 183)  # AArch64, not x86_64
            entries[0] = ("teerex", bytes(foreign))
        if variant == "script":
            entries[0] = ("teerex", b"#!/bin/sh\nexit 0\n")
        if variant == "traversal":
            entries.append(("../escaped", b"must not extract"))
        if variant == "extra":
            entries.append(("extra.txt", b"must not extract"))
        if variant == "duplicate":
            entries.append(entries[0])
        with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as output:
            for filename, data in entries:
                member = tarfile.TarInfo(filename)
                member.mode = 0o755 if filename == "teerex" else 0o644
                member.size = len(data)
                if variant in ("symlink", "hardlink") and filename == "README.md":
                    member.type = tarfile.SYMTYPE if variant == "symlink" else tarfile.LNKTYPE
                    member.linkname = "RIGHTS.md"
                    member.size = 0
                    output.addfile(member)
                else:
                    output.addfile(member, io.BytesIO(data))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (source / "SHA256SUMS").write_text(digest + "  " + name + "\n")
        return source

    def call(self, command, tag=None, source=None, *, ok=True, extra=(), prefix=None):
        args = ["/bin/bash", str(INSTALLER), command, "--prefix", str(prefix or self.prefix)]
        if tag is not None:
            args += ["--version", tag]
        if source is not None:
            args += ["--from", str(source)]
        result = subprocess.run(args + list(extra), env=self.env, capture_output=True, text=True, timeout=120)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def snapshot(self):
        # Reads may update atime; no bytes, links, modes, ownership or mtimes may change.
        paths = [self.home] + sorted(self.home.rglob("*"))
        result = {}
        for path in paths:
            stat = path.lstat()
            try:
                data = os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None
            except PermissionError:
                data = "unreadable"  # Metadata still must remain identical.
            result[str(path)] = (stat.st_mode, stat.st_uid, stat.st_gid, stat.st_ino, stat.st_mtime_ns, data)
        return result

    def machine(self, command, tag=None, *, error=None, **kwargs):
        before = self.snapshot()
        result = self.call(command, tag, ok=error is None, **kwargs)
        self.assertEqual(self.snapshot(), before, "read-only command changed the filesystem")
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["operation"], command)
        self.assertIs(data["ok"], error is None)
        if error is not None:
            self.assertEqual(set(data), {"schema_version", "operation", "ok", "error"})
            self.assertEqual(data["error"]["code"], error)
            self.assertTrue(data["error"]["message"])
        return data

    def active(self, tag, label):
        self.assertEqual(os.readlink(self.prefix / "current"), "versions/" + tag)
        output = subprocess.check_output([str(self.prefix / "current" / "teerex"), "--help"], text=True)
        self.assertEqual(output.strip(), "installer fixture " + label)

    def test_install_upgrade_rollback_and_removal(self):
        self.call("install", OLD, self.old_source)
        self.active(OLD, "old")
        self.call("upgrade", NEW, self.new_source)
        self.active(NEW, "new")
        self.assertTrue((self.prefix / "versions" / OLD / "teerex").exists())
        self.assertEqual(sorted(p.name for p in (self.prefix / "versions").iterdir()), [OLD, NEW])
        self.call("rollback", OLD)
        self.active(OLD, "old")
        self.call("remove", NEW)
        self.assertFalse((self.prefix / "versions" / NEW).exists())
        self.call("remove", OLD, ok=False)
        self.active(OLD, "old")
        self.call("remove", OLD, extra=("--deactivate",))
        self.assertFalse((self.prefix / "current").is_symlink())
        self.assertEqual(list((self.prefix / "versions").iterdir()), [])
        self.assertIn("Active: none", self.call("list").stdout)
        empty = self.machine("inspect")
        self.assertEqual(empty["state"], "managed")
        self.assertEqual(empty["installed_versions"], [])
        self.assertIsNone(empty["active_version"])
        self.machine("verify", OLD, error="invalid_release")
        self.call("upgrade", NEW, self.new_source, ok=False)
        (self.prefix / "versions").rmdir()
        (self.prefix / ".teerex-install-root").unlink()
        self.prefix.rmdir()

    def test_repeated_install_never_overwrites(self):
        self.call("install", OLD, self.old_source)
        original = (self.prefix / "versions" / OLD / "teerex").stat().st_ino
        self.call("install", OLD, self.new_source, ok=False)
        self.assertEqual((self.prefix / "versions" / OLD / "teerex").stat().st_ino, original)
        self.active(OLD, "old")

    def test_failed_upgrade_preserves_active(self):
        # A path resembling file(1)'s answer must not satisfy the binary check.
        self.prefix = self.home / ("Mach-O 64-bit executable arm64" if MAC else "ELF 64-bit LSB executable, x86-64,")
        self.call("install", OLD, self.old_source)
        for variant in ("extra", "duplicate", "traversal", "symlink", "hardlink", "wrong-architecture", "script"):
            with self.subTest(variant=variant):
                source = self.archive(NEW, "new", variant)
                self.call("upgrade", NEW, source, ok=False)
                self.active(OLD, "old")
                self.assertFalse((self.prefix / "versions" / NEW).exists())
                self.assertFalse((self.prefix / "escaped").exists())
        source = self.archive(NEW, "broken")
        self.assertIn("--help failed", self.call("upgrade", NEW, source, ok=False).stderr)
        self.active(OLD, "old")

    def test_bad_checksums_preserve_active(self):
        self.call("install", OLD, self.old_source)
        sums = self.new_source / "SHA256SUMS"
        original = sums.read_text()
        name = "teerex-" + NEW + "-" + ASSET_PLATFORM + ".tar.gz"
        for invalid in ("0" * 64 + "  " + name + "\n", original + original, "not-a-hash  " + name + "\n", "0" * 64 + "  unrelated.tar.gz\n"):
            with self.subTest(checksum=invalid[:20]):
                sums.write_text(invalid)
                self.call("upgrade", NEW, self.new_source, ok=False)
                self.active(OLD, "old")
        # Other assets do not cause their files to be read or checked.
        sums.write_text(original + "0" * 64 + "  unrelated.tar.gz\n")
        self.call("upgrade", NEW, self.new_source)
        self.active(NEW, "new")

    def test_failed_first_install_can_be_retried(self):
        self.call("install", NEW, self.home / "missing", ok=False)
        self.assertFalse((self.prefix / "current").is_symlink())
        self.call("install", OLD, self.old_source)
        self.active(OLD, "old")

    def test_unmanaged_roots_and_symlink_ancestors_are_untouched(self):
        self.prefix.mkdir(parents=True)
        sentinel = self.prefix / "teerex"
        sentinel.write_text("not yours")
        self.call("install", OLD, self.old_source, ok=False)
        self.assertEqual(list(self.prefix.iterdir()), [sentinel])
        real = self.home / "real"
        real.mkdir()
        link = self.home / "linked"
        link.symlink_to(real, target_is_directory=True)
        self.call("install", OLD, self.old_source, prefix=link / "install", ok=False)
        self.assertEqual(list(real.iterdir()), [])

    def test_modified_missing_extra_and_symlinked_files_are_preserved(self):
        self.call("install", OLD, self.old_source)
        self.call("upgrade", NEW, self.new_source)
        release = self.prefix / "versions" / OLD
        readme = release / "README.md"
        original = readme.read_bytes()
        readme.write_text("user notes")
        self.call("rollback", OLD, ok=False)
        self.call("remove", OLD, ok=False)
        self.assertEqual(readme.read_text(), "user notes")
        self.active(NEW, "new")
        readme.unlink()
        self.call("remove", OLD, ok=False)
        readme.symlink_to(release / "RIGHTS.md")
        self.call("remove", OLD, ok=False)
        self.assertTrue(readme.is_symlink())
        readme.unlink()
        readme.write_bytes(original)
        extra = release / ".user-notes"
        extra.write_text("keep")
        self.call("remove", OLD, ok=False)
        self.assertEqual(extra.read_text(), "keep")
        extra.unlink()
        self.call("remove", OLD)

    def test_current_collision_is_not_overwritten(self):
        self.call("install", OLD, self.old_source)
        current = self.prefix / "current"
        current.unlink()
        current.write_text("user-owned")
        self.call("upgrade", NEW, self.new_source, ok=False)
        self.assertEqual(current.read_text(), "user-owned")
        current.unlink()
        current.symlink_to(self.home)
        self.call("rollback", OLD, ok=False)
        self.assertEqual(os.readlink(current), str(self.home))

    def test_explicit_selection_and_home_boundary(self):
        for tag in (None, "latest", "../v0.1.0", "v1.2.3/../outside"):
            with self.subTest(tag=tag):
                self.call("install", tag, self.old_source, ok=False)
        for extra in (("--all",), ("--cartridge", "observe"), ("--deactivate",)):
            self.call("install", OLD, self.old_source, extra=extra, ok=False)
        for prefix in (self.home, self.home / ".." / "outside", self.home / "x" / "." / ".." / "y"):
            self.call("install", OLD, self.old_source, prefix=prefix, ok=False)
        self.assertFalse(self.prefix.exists())

    def test_existing_release_can_be_reactivated_after_deactivation(self):
        self.call("install", OLD, self.old_source)
        self.call("upgrade", NEW, self.new_source)
        self.call("remove", NEW, extra=("--deactivate",))
        self.call("rollback", OLD)
        self.active(OLD, "old")

    def test_lock_refuses_concurrent_mutation(self):
        self.call("install", OLD, self.old_source)
        lock = self.prefix / ".installer-lock"
        lock.mkdir()
        try:
            self.assertIn("installer lock", self.call("upgrade", NEW, self.new_source, ok=False).stderr)
            self.active(OLD, "old")
        finally:
            lock.rmdir()

    def test_inspect_absent_and_unmanaged_without_adoption(self):
        self.prefix = self.home / 'quote"-slash\\-tab\t-control\x01\x1f-雪' / "teerex"
        expected = {"schema_version": 1, "operation": "inspect", "ok": True,
                    "state": "absent", "root": str(self.prefix), "platform": ASSET_PLATFORM,
                    "active_version": None, "installed_versions": [], "busy": False, "reason": None}
        self.assertEqual(self.machine("inspect"), expected)
        self.machine("verify", OLD, error="missing_root")
        alias = self.home / "home-alias"
        alias.symlink_to(self.home, target_is_directory=True)
        self.env["HOME"] = str(alias)
        self.assertEqual(self.machine("inspect", prefix=alias / self.prefix.relative_to(self.home)), expected)
        self.env["HOME"] = str(self.home)
        self.prefix.mkdir(parents=True)
        (self.prefix / "manual-notes").write_text("leave alone")
        expected.update(state="unmanaged", reason="missing_marker")
        self.assertEqual(self.machine("inspect"), expected)
        self.machine("verify", OLD, error="unmanaged_root")
        (self.prefix / ".teerex-install-root").write_text("another-manager-v2\n")
        expected["reason"] = "unrecognized_marker"
        self.assertEqual(self.machine("inspect"), expected)
        self.machine("verify", OLD, error="unmanaged_root")
        self.call("install", OLD, self.old_source, ok=False)

    def test_machine_inventory_and_fixed_verified_selection_never_execute(self):
        self.prefix = self.home / 'quote"-slash\\-tab\t-雪' / "teerex"
        self.call("install", OLD, self.old_source)
        self.call("upgrade", NEW, self.new_source)
        probe = self.home / "must-not-execute"
        self.env["TEEREX_INSTALL_EXEC_PROBE"] = str(probe)
        data = self.machine("inspect")
        self.assertEqual(data, {"schema_version": 1, "operation": "inspect", "ok": True,
                              "state": "managed", "root": str(self.prefix), "platform": ASSET_PLATFORM,
                              "active_version": NEW, "installed_versions": [OLD, NEW], "busy": False, "reason": None})
        verified = self.machine("verify", OLD)
        executable = self.prefix / "versions" / OLD / "teerex"
        self.assertEqual(verified, {"schema_version": 1, "operation": "verify", "ok": True,
                                  "root": str(self.prefix), "platform": ASSET_PLATFORM,
                                  "active_version": NEW, "selected_version": OLD,
                                  "executable": str(executable),
                                  "sha256": hashlib.sha256(self.binaries["old"]).hexdigest()})
        self.assertFalse(probe.exists())
        (self.prefix / "current").unlink()  # A deliberately deactivated root is valid.
        self.assertIsNone(self.machine("inspect")["active_version"])
        self.assertIsNone(self.machine("verify", OLD)["active_version"])
        self.assertFalse(probe.exists())
        # Positive control: this native fixture records execution when actually launched.
        subprocess.run([str(executable), "--help"], env=self.env, capture_output=True, check=True)
        self.assertEqual(probe.read_text(), "executed\n")

    def test_machine_busy_including_stale_lock_is_not_inventory(self):
        self.call("install", OLD, self.old_source)
        lock = self.prefix / ".installer-lock"
        current = self.prefix / "current"
        current.unlink()
        current.symlink_to("versions/mid-mutation")
        for kind in ("directory", "file", "dangling-symlink"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    lock.mkdir()
                elif kind == "file":
                    lock.write_text("stale")
                else:
                    lock.symlink_to(self.home / "absent-lock-target")
                try:
                    data = self.machine("inspect")
                    self.assertEqual(data["state"], "managed")
                    self.assertTrue(data["busy"])
                    self.assertIsNone(data["active_version"])
                    self.assertEqual(data["installed_versions"], [])
                    self.machine("verify", OLD, error="busy")
                finally:
                    lock.rmdir() if kind == "directory" else lock.unlink()

    def test_machine_refuses_unsafe_paths_current_and_inventory(self):
        for prefix in (self.home, str(self.home) + "/../outside", str(self.home) + "/x//y",
                       str(self.home) + "/x/./y", str(self.home) + "/line\nbreak"):
            self.machine("inspect", prefix=prefix, error="unsafe_path")
            self.machine("verify", OLD, prefix=prefix, error="unsafe_path")
        link = self.home / "linked"
        link.symlink_to(self.home)
        self.machine("inspect", prefix=link / "install", error="unsafe_path")
        self.machine("verify", OLD, prefix=link / "install", error="unsafe_path")
        self.call("install", OLD, self.old_source)
        marker = self.prefix / ".teerex-install-root"
        marker.chmod(0)
        try:
            self.machine("inspect", error="invalid_root")
            self.machine("verify", OLD, error="invalid_root")
        finally:
            marker.chmod(0o600)
        versions = self.prefix / "versions"
        versions.chmod(0o300)
        try:
            self.machine("inspect", error="invalid_root")
            self.machine("verify", OLD, error="invalid_root")
        finally:
            versions.chmod(0o700)
        current = self.prefix / "current"
        for target in (str(self.home), "versions/" + NEW, "versions/../elsewhere"):
            current.unlink()
            current.symlink_to(target)
            self.machine("inspect", error="invalid_current")
            self.machine("verify", OLD, error="invalid_current")
        current.unlink()
        current.write_text("manual executable")
        self.machine("inspect", error="invalid_current")
        self.machine("verify", OLD, error="invalid_current")
        current.unlink()
        current.symlink_to("versions/" + OLD)
        entry = self.prefix / "versions" / NEW
        entry.symlink_to(self.prefix / "versions" / OLD)
        self.machine("inspect", error="invalid_release")
        self.machine("verify", OLD, error="invalid_release")
        entry.unlink()
        entry = self.prefix / "versions" / ".unexpected"
        entry.mkdir()
        self.machine("inspect", error="invalid_release")
        entry.rmdir()
        versions = self.prefix / "versions"
        versions.rename(self.prefix / "saved-versions")
        versions.symlink_to(self.prefix / "saved-versions")
        self.machine("inspect", error="invalid_root")
        self.machine("verify", OLD, error="invalid_root")
        marker = self.prefix / ".teerex-install-root"
        marker.unlink()
        marker.symlink_to(self.home / "missing-marker")
        self.machine("inspect", error="invalid_root")
        self.machine("verify", OLD, error="invalid_root")

    def test_machine_verify_integrity_structure_and_host_without_execution(self):
        self.call("install", OLD, self.old_source)
        release = self.prefix / "versions" / OLD
        readme = release / "README.md"
        original = readme.read_bytes()
        probe = self.home / "must-not-execute"
        self.env["TEEREX_INSTALL_EXEC_PROBE"] = str(probe)
        readme.write_text("modified")
        self.machine("verify", OLD, error="integrity_mismatch")
        self.assertEqual(self.machine("inspect")["installed_versions"], [OLD])  # Inventory is not integrity.
        readme.unlink()
        self.machine("verify", OLD, error="invalid_release")
        readme.symlink_to(release / "RIGHTS.md")
        self.machine("verify", OLD, error="invalid_release")
        readme.unlink()
        readme.write_bytes(original)
        extra = release / ".user-notes"
        extra.write_text("keep")
        self.machine("verify", OLD, error="invalid_release")
        extra.unlink()
        binary = release / "teerex"
        binary.chmod(0o600)
        self.machine("verify", OLD, error="invalid_release")
        binary.chmod(0o700)
        foreign = bytearray(self.binaries["old"])
        struct.pack_into("<I" if MAC else "<H", foreign, 4 if MAC else 18, 0x01000007 if MAC else 183)
        binary.write_bytes(foreign)
        # A fresh, internally consistent record must still fail host architecture.
        record = "".join(hashlib.sha256((release / name).read_bytes()).hexdigest() + "  " + name + "\n"
                         for name in ("teerex", "README.md", "RIGHTS.md"))
        (release / ".files.sha256").write_text(record)
        self.machine("verify", OLD, error="architecture_mismatch")
        self.machine("verify", NEW, error="invalid_release")
        self.assertFalse(probe.exists())

    def test_machine_argument_errors_are_json(self):
        self.machine("verify", error="invalid_arguments")
        self.machine("verify", "latest", error="invalid_arguments")
        self.machine("inspect", OLD, error="invalid_arguments")
        self.machine("inspect", extra=("--from", str(self.old_source)), error="invalid_arguments")
        self.machine("verify", OLD, extra=("--deactivate",), error="invalid_arguments")
        self.machine("inspect", extra=("--unknown",), error="invalid_arguments")

    def test_default_prefix(self):
        subprocess.run(["/bin/bash", str(INSTALLER), "install", "--version", OLD, "--from", str(self.old_source)], env=self.env, capture_output=True, check=True)
        self.assertEqual(os.readlink(self.home / ".local/opt/teerex/current"), "versions/" + OLD)

    @unittest.skipUnless(PUBLIC, "pass --public for real GitHub download and installation")
    def test_public_alpha_release(self):
        if LINUX:
            # There is no published Linux alpha.1 asset. Do not substitute a
            # Mac download or a local fixture and describe it as public Linux.
            self.call("install", OLD, self.old_source)
            result = self.call("upgrade", "v0.1.0-alpha.1", ok=False)
            self.assertIn("teerex-v0.1.0-alpha.1-x86_64-linux.tar.gz", result.stdout)
            self.assertIn("alpha.1 is Mac-only", result.stderr)
            self.active(OLD, "old")
            return
        result = self.call("install", "v0.1.0-alpha.1")
        self.assertIn("require Rex API 13", result.stderr)
        binary = self.prefix / "current" / "teerex"
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), "c39108dc3bfedf240c62c4f7b0c683f6f06b5ef59fa78cd377aa8b38b007abe9")
        self.assertEqual(binary.stat().st_size, 300712)
        receipt = self.machine("verify", "v0.1.0-alpha.1")
        self.assertEqual(receipt["sha256"], "c39108dc3bfedf240c62c4f7b0c683f6f06b5ef59fa78cd377aa8b38b007abe9")
        self.assertEqual(receipt["selected_version"], "v0.1.0-alpha.1")
        output = subprocess.check_output([str(binary), "--help"], text=True, stderr=subprocess.STDOUT)
        for command in ("observe", "compare", "watch", "run"):
            self.assertIn(command, output)
        # Real HTTPS failure leaves the public installation active.
        self.call("upgrade", "v0.0.0-installer-missing-test", ok=False)
        self.assertEqual(os.readlink(self.prefix / "current"), "versions/v0.1.0-alpha.1")
        # No newer public release is invented: upgrade to the local stub only,
        # then roll back to and execute the exact retained public binary.
        self.call("upgrade", NEW, self.new_source)
        self.active(NEW, "new")
        self.call("rollback", "v0.1.0-alpha.1")
        self.assertEqual(subprocess.check_output([str(binary), "--help"], text=True, stderr=subprocess.STDOUT), output)
        self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(), "c39108dc3bfedf240c62c4f7b0c683f6f06b5ef59fa78cd377aa8b38b007abe9")
        self.call("remove", NEW)
        self.call("remove", "v0.1.0-alpha.1", extra=("--deactivate",))
        self.assertIn("Active: none", self.call("list").stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
