"""Public lifecycle tests in disposable HOME; never invoke Rex or personal state."""
import signal
import selectors
import fcntl
import time
import hashlib
import importlib.util
import io
from contextlib import redirect_stderr
from unittest.mock import patch
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).with_name("cartridges.py").resolve()
PREFIX = [str(Path(os.environ["TEEREX_BIN"]).resolve()), "cartridges"] if os.environ.get("TEEREX_BIN") else [sys.executable, str(CLI)]
PLATFORM = "aarch64-macos" if platform.system() == "Darwin" else "x86_64-linux"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Lifecycle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="teerex-cartridges-test-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.root = self.home / "space in path" / "cartridges"
        self.catalog = self.home / "catalog"
        self.catalog.mkdir()
        self.entries = []
        self.env = dict(os.environ, HOME=str(self.home))
        self.sentinels = []
        for name in (".zshrc", ".config/rex/init.lua", ".local/opt/teerex/current"):
            p = self.home / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("user owned, do not touch")
            self.sentinels.append(p)
        self.addCleanup(self.check_sentinels)

    def check_sentinels(self):
        for p in self.sentinels:
            self.assertEqual(p.read_text(), "user owned, do not touch")

    def package(self, key, v="1.0.0", deps=None, status="ready", kind="script", code=None):
        path = self.catalog / key / v
        path.mkdir(parents=True)
        payload = path / "launch"
        payload.write_text(code or '#!/bin/sh\nprintf "%s\\n" "fixture:' + key + ':' + v + '" "$@"\n')
        payload.chmod(0o700)
        m = dict(schema_version=1, id=key, version=v, status=status, kind=kind, platform=PLATFORM,
                 entrypoint=["launch"], dependencies=deps or {}, data_policy="retain",
                 files=[dict(path="launch", sha256=sha(payload), executable=True)],
                 provenance={"kind": "synthetic-test-only"}, compatibility={"runtime": "/bin/sh"}, permissions=["user-process"])
        (path / "manifest.json").write_text(json.dumps(m))
        self.entries = [e for e in self.entries if not e["path"].startswith(key + "/")]
        self.entries.append(dict(path=key + "/" + v, manifest_sha256=sha(path / "manifest.json")))
        self.write_catalog()
        return path

    def write_catalog(self):
        (self.catalog / "catalog.json").write_text(json.dumps(dict(schema_version=1, packages=self.entries)))

    def update_manifest(self, path, modify):
        m = json.loads((path / "manifest.json").read_text())
        modify(m)
        (path / "manifest.json").write_text(json.dumps(m))
        for e in self.entries:
            if e["path"] == str(path.relative_to(self.catalog)):
                e["manifest_sha256"] = sha(path / "manifest.json")
        self.write_catalog()

    def invoke(self, *args, ok=True):
        p = subprocess.run(PREFIX + ["--root", str(self.root), *map(str, args)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        result = json.loads(p.stdout if ok else p.stderr)
        if not ok:
            self.assertEqual(p.returncode, 1)
            self.assertEqual(result["schema_version"], 1)
            for message in ("experimental cartridge requires", "choose explicit IDs", "cartridge root does not exist",
                            "active removal requires", "active dependent blocks", "in use or concurrent"):
                if message in result["error"]:
                    self.assertTrue(result["next_step"])
        return result

    def install(self, *ids, apply=True, extra=(), ok=True):
        return self.invoke("install", *ids, "--catalog", self.catalog, *( ["--apply"] if apply else []), *extra, ok=ok)

    def state(self):
        return self.invoke("list")

    def test_plan_is_read_only_and_all_excludes_experiments(self):
        self.package("alpha")
        self.package("beta", status="experimental")
        result = self.install(apply=False, extra=["--all"])
        self.assertEqual(result["selected"], ["alpha"])
        self.assertEqual(result["excluded_experimental"], ["beta"])
        self.assertFalse(self.root.exists())
        self.install("beta", apply=False, ok=False)
        self.assertFalse(self.root.exists())
        result = self.install(extra=["--all"])
        self.assertEqual(self.state()["active"], {"alpha": "1.0.0"})
        before = (self.root / "state.json").read_bytes()
        self.install("beta", apply=False, extra=["--allow-experimental"])
        self.assertEqual((self.root / "state.json").read_bytes(), before)
        self.assertFalse((self.root / "data").exists())
        self.assertFalse(result["hooks_executed"])

    def test_individual_all_repeat_and_independent_removal(self):
        for key, kind in (("alpha", "script"), ("beta", "agent"), ("gamma", "extension")):
            self.package(key, kind=kind)
        self.install("beta")
        self.install(extra=["--all"])
        self.install(extra=["--all"])
        self.assertEqual(self.state()["active"], {k: "1.0.0" for k in ("alpha", "beta", "gamma")})
        self.invoke("remove", "beta", "--version", "1.0.0", "--apply", ok=False)
        self.invoke("remove", "beta", "--version", "1.0.0", "--deactivate", "--apply")
        self.assertEqual(self.state()["active"], {"alpha": "1.0.0", "gamma": "1.0.0"})
        self.assertFalse((self.root / "packages/beta/1.0.0").exists())
        self.assertTrue((self.root / "retired/beta/1.0.0/launch").is_file())

    def test_upgrade_rollback_remove_restore_and_retained_data(self):
        self.package("alpha")
        self.install("alpha")
        run = subprocess.run(PREFIX + ["--root", str(self.root), "run", "alpha", "--", "space ; in arg"], env=self.env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout, "fixture:alpha:1.0.0\nspace ; in arg\n")
        data = self.root / "data/alpha/private-notes"
        data.write_bytes(b"keep user data\x00")
        self.package("alpha", "1.2.0")
        self.install("alpha")
        self.assertEqual(self.state()["active"]["alpha"], "1.2.0")
        self.invoke("activate", "alpha", "--version", "1.0.0", "--apply")
        self.invoke("remove", "alpha", "--version", "1.2.0", "--apply")
        self.invoke("restore", "alpha", "--version", "1.2.0", "--apply")
        self.assertEqual(self.state()["active"]["alpha"], "1.0.0")
        self.assertEqual(data.read_bytes(), b"keep user data\x00")
        self.invoke("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply")
        self.assertEqual(self.state()["active"], {})
        self.assertEqual(data.read_bytes(), b"keep user data\x00")

    def test_exact_dependencies_no_gc_conflicts_and_activation_recheck(self):
        self.package("lib")
        self.package("agent", deps={"lib": "1.0.0"})
        result = self.install("agent")
        self.assertEqual([p["id"] for p in result["packages"]], ["lib", "agent"])
        self.invoke("remove", "lib", "--version", "1.0.0", "--deactivate", "--apply", ok=False)
        self.package("lib", "2.0.0")
        self.install("lib", ok=False)
        self.assertEqual(self.state()["active"]["lib"], "1.0.0")
        self.invoke("remove", "agent", "--version", "1.0.0", "--deactivate", "--apply")
        self.assertEqual(self.state()["active"], {"lib": "1.0.0"})
        self.install("lib")
        self.invoke("restore", "agent", "--version", "1.0.0", "--apply")
        self.invoke("activate", "agent", "--version", "1.0.0", "--apply", ok=False)
        self.invoke("activate", "lib", "--version", "1.0.0", "--apply")
        self.invoke("activate", "agent", "--version", "1.0.0", "--apply")

    def test_cycle_missing_dependency_and_experimental_dependency_fail_before_activation(self):
        self.package("alpha", deps={"beta": "1.0.0"})
        self.install("alpha", ok=False)
        self.assertEqual(self.state()["active"], {})
        self.package("beta", deps={"alpha": "1.0.0"})
        self.install("alpha", ok=False)
        self.assertEqual(self.state()["installed"], {})
        self.update_manifest(self.catalog / "beta/1.0.0", lambda m: m.update(dependencies={}, status="experimental"))
        self.install("alpha", ok=False)
        self.install("alpha", extra=["--allow-experimental"])
        self.assertEqual(self.state()["active"], {"alpha": "1.0.0", "beta": "1.0.0"})

    def test_invalid_bulk_member_never_partially_activates(self):
        self.package("alpha")
        path = self.package("beta")
        (path / "launch").write_text("corrupt")
        self.install(extra=["--all"], ok=False)
        self.assertEqual(self.state()["installed"], {})
        self.assertFalse((self.root / "packages").exists())

    def test_modified_missing_added_or_linked_installed_payload_is_not_removed(self):
        self.package("alpha")
        self.install("alpha")
        path = self.root / "packages/alpha/1.0.0/launch"
        original = path.read_bytes()
        path.write_bytes(original + b"# user edits\n")
        self.invoke("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply", ok=False)
        path.write_bytes(original)
        extra = path.parent / "notes"
        extra.write_text("user owned")
        self.invoke("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply", ok=False)
        extra.unlink()
        path.unlink()
        path.symlink_to(self.catalog / "alpha/1.0.0/launch")
        self.invoke("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply", ok=False)
        self.assertTrue(path.is_symlink())
        self.assertEqual(self.state()["active"], {"alpha": "1.0.0"})

    def test_retired_manifest_identity_is_pinned(self):
        self.package("alpha")
        self.install("alpha")
        self.invoke("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply")
        m = self.root / "retired/alpha/1.0.0/manifest.json"
        value = json.loads(m.read_text())
        value["permissions"] = ["modified"]
        m.write_text(json.dumps(value))
        self.invoke("restore", "alpha", "--version", "1.0.0", "--apply", ok=False)
        self.assertEqual(self.state()["active"], {})

    def test_traversal_and_links_are_rejected_without_external_writes(self):
        path = self.package("alpha")
        original = (path / "manifest.json").read_bytes()
        for bad in ("../escape", "/absolute", "a/../escape", "a//escape", "./launch", "manifest.json"):
            with self.subTest(path=bad):
                (path / "manifest.json").write_bytes(original)
                self.update_manifest(path, lambda m: m["files"][0].update(path=bad))
                self.install("alpha", ok=False)
        (path / "manifest.json").write_bytes(original)
        self.entries[0]["manifest_sha256"] = sha(path / "manifest.json")
        self.write_catalog()
        (path / "launch").unlink()
        (path / "launch").symlink_to(self.sentinels[0])
        self.install("alpha", ok=False)
        self.assertFalse((self.home / "escape").exists())

    def test_root_refuses_unmarked_shared_symlink_and_outside_home(self):
        self.package("alpha")
        self.root.mkdir(parents=True)
        (self.root / "notes").write_text("keep me")
        self.install("alpha", ok=False)
        self.assertEqual((self.root / "notes").read_text(), "keep me")
        self.root = self.home / "alias"
        self.root.symlink_to(self.home / "catalog", target_is_directory=True)
        self.install("alpha", ok=False)
        self.root = self.home
        self.install("alpha", ok=False)
        self.root = self.home.parent / "not-this-home"
        self.install("alpha", ok=False)

    def test_unknown_fields_duplicate_json_platform_and_identity_overwrite_refused(self):
        path = self.package("alpha")
        self.install("alpha")
        self.update_manifest(path, lambda m: m.update(install_hook="touch something"))
        self.install("alpha", ok=False)
        self.update_manifest(path, lambda m: m.pop("install_hook"))
        self.update_manifest(path, lambda m: m.update(platform="x86_64-linux" if PLATFORM == "aarch64-macos" else "aarch64-macos"))
        self.install("alpha", ok=False)
        self.update_manifest(path, lambda m: m.update(platform=PLATFORM, permissions=["changed version identity"]))
        self.install("alpha", ok=False)
        index = self.catalog / "catalog.json"
        index.write_text('{"schema_version":1,"schema_version":1,"packages":[]}')
        self.install("alpha", ok=False)

    def test_in_use_blocks_own_removal_upgrade_and_dependencies_not_unrelated_items(self):
        self.package("lib")
        self.package("agent", deps={"lib": "1.0.0"}, kind="agent", code='#!/bin/sh\nprintf "ready\\n%s\\n%s\\n" "$TEEREX_CARTRIDGE_DATA" "$TEEREX_CARTRIDGE_DEPENDENCIES"\nread answer\nprintf "%s\\n" "$answer"\n')
        self.package("other")
        self.install("agent", "other")
        command = PREFIX + ["--root", str(self.root), "run", "agent"]
        process = subprocess.Popen(command, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline(), "ready\n")
            self.assertEqual(process.stdout.readline().strip(), str(self.root / "data/agent"))
            self.assertEqual(json.loads(process.stdout.readline()), {"lib": str(self.root / "packages/lib/1.0.0")})
            self.invoke("remove", "agent", "--version", "1.0.0", "--deactivate", "--apply", ok=False)
            self.package("agent", "2.0.0", deps={"lib": "1.0.0"})
            self.install("agent", ok=False)
            self.invoke("remove", "other", "--version", "1.0.0", "--deactivate", "--apply")
            self.assertEqual(self.state()["active"], {"agent": "1.0.0", "lib": "1.0.0"})
            out, error = process.communicate("released\n", timeout=5)
            self.assertEqual(process.returncode, 0, error)
            self.assertEqual(out, "released\n")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.invoke("remove", "agent", "--version", "1.0.0", "--deactivate", "--apply")
        self.assertIsNotNone(process.poll())
        self.assertTrue((self.root / "leases/agent/1.0.0").exists())
        self.assertTrue((self.root / "data/agent").exists())
        self.install("agent")
        self.assertEqual(self.state()["active"]["agent"], "2.0.0")

    def test_bulk_registry_write_failure_rolls_back_staged_payloads(self):
        self.package("alpha")
        self.package("beta")
        self.install(extra=["--all"])
        before = (self.root / "state.json").read_bytes()
        self.package("alpha", "2.0.0")
        self.package("beta", "2.0.0")
        # Existing per-ID directories remain writable, so both copies can be
        # staged, but creation of the final root registry temp file must fail.
        self.root.chmod(0o500)
        try:
            result = self.install(extra=["--all"], ok=False)
            self.assertIn("Permission denied", result["error"])
        finally:
            self.root.chmod(0o700)
        self.assertEqual((self.root / "state.json").read_bytes(), before)
        self.assertFalse((self.root / "packages/alpha/2.0.0").exists())
        self.assertFalse((self.root / "packages/beta/2.0.0").exists())
        self.assertEqual(self.state()["active"], {"alpha": "1.0.0", "beta": "1.0.0"})

    def snapshot(self):
        return {str(p.relative_to(self.home)): sha(p) if p.is_file() else None
                for p in self.home.rglob("*")}

    def test_preview_experimental_empty_and_refusal_guidance(self):
        self.package("alpha", status="experimental", code='#!/bin/sh\ntouch "$HOME/EXECUTED"\n')
        before = self.snapshot()
        for ids, extra in (((), ["--all"]), (("alpha",), ["--allow-experimental"]),
                           ((), ["--all", "--allow-experimental"])):
            result = self.install(*ids, apply=False, extra=extra)
            self.assertFalse(result["applied"])
            self.assertEqual(self.snapshot(), before)
            if not ids and "--allow-experimental" not in extra:
                self.assertEqual(result["selected"], [])
                self.assertEqual(result["packages"], [])
                self.assertEqual(result["excluded_experimental"], ["alpha"])
        for argv in (("install", "alpha", "--catalog", self.catalog),
                     ("install", "alpha", "--all", "--catalog", self.catalog),
                     ("run", "alpha")):
            result = self.invoke(*argv, ok=False)
            self.assertEqual(result["schema_version"], 1)
            self.assertTrue(result["next_step"])
            self.assertEqual(self.snapshot(), before)
        result = self.install(extra=["--all"])
        self.assertEqual(result["excluded_experimental"], ["alpha"])
        self.assertEqual(self.state()["active"], {})
        self.assertFalse((self.root / "packages").exists())

    def test_registry_contention_is_immediate_and_read_only(self):
        self.package("alpha")
        self.install("alpha")
        before = self.snapshot()
        with (self.root / ".lock").open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for argv in (("run", "alpha"), ("install", "alpha", "--catalog", self.catalog, "--apply"),
                         ("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply")):
                start = time.monotonic()
                result = self.invoke(*argv, ok=False)
                self.assertLess(time.monotonic() - start, 1)
                self.assertIn("in use or concurrent lifecycle operation: .lock", result["error"])
                self.assertTrue(result["next_step"])
                self.assertEqual(self.snapshot(), before)

    def test_common_refusals_preserve_existing_home(self):
        self.package("alpha")
        self.package("beta", deps={"alpha": "1.0.0"})
        self.package("experiment", status="experimental")
        self.install("beta")
        before = self.snapshot()
        for argv in (("install", "experiment", "--catalog", self.catalog),
                     ("install", "alpha", "--all", "--catalog", self.catalog),
                     ("remove", "beta", "--version", "1.0.0", "--apply"),
                     ("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply")):
            result = self.invoke(*argv, ok=False)
            self.assertTrue(result["next_step"])
            self.assertEqual(self.snapshot(), before)

    def test_old_python_version_refuses_before_main(self):
        spec = importlib.util.spec_from_file_location("manager", CLI)
        manager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manager)
        error = io.StringIO()
        with patch.object(sys, "version_info", (3, 8)), patch.object(manager, "main") as main, redirect_stderr(error):
            with self.assertRaises(SystemExit) as stopped:
                manager.entry()
        self.assertEqual(stopped.exception.code, 1)
        main.assert_not_called()
        refusal = json.loads(error.getvalue())
        self.assertIn("Python 3.9+ required, found 3.8", refusal["error"])
        self.assertEqual(refusal["schema_version"], 1)

    def test_sigint_during_apply_returns_json_and_previous_selection(self):
        self.package("alpha")
        self.install("alpha")
        self.package("alpha", "2.0.0")
        # A disposable interpreter fixture pauses after the real stage copy.
        # The core still execs its actual embedded source; the direct path uses
        # the same fixture. No product hook or copy-speed assumption is needed.
        interpreter = self.home / "python3"
        interpreter.write_text("#!" + sys.executable + " -I\n" + r'''import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
if args[:1] == ["-I"]:
    args = args[1:]
if args[0] == "-c":
    source = args[1]
    sys.argv = ["-c"] + args[2:]
else:
    source = Path(args[0]).read_text()
    sys.argv = args
copytree = shutil.copytree

def pause_after_copy(*args, **kwargs):
    copytree(*args, **kwargs)
    print("stage copied; waiting for SIGINT", flush=True)
    os.read(0, 1)  # Parent keeps stdin open until it sends SIGINT.
    raise AssertionError("test pause unexpectedly released")

shutil.copytree = pause_after_copy
exec(compile(source, sys.argv[0], "exec"), {"__name__": "__main__"})
''')
        interpreter.chmod(0o700)
        prefix = [sys.executable, "-I", str(interpreter), str(CLI)] if PREFIX == [sys.executable, str(CLI)] else PREFIX
        command = prefix + ["--root", str(self.root), "install", "alpha", "--catalog", str(self.catalog), "--apply"]
        env = dict(self.env, PATH=str(self.home) + os.pathsep + self.env.get("PATH", ""))
        process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with selectors.DefaultSelector() as ready:
                ready.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(ready.select(timeout=10), "manager did not reach the staged-copy pause")
            self.assertEqual(process.stdout.readline(), "stage copied; waiting for SIGINT\n")
            self.assertTrue(list((self.root / "packages/alpha").glob(".stage-*")))
            process.send_signal(signal.SIGINT)
            out, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 130, out + error)
            self.assertTrue(json.loads(error)["error"].startswith("interrupted"))
            self.assertEqual(self.state()["active"], {"alpha": "1.0.0"})
            self.assertNotIn("2.0.0", self.state()["installed"]["alpha"])
            self.assertFalse(list(self.root.rglob(".stage-*")))
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_entry_interrupt_rolls_back_and_emits_json(self):
        spec = importlib.util.spec_from_file_location("manager", CLI)
        manager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(manager)
        self.package("alpha")
        self.install("alpha")
        before = (self.root / "state.json").read_bytes()
        self.package("alpha", "2.0.0")
        argv = ["-c", "--root", str(self.root), "install", "alpha", "--catalog", str(self.catalog), "--apply"]
        error = io.StringIO()
        with patch.dict(os.environ, self.env), patch.object(sys, "argv", argv), \
                patch.object(manager.Store, "save", side_effect=KeyboardInterrupt), redirect_stderr(error):
            with self.assertRaises(SystemExit) as stopped:
                manager.entry()
        self.assertEqual(stopped.exception.code, 130)
        self.assertTrue(json.loads(error.getvalue())["error"].startswith("interrupted"))
        self.assertEqual((self.root / "state.json").read_bytes(), before)
        self.assertFalse((self.root / "packages/alpha/2.0.0").exists())

    def test_home_change_and_direct_invocation_has_no_lease(self):
        self.package("alpha", code='#!/bin/sh\nprintf "ready\\n"\nread answer\n')
        self.install("alpha")
        other = self.home / "other-home"
        other.mkdir(mode=0o700)
        env = dict(self.env, HOME=str(other))
        listed = subprocess.run(PREFIX + ["list"], env=env, capture_output=True, text=True)
        self.assertEqual(json.loads(listed.stdout)["active"], {})
        run = subprocess.run(PREFIX + ["run", "alpha"], env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn("cartridge root does not exist", run.stderr)
        process = subprocess.Popen([str(self.root / "packages/alpha/1.0.0/launch")], env=self.env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline(), "ready\n")
            self.invoke("remove", "alpha", "--version", "1.0.0", "--deactivate", "--apply")
            process.communicate("done\n", timeout=5)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_no_automatic_code_execution_on_install(self):
        sentinel = self.home / "must-not-run"
        self.package("agent", kind="agent", code='#!/bin/sh\ntouch "' + str(sentinel) + '"\n')
        self.install("agent")
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.root / "data").exists())


if __name__ == "__main__":
    unittest.main()
