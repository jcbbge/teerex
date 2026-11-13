"""Public surface contract using only disposable Rex sockets, on Linux and macOS.

REX_BIN selects a real Rex; TEEREX_BIN selects the shared CLI or standalone test entry.
No personal/default server, config, pane or process is touched.
"""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex")).resolve())


class SurfacesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = str(Path(os.environ.get("REX_BIN") or shutil.which("rex") or "MISSING_REX").resolve())
        tmp = tempfile.TemporaryDirectory(prefix="tsurface-", dir="/tmp")
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.config = cls.root / "init.lua"
        cls.config.write_text("")
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                      "--restore=false", "--config", str(cls.config), "--state-dir", str(cls.root / "state")],
                                     stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Disposable Rex did not start")
        cls.source = cls.rpc("server.version", {})
        print("Real Rex:", json.dumps(cls.source), flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def rpc(cls, method, args):
        return json.loads(subprocess.check_output(cls.base + ["api", "call", method, json.dumps(args)], timeout=10))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.env = dict(os.environ, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""),
                        REX_SERVER="unix:///tmp/poison.sock", REX_SESSION="session:poison",
                        REX_BLOCK="block:poison", REX_CLIENT="client:poison", XDG_STATE_HOME=str(self.work / "state"))
        self.session = self.rpc("session.create", {"label": "surfaces disposable"})["session_id"]
        self.anchor = self.open("tab")["actual"]["block_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": self.session}))

    def view(self):
        return self.rpc("session.view", {"session_id": self.session})

    def command(self, layout, *argv, label="surface α", extra=()):
        command = [BIN, "surfaces", "open", "--socket", str(self.socket), "--session", self.session,
                   "--layout", layout, "--label", label]
        if layout != "tab":
            command += ["--anchor", self.anchor]
        return command + list(extra) + ["--", *(argv or ["/bin/sh", "-c", "printf 'visible surface\\n'; sleep 60"])]

    def run_json(self, command):
        r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertTrue(r.stdout, r.stderr)
        return r, json.loads(r.stdout)

    def open(self, layout, *argv, **kw):
        r, value = self.run_json(self.command(layout, *argv, **kw))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(value["outcome"], "created_and_verified")
        self.assertTrue(value["requested_geometry_verified"])
        self.assertFalse(value["retry_safe"])
        self.assertFalse(value["focus_requested"])
        self.assertEqual(value["painted_visibility"], "not_assessed")
        return value

    def inspect(self, bid):
        r, v = self.run_json([BIN, "surfaces", "inspect", "--socket", str(self.socket), "--session", self.session, "--pane", bid])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(v["outcome"], "inspected")
        return v["actual"]

    def rect(self, actual, expected):
        self.assertEqual(len(actual), 4)
        for n, e in zip(actual, expected):
            self.assertAlmostEqual(n, e, places=6)

    def rename_command(self, *target, label="renamed α ' $(literal)"):
        return [BIN, "surfaces", "rename", "--socket", str(self.socket), "--session", self.session,
                *target, "--label", label]

    def surface(self, operation, *args):
        return self.run_json([BIN, "surfaces", *operation.split(), "--socket", str(self.socket), *args])

    def another_session(self, label="another session α"):
        sid = self.rpc("session.create", {"label": label})["session_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": sid}))
        return sid

    def global_command(self, label, create_session=None, *options):
        return [BIN, "surfaces", "ensure", "--socket", str(self.socket), "--session", "any", "--label", label,
                "--create-session", create_session or self.session, *options, "--", "/bin/sh", "-c", "sleep 60"]

    def test_global_ensure_creates_in_selected_session_then_reuses_across_sessions(self):
        sid = self.another_session("destination " + self.work.name)
        r, made = self.run_json(self.global_command("global seat α", sid[-8:]))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(made["outcome"], "created")
        self.assertEqual(made["resolved"]["session_id"], sid)
        self.assertEqual(made["actual"]["session_id"], sid)
        self.assertEqual(self.view()["windows"][0]["focused_block_id"], self.anchor)
        before = self.view()
        other_before = self.rpc("session.view", {"session_id": sid})
        # The creation target and anchor are unused when reusing an existing pane on another session.
        r, reused = self.run_json(self.global_command("global seat α", "absent creation session", "--focus", "yes",
                                                     "--layout", "tiled", "--anchor", self.anchor))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(reused["outcome"], "existing")
        self.assertEqual(reused["resolved"], made["resolved"])
        self.assertFalse(reused["creation_attempted"])
        self.assertTrue(reused["actual"]["in_active_window"])
        self.assertEqual(reused["actual"]["focused_block_id"], made["actual"]["block_id"])
        self.assertEqual(before, self.view())
        self.assertEqual(len(other_before["windows"]), len(self.rpc("session.view", {"session_id": sid})["windows"]))
        for selector in ("global seat α", made["actual"]["block_id"], made["actual"]["block_id"][-8:]):
            r, resolved = self.surface("resolve", "--session", "any", "--pane", selector)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertEqual(resolved["resolved"], made["resolved"])
        r, absent = self.surface("resolve", "--session", "any", "--pane", "absent pane")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(absent["failure_reason"], "target_not_found")
        self.assertTrue(all("session_id" in row and "session_label" in row and "label" in row for row in absent["candidates"]))

    def test_global_ensure_refuses_missing_creation_target_and_incomplete_inventory(self):
        before = self.view()
        r, refused = self.run_json(self.global_command("uncreated seat", "absent destination"))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(refused["failure_reason"], "target_not_found")
        self.assertFalse(refused["creation_attempted"])
        for args in (("ensure", "--session", "any", "--label", "seat", "--", "/bin/sh"),
                     ("resolve", "--session", "any"),
                     ("resolve", "--session", "any", "--window", "seat"),
                     ("ensure", "--session", self.session, "--create-session", self.session, "--label", "seat", "--", "/bin/sh")):
            r = subprocess.run([BIN, "surfaces", args[0], "--socket", str(self.socket), *args[1:]],
                               capture_output=True, text=True, env=self.env, timeout=5)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        needle = 'local view=rex.call("session.view",{session_id=session.session_id})'
        self.shim("import subprocess,sys\nargs=sys.argv[1:]\ni=args.index('-e')+1\n"
                  + "args[i]=args[i].replace(" + repr(needle) + ",'local view=nil')\n"
                  + f"sys.exit(subprocess.run([{self.rex!r},*args]).returncode)\n")
        r, refused = self.run_json(self.global_command("uncreated seat"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(refused["failure_reason"], "global_session_view_unavailable")
        self.assertFalse(refused["creation_attempted"])
        self.assertEqual(before, self.view())

    def test_global_ambiguity_refuses_with_session_attributed_candidates(self):
        sid = self.another_session()
        r, one = self.run_json(self.global_command("ambiguous seat"))
        self.assertEqual(r.returncode, 0, r.stdout)
        cmd = self.command("tab", label="ambiguous seat")
        cmd[cmd.index("--session") + 1] = sid
        r, two = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout)
        before = self.view()
        for cmd in (self.global_command("ambiguous seat"),
                    [BIN, "surfaces", "resolve", "--socket", str(self.socket), "--session", "any", "--pane", "ambiguous seat"]):
            r, refused = self.run_json(cmd)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn(refused["failure_reason"], ("ambiguous_label", "ambiguous_target"))
            self.assertFalse(refused["creation_attempted"])
            self.assertEqual({c["session_id"] for c in refused["candidates"]}, {self.session, sid})
            self.assertEqual({c["block_id"] for c in refused["candidates"]}, {one["actual"]["block_id"], two["actual"]["block_id"]})
            self.assertTrue(all(c["session_label"] for c in refused["candidates"]))
        self.assertEqual(before, self.view())

    def test_global_concurrent_ensures_share_socket_alias_lock_and_create_one_pane(self):
        sid = self.another_session()
        alias = self.work / "socket-alias"
        alias.symlink_to(self.socket)
        first = self.global_command("concurrent seat", self.session)
        second = self.global_command("concurrent seat", sid)
        second[second.index("--socket") + 1] = str(alias)
        # Slow the child after it starts, so the second ensure overlaps the held lock.
        self.shim("import subprocess,sys,time\ntime.sleep(.2)\n"
                  + f"sys.exit(subprocess.run([{self.rex!r},*sys.argv[1:]]).returncode)\n")
        children = [subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for cmd in (first, second)]
        results = []
        for child in children:
            out, err = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, out + err)
            results.append(json.loads(out))
        self.assertEqual({v["outcome"] for v in results}, {"created", "existing"})
        self.assertEqual(results[0]["resolved"], results[1]["resolved"])
        self.assertEqual(results[0]["ensure_lock"], results[1]["ensure_lock"])
        lock = Path(results[0]["ensure_lock"])
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        self.assertEqual(lock.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(lock.name, "server-" + hashlib.sha256(str(self.socket.resolve()).encode()).hexdigest() + ".lock")
        count = sum(b.get("label") == "concurrent seat" for session in (self.session, sid)
                    for w in self.rpc("session.view", {"session_id": session}).get("windows", [])
                    for layer in w["layers"] for b in layer["blocks"])
        self.assertEqual(count, 1)

    def test_ensure_busy_is_retry_safe_and_cancelled_wait_does_not_mutate(self):
        root = Path(self.env["XDG_STATE_HOME"]) / "teerex-surfaces"
        root.mkdir(parents=True, mode=0o700)
        lock = root / ("server-" + hashlib.sha256(str(self.socket.resolve()).encode()).hexdigest() + ".lock")
        lock.touch(mode=0o600)
        before = self.view()
        with lock.open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            r, busy = self.run_json(self.global_command("busy seat", None, "--timeout-ms", "100"))
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertEqual(busy["failure_reason"], "ensure_busy")
            self.assertTrue(busy["retry_safe"])
            self.assertFalse(busy["creation_attempted"])
            child = subprocess.Popen(self.global_command("busy seat"), env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(.1)
            child.terminate()
            out, err = child.communicate(timeout=3)
            self.assertEqual(child.returncode, 143, out + err)
            self.assertFalse(json.loads(out)["creation_attempted"])
        self.assertEqual(before, self.view())
        r, made = self.run_json(self.global_command("busy seat"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(made["outcome"], "created")

    def test_global_ensure_state_fallback_and_private_path_refusals(self):
        self.env.pop("XDG_STATE_HOME")
        self.env["HOME"] = str(self.work / "home")
        r, made = self.run_json(self.global_command("fallback seat"))
        self.assertEqual(r.returncode, 0, r.stdout)
        expected = Path(self.env["HOME"]) / ".local/state/teerex-surfaces"
        self.assertEqual(Path(made["ensure_lock"]).parent, expected)
        before = self.view()
        lock = Path(made["ensure_lock"])
        lock.unlink()
        target = self.work / "unrelated"
        target.write_text("must remain")
        lock.symlink_to(target)
        r, refused = self.run_json(self.global_command("different seat"))
        self.assertEqual(r.returncode, 1)
        self.assertFalse(refused["creation_attempted"])
        self.assertEqual(target.read_text(), "must remain")
        self.assertEqual(before, self.view())
        lock.unlink()
        lock.touch(mode=0o644)
        lock.chmod(0o644)
        r, refused = self.run_json(self.global_command("different seat"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(refused["failure_reason"], "EnsureLockNotPrivateRegular")
        lock.unlink()
        expected.chmod(0o755)
        r, refused = self.run_json(self.global_command("different seat"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(refused["failure_reason"], "EnsureStateDirectoryNotPrivate")

    def test_resolve_labels_suffixes_and_mutation_targets(self):
        label = "unique session α " + self.work.name
        self.rpc("session.set_label", {"session_id": self.session, "label": label})
        pane = self.open("tab", label="unique pane α")["actual"]
        for session in (self.session, self.session[-8:], label):
            for target in (pane["block_id"], pane["block_id"][-8:], "unique pane α"):
                r, value = self.surface("resolve", "--session", session, "--pane", target)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(value["requested"]["session_id"], session)
                self.assertEqual(value["resolved"]["session_id"], self.session)
                self.assertEqual(value["resolved"]["block_id"], pane["block_id"])
        r, value = self.surface("inspect", "--session", label, "--pane", "unique pane α")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(value["actual"]["block_id"], pane["block_id"])
        r, value = self.surface("resolve", "--session", label, "--window", "unique pane α")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(value["resolved"]["window_id"], pane["window_id"])
        self.open("tab", label="unique pane α")
        before = self.view()
        r, value = self.surface("close", "--session", label, "--pane", "unique pane α")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(value["failure_reason"], "ambiguous_target")
        self.assertEqual(len(value["candidates"]), 2)
        self.assertEqual(before, self.view())
        r, value = self.surface("resolve", "--session", "absent session")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(value["failure_reason"], "target_not_found")
        self.assertTrue(value["candidates"])

    def test_session_ensure_empty_existing_and_ambiguous(self):
        label = "ensured α " + self.work.name
        before = self.view()
        r, made = self.surface("session ensure", "--label", label)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(made["outcome"], "created")
        sid = made["resolved"]["session_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": sid}))
        self.assertEqual(self.rpc("session.view", {"session_id": sid}).get("windows", []), [])
        r, existing = self.surface("session ensure", "--label", label)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(existing["outcome"], "existing")
        self.assertEqual(existing["resolved"], made["resolved"])
        self.assertFalse(existing["creation_attempted"])
        other = self.rpc("session.create", {"label": label})["session_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": other}))
        r, refused = self.surface("session ensure", "--label", label)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(refused["failure_reason"], "ambiguous_label")
        self.assertEqual(len(refused["candidates"]), 2)
        self.assertFalse(refused["creation_attempted"])
        self.assertEqual(before, self.view())

    def test_pane_ensure_reuses_tab_or_pane_and_focuses_only_when_requested(self):
        cmd = ["--session", self.session, "--label", "ensured pane", "--", "/bin/sh", "-c", "sleep 60"]
        r, made = self.surface("ensure", *cmd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(made["outcome"], "created")
        bid = made["actual"]["block_id"]
        before = self.view()
        r, existing = self.surface("ensure", *cmd)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(existing["outcome"], "existing")
        self.assertEqual(existing["actual"]["block_id"], bid)
        self.assertEqual(before, self.view())
        r, focused = self.surface("ensure", "--focus", "yes", *cmd)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(focused["actual"]["focused_block_id"], bid)
        self.assertTrue(focused["actual"]["in_active_window"])
        # Window label alone is enough, even if the terminal was relabelled.
        self.rpc("session.set_block_label", {"session_id": self.session, "block_id": bid, "label": "different"})
        r, existing = self.surface("ensure", *cmd)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(existing["actual"]["block_id"], bid)
        self.open("tab", label="ensured pane")
        before = self.view()
        r, refused = self.surface("ensure", *cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(refused["failure_reason"], "ambiguous_label")
        self.assertEqual(before, self.view())
        r, made_focused = self.surface("ensure", "--focus", "yes", "--session", self.session,
                                       "--label", "new focused ensure", "--", "/bin/sh", "-c", "sleep 60")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(made_focused["outcome"], "created")
        self.assertTrue(made_focused["actual"]["in_active_window"])
        self.assertEqual(made_focused["actual"]["block_id"], made_focused["actual"]["focused_block_id"])

    def test_ensure_concurrent_duplicate_readback_is_uncertain_without_retry(self):
        # Inject a second client-equivalent creation between receipt and fresh view.
        needle = 'local after=rex.call("session.view",{session_id=a.session_id})'
        injected = 'rex.call(method,params)\n' + needle
        self.shim("import subprocess,sys\nargs=sys.argv[1:]\ni=args.index('-e')+1\n"
                  + "args[i]=args[i].replace(" + repr(needle) + "," + repr(injected) + ")\n"
                  + f"sys.exit(subprocess.run([{self.rex!r},*args]).returncode)\n")
        r, value = self.surface("ensure", "--session", self.session, "--label", "racing label",
                                "--", "/bin/sh", "-c", "sleep 60")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(value["outcome"], "uncertain")
        self.assertEqual(value["failure_reason"], "ensure_label_readback_ambiguous")
        self.assertTrue(value["creation_attempted"])
        self.assertEqual(len(value["candidates"]), 2)
        self.assertEqual(len(self.view()["windows"]), 3)
        self.assertFalse(value["retry_safe"])

    def test_rename_window_and_pane_read_back_labels_without_changing_focus(self):
        pane = self.open("tab")["actual"]
        initial = self.view()
        focus = lambda view: (view["active_window_id"], {w["window_id"]: w.get("focused_block_id") for w in view["windows"]})
        for flag, identity, label in (("--window", pane["window_id"], "seat α ' $(literal)"),
                                      ("--pane", pane["block_id"], "pane α ' $(literal)")):
            r, renamed = self.run_json(self.rename_command(flag, identity, label=label))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(renamed["outcome"], "renamed_and_verified")
            self.assertEqual(renamed["requested"]["label"], label)
            self.assertEqual(renamed["actual"]["label"], label)
            self.assertTrue(renamed["requested_label_verified"])
            self.assertTrue(renamed["control_attempted"])
            self.assertTrue(renamed["control_acknowledged"])
            self.assertFalse(renamed["creation_attempted"])
            self.assertFalse(renamed["focus_requested"])
            self.assertFalse(renamed["retry_safe"])
            self.assertEqual(focus(self.view()), focus(initial))
        actual = self.inspect(pane["block_id"])
        self.assertEqual(actual["label"], "pane α ' $(literal)")
        self.assertEqual(actual["window_label"], "seat α ' $(literal)")
        self.assertEqual(actual["rect"], pane["rect"])
        self.assertEqual(len(self.view()["windows"]), len(initial["windows"]))

    def test_rename_usage_and_unknown_target_do_not_mutate(self):
        before = self.view()
        window = before["windows"][0]["window_id"]
        for target, label in (([], "valid"), (["--window", window, "--pane", self.anchor], "valid"),
                              (["--window", "window:bad"], "valid"), (["--pane", "block:bad"], "valid"),
                              (["--window", window], ""), (["--pane", self.anchor], "bad\nlabel"),
                              (["--pane", self.anchor], "α" * 65),
                              (["--window", window, "--layout", "tab"], "valid")):
            r = subprocess.run(self.rename_command(*target, label=label), env=dict(self.env, PATH="/missing"),
                               capture_output=True, text=True, timeout=5)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertEqual(r.stdout, "")
        r, refused = self.run_json(self.rename_command("--window", "window:00000000-0000-0000-0000-000000000000"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(refused["outcome"], "refused")
        self.assertEqual(refused["failure_reason"], "window_not_found")
        self.assertFalse(refused["control_attempted"])
        self.assertEqual(self.view(), before)

    def test_rename_refuses_missing_server_method_before_mutation(self):
        before = self.view()
        # Simulate an older server's advertised methods in the local Lua controller.
        self.shim("import subprocess,sys\n"
                  "args=sys.argv[1:]\n"
                  "i=args.index('-e')+1\n"
                  "args[i]=args[i].replace('local help=rex.call(\"help.all\")','local help={methods={}}')\n"
                  f"sys.exit(subprocess.run([{self.rex!r},*args]).returncode)\n")
        r, refused = self.run_json(self.rename_command("--pane", self.anchor))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(refused["outcome"], "refused")
        self.assertEqual(refused["failure_reason"], "rename_label_method_unavailable")
        self.assertFalse(refused["control_attempted"])
        self.assertEqual(self.view(), before)

    def test_rename_normalized_label_mismatch_and_lost_receipt_stay_non_success(self):
        r, mismatch = self.run_json(self.rename_command("--pane", self.anchor, label="  trimmed α  "))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(mismatch["outcome"], "label_mismatch")
        self.assertEqual(mismatch["requested"]["label"], "  trimmed α  ")
        self.assertEqual(mismatch["actual"]["label"], "trimmed α")
        self.assertFalse(mismatch["requested_label_verified"])
        self.assertEqual(mismatch["failure_reason"], "requested_label_not_verified")
        before = self.view()
        self.shim("import json,subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                  "for line in r.stdout.splitlines():\n"
                  " if json.loads(line)['event']=='attempt':sys.stdout.buffer.write(line+b'\\n')\n"
                  "sys.stdout.flush();sys.exit(77)\n")
        r, lost = self.run_json(self.rename_command("--pane", self.anchor, label="actual rename"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(lost["outcome"], "uncertain")
        self.assertTrue(lost["control_attempted"])
        self.assertFalse(lost["creation_attempted"])
        self.assertFalse(lost["retry_safe"])
        self.assertFalse(lost["requested_label_verified"])
        self.assertEqual(self.view()["windows"][0]["layers"][0]["blocks"][0]["label"], "actual rename")
        self.assertEqual(len(self.view()["windows"]), len(before["windows"]))

    def test_four_asymmetric_directions_and_nested_readback(self):
        # Explicit independent rectangles catch confusing NEW share with BEFORE share.
        expected = {"right": [.77, 0, .23, 1], "left": [0, 0, .23, 1],
                    "up": [0, 0, 1, .23], "down": [0, .77, 1, .23]}
        initial = self.anchor
        for direction, rect in expected.items():
            with self.subTest(direction=direction):
                if direction != "right":
                    self.anchor = self.open("tab")["actual"]["block_id"]
                before = self.view()
                v = self.open("tiled", extra=["--direction", direction, "--ratio", ".23"])
                a = v["actual"]
                self.rect(a["rect"], rect)
                self.assertAlmostEqual(a["pane_share"], .23)
                self.assertEqual(self.view()["active_window_id"], before["active_window_id"])
                self.assertEqual(a["window_id"], self.inspect(self.anchor)["window_id"])
                self.assertEqual(a["host_id"], self.inspect(self.anchor)["host_id"])
                stable = self.view()
                self.assertEqual(self.inspect(a["block_id"])["rect"], a["rect"])
                self.assertEqual(stable, self.view(), "inspect must not change layout/focus")
        self.anchor = initial
        nested = self.open("tiled", extra=["--direction", "down", "--ratio", ".4"])["actual"]
        self.rect(nested["rect"], [0, .6, .77, .4])
        self.assertEqual(len(nested["split_path"]), 2)

    def test_close_receipt_publisher_preflight_and_verified_atomic_update(self):
        directory = self.work / "completion"
        directory.mkdir(mode=0o700)
        file = directory / "receipt.json"
        packet = dict(schema_version=1, kind="run_visible_result", receipt_state="cleanup_pending_or_unknown",
                      cleanup_owner="visible_supervisor", receipt_path=str(file), server="unix://" + str(self.socket),
                      session_id=self.session, created=dict(block_id=self.anchor),
                      cleanup=dict(attempted=True, block_absence="unknown", block_absence_verified=False),
                      outcome="exit_reported", exit_report=dict(exit_code=0), success=False)
        file.write_text(json.dumps(packet)); file.chmod(0o600)
        other = self.open("tab")["created"]["block_id"]
        before = self.view()
        command = [BIN, "surfaces", "close", "--socket", str(self.socket), "--session", self.session,
                   "--pane", other, "--publish-receipt-file", str(file)]
        rejected = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertEqual(self.view(), before, "mismatched prepared target must refuse before any close")
        command[command.index("--pane") + 1] = self.anchor
        file.chmod(0o644)
        rejected = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(self.view(), before)
        file.chmod(0o600)
        result, close = self.run_json(command)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        final = json.loads(file.read_text())
        self.assertEqual(final["exit_report"], {"exit_code": 0})
        self.assertTrue(final["success"])
        self.assertTrue(final["cleanup"]["block_absence_verified"])
        self.assertEqual(final["cleanup"]["block_absence"], "verified_absent")
        self.assertEqual(final["cleanup"]["transport"]["receipt"], close)
        self.assertEqual(final["receipt_state"], "final")
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.inspect(other)["block_id"], other)

    def test_close_publisher_hard_deadline_covers_blocked_final_stdout(self):
        directory = self.work / "blocked-publisher"
        directory.mkdir(mode=0o700)
        file = directory / "receipt.json"
        file.write_text(json.dumps(dict(schema_version=1, kind="run_visible_result", receipt_state="cleanup_pending_or_unknown",
            cleanup_owner="visible_supervisor", receipt_path=str(file), server="unix://" + str(self.socket), session_id=self.session,
            created=dict(block_id=self.anchor), cleanup=dict(block_absence="unknown", block_absence_verified=False),
            outcome="exit_reported", exit_report=dict(exit_code=0), success=False)))
        file.chmod(0o600)
        reader, writer = os.pipe()
        process = None
        try:
            os.set_blocking(writer, False)
            while True:
                try:os.write(writer, b"x" * 4096)
                except BlockingIOError:break
            os.set_blocking(writer, True)
            started = time.monotonic()
            process = subprocess.Popen([BIN, "surfaces", "close", "--socket", str(self.socket), "--session", self.session,
                "--pane", self.anchor, "--timeout-ms", "1000", "--publish-receipt-file", str(file)],
                env=self.env, stdout=writer, stderr=subprocess.PIPE)
            process.wait(timeout=6)
            stderr = process.stderr.read().decode(errors="replace")
            process.stderr.close()
            self.assertEqual(process.returncode, 124, stderr)
            self.assertLess(time.monotonic() - started, 5)
            # Publication preceded stdout. A late watchdog exit cannot erase known evidence.
            self.assertTrue(json.loads(file.read_text())["cleanup"]["block_absence_verified"])
        finally:
            os.close(reader);os.close(writer)
            if process is not None and process.poll() is None:
                process.kill();process.communicate(timeout=5)

    def test_explicit_focus_and_close_verify_only_the_requested_pane(self):
        tab = self.open("tab")["actual"]
        self.assertNotEqual(self.view()["active_window_id"], tab["window_id"])
        base = [BIN, "surfaces", "focus", "--socket", str(self.socket), "--session", self.session, "--pane", tab["block_id"]]
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "focused_and_verified")
        self.assertTrue(v["focus_requested"])
        self.assertTrue(v["control_acknowledged"])
        self.assertFalse(v["creation_attempted"])
        self.assertEqual(self.view()["active_window_id"], tab["window_id"])
        self.assertEqual(self.inspect(tab["block_id"])["focused_block_id"], tab["block_id"])
        base[2] = "close"
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "closed_and_absent")
        self.assertTrue(v["block_absence_verified"])
        self.assertTrue(v["close_requested"])
        self.assertFalse(v["automatic_close"])
        self.assertEqual(self.inspect(self.anchor)["block_id"], self.anchor)
        stable = self.view()
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["outcome"], "refused")
        self.assertFalse(v["control_attempted"])
        self.assertEqual(self.view(), stable)
        base[base.index("--pane") + 1] = self.anchor
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "closed_and_absent")
        self.assertFalse(self.view().get("windows"))

    def move_command(self, pane, *, direction="right", ratio=".27", focus="no"):
        return [BIN, "surfaces", "move", "--socket", str(self.socket), "--session", self.session,
                "--pane", pane, "--anchor", self.anchor, "--direction", direction, "--ratio", ratio, "--focus", focus]

    def test_existing_tab_move_preserves_identity_process_and_asymmetric_geometry(self):
        expected = {"right": [.73, 0, .27, 1], "left": [0, 0, .27, 1],
                    "up": [0, 0, 1, .27], "down": [0, .73, 1, .27]}
        for direction, rect in expected.items():
            self.anchor = self.open("tab")["actual"]["block_id"]
            pane = self.open("tab", "/bin/sh", "-c", "printf 'same terminal process\\n'; exec sleep 60")["actual"]
            before = self.view()
            blocks_before = {b["block_id"] for b in self.rpc("session.list_blocks", {"session_id": self.session})["blocks"]}
            process = self.rpc("com.superlogical.terminal.process", {"session_id": self.session, "block_id": pane["block_id"], "args": {}})
            r, refused = self.run_json(self.move_command(pane["block_id"], direction=direction))
            self.assertEqual(r.returncode, 1)
            self.assertEqual(refused["failure_reason"], "focused_source_move_requires_focus_yes")
            self.assertFalse(refused["control_attempted"])
            self.assertEqual(self.view(), before)
            r, moved = self.run_json(self.move_command(pane["block_id"], direction=direction, focus="yes"))
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertEqual(moved["outcome"], "moved_and_verified")
            self.assertFalse(moved["creation_attempted"])
            self.assertTrue(moved["control_acknowledged"])
            self.assertTrue(moved["focus_acknowledged"])
            self.assertIsNone(moved["created"])
            self.assertEqual(moved["actual"]["block_id"], pane["block_id"])
            self.assertEqual(moved["previous"]["window_id"], pane["window_id"])
            self.rect(moved["actual"]["rect"], rect)
            self.assertEqual(moved["actual"]["window_id"], self.inspect(self.anchor)["window_id"])
            self.assertEqual(moved["actual"]["focused_block_id"], pane["block_id"])
            self.assertEqual(len(self.view()["windows"]), len(before["windows"]) - 1)
            self.assertEqual({b["block_id"] for b in self.rpc("session.list_blocks", {"session_id": self.session})["blocks"]}, blocks_before)
            after_process = self.rpc("com.superlogical.terminal.process", {"session_id": self.session, "block_id": pane["block_id"], "args": {}})
            self.assertEqual(after_process["child"]["pid"], process["child"]["pid"])
            capture = self.rpc("com.superlogical.terminal.format", {"session_id": self.session, "block_id": pane["block_id"], "args": {"format": "text", "max_bytes": 2048}})
            self.assertIn("same terminal process", capture["content"])

    def test_existing_unfocused_pane_moves_without_changing_focus(self):
        pane = self.open("tiled", extra=["--ratio", ".21"])["actual"]
        self.anchor = self.open("tab")["actual"]["block_id"]
        before = self.view()
        r, moved = self.run_json(self.move_command(pane["block_id"], ratio=".31"))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(moved["outcome"], "moved_and_verified")
        self.assertFalse(moved["focus_requested"])
        self.rect(moved["actual"]["rect"], [.69, 0, .31, 1])
        after = self.view()
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual({w["window_id"]: w.get("focused_block_id") for w in after["windows"]},
                         {w["window_id"]: w.get("focused_block_id") for w in before["windows"]})

    def test_lost_move_receipt_is_uncertain_without_recreate_or_retry(self):
        pane = self.open("tab")["actual"]
        before = self.view()
        self.shim("import json,subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                  "for line in r.stdout.splitlines():\n"
                  " if json.loads(line)['event']=='attempt':sys.stdout.buffer.write(line+b'\\n')\n"
                  "sys.stdout.flush();sys.exit(77)\n")
        r, result = self.run_json(self.move_command(pane["block_id"], focus="yes"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(result["outcome"], "uncertain")
        self.assertFalse(result["creation_attempted"])
        self.assertTrue(result["control_attempted"])
        self.assertFalse(result["retry_safe"])
        self.assertIsNone(result["actual"])
        self.env["PATH"] = str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"]
        actual = self.inspect(pane["block_id"])
        self.rect(actual["rect"], [.73, 0, .27, 1])
        self.assertEqual(len(self.view()["windows"]), len(before["windows"]) - 1)

    def test_floating_bounds_label_host_and_exact_argv_cwd(self):
        before = self.view()
        output = self.work / "args.json"
        cwd = self.work / "cwd ' α"
        cwd.mkdir()
        args = ["", "α\nnext", "'\"", "$(touch NEVER); >&2", "--"]
        code = f"import os,json,sys;from pathlib import Path;Path({str(output)!r}).write_text(json.dumps([os.getcwd(),sys.argv[1:]]));print('REAL TERMINAL CONTENT α',flush=True)"
        v = self.open("float", sys.executable, "-c", code, *args, label="inbox ' α",
                      extra=["--bounds", "[0.61,0.07,0.34,0.81]", "--cwd", str(cwd)])
        a = v["actual"]
        self.assertEqual(a["layer_kind"], "floating")
        self.assertEqual(a["label"], "inbox ' α")
        self.rect(a["layer_bounds"], [.61, .07, .34, .81])
        self.rect(a["rect"], [.61, .07, .34, .81])
        self.assertEqual(self.view()["active_window_id"], before["active_window_id"])
        for _ in range(100):
            if output.exists():
                break
            time.sleep(.02)
        self.assertEqual(json.loads(output.read_text()), [str(cwd.resolve()), args])
        capture = self.rpc("com.superlogical.terminal.format", {"session_id": self.session, "block_id": a["block_id"],
                           "args": {"format": "text", "max_bytes": 2048}})
        self.assertIn("REAL TERMINAL CONTENT α", capture["content"])
        self.assertEqual(self.inspect(a["block_id"])["rect"], a["rect"])

    def test_tab_empty_session_label_retention_and_no_focus_request(self):
        before = self.view()
        v = self.open("tab", "/bin/echo", "retained exit", label="new visible tab")
        a = v["actual"]
        self.rect(a["rect"], [0, 0, 1, 1])
        self.assertEqual(a["layer_kind"], "tiled")
        self.assertNotEqual(a["window_id"], before["windows"][0]["window_id"])
        after = self.view()
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual(next(w for w in after["windows"] if w["window_id"] == a["window_id"])["label"], "new visible tab")
        time.sleep(.1)
        self.assertEqual(self.inspect(a["block_id"])["block_id"], a["block_id"])

    def test_refusal_and_bad_geometry_do_not_create(self):
        before = self.view()
        unknown = "block:00000000-0000-0000-0000-000000000000"
        cmd = self.command("tiled")
        cmd[cmd.index("--anchor") + 1] = unknown
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["outcome"], "refused")
        self.assertFalse(v["creation_attempted"])
        for extra in [["--ratio", "nan"], ["--ratio", "0"], ["--ratio", "1"], ["--bounds", "[0,0,.3,1]"], ["--direction", "north"]]:
            r = subprocess.run(self.command("tiled", extra=extra), env=dict(self.env, PATH="/missing"), capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr + r.stdout)
        for bounds in ["[0,0,0,1]", "[0.8,0,0.3,1]", "[-0.1,0,0.3,1]", "[0,0,1]", "[0,0,1,1,1]"]:
            r = subprocess.run(self.command("float", extra=["--bounds", bounds]), capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.view(), before)
        floating = self.open("float", extra=["--bounds", "[0.67,0,0.33,1]"])["actual"]
        self.anchor = floating["block_id"]
        stable = self.view()
        r, v = self.run_json(self.command("tiled"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["failure_reason"], "anchor_not_tiled")
        self.assertEqual(self.view(), stable)
        self.rpc("session.set_layer_state", {"session_id": self.session, "layer_id": floating["layer_id"], "state": "minimized"})
        r, v = self.run_json(self.command("float", extra=["--bounds", "[0,0,0.2,1]"]))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["failure_reason"], "anchor_layer_not_normal")
        self.assertEqual(self.inspect(self.anchor)["layer_state"], "minimized")

    def test_focus_palette_resolves_server_wide_and_refuses_missing_or_ambiguous(self):
        fragment = self.work / "focus.lua"
        cmd = [BIN, "surfaces", "palette", "focus", "--file", str(fragment), "--name", "jump_existing",
               "--title", "Jump existing", "--label", "focus destination", "--teerex", BIN]
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.config.write_text("dofile(" + json.dumps(str(fragment)) + ")\n")
        self.rpc("server.config_reload", {})
        invoke = self.base + ["do", "--session", self.session, "--block", self.anchor, "jump_existing"]
        absent = subprocess.run(invoke, capture_output=True, text=True)
        self.assertNotEqual(absent.returncode, 0)
        block = {"block": {"flavor": "com.superlogical.terminal.shell", "label": "focus destination",
                           "options": {"command": ["/bin/sh", "-c", "sleep 60"]}}}
        made = self.rpc("session.create", {"label": "focus other", "initial_windows": [{"layout": block}]})
        result = subprocess.run(invoke, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "focused_and_verified")
        self.rpc("session.new_window", {"session_id": made["session_id"], "layout": block})
        ambiguous = subprocess.run(invoke, capture_output=True, text=True)
        self.assertNotEqual(ambiguous.returncode, 0)

    def test_named_host_focus_palette_targets_selected_server_without_creation(self):
        socket = self.work / "other.sock"
        log = (self.work / "other.log").open("w")
        other = subprocess.Popen([self.rex, "server", "run", "--listen", "unix://" + str(socket),
                                  "--restore=false", "--config", "/dev/null", "--state-dir", str(self.work / "other-state")],
                                 stdout=log, stderr=log)
        def stop():
            other.terminate()
            try:
                other.wait(timeout=5)
            except subprocess.TimeoutExpired:
                other.kill()
                other.wait(timeout=5)
            log.close()
        self.addCleanup(stop)
        base = [self.rex, "--autostart=false", "--server", "unix://" + str(socket)]
        def rpc(method, args=None):
            return json.loads(subprocess.check_output(base + ["api", "call", method, json.dumps(args or {})], timeout=10))
        for _ in range(100):
            if socket.exists():
                break
            self.assertIsNone(other.poll())
            time.sleep(.03)
        settings = self.work / "hosts.json"
        settings.write_text(json.dumps(dict(schema_version=1, hosts=dict(destination=dict(
            host_id="fixture", transport="local", home=str(self.work), socket=str(socket), rex=self.rex,
            teerex=BIN, store=str(self.work / "boards"), platform="macos-arm64" if sys.platform == "darwin" else "linux-x86_64")))))
        fragment = self.work / "named-focus.lua"
        r, _ = self.run_json([BIN, "surfaces", "palette", "focus", "--file", str(fragment), "--teerex", BIN,
                             "--name", "named_focus", "--title", "Focus named host", "--label", "named target",
                             "--config", str(settings), "--host", "destination"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.config.write_text("dofile(" + json.dumps(str(fragment)) + ")\n")
        self.rpc("server.config_reload", {})
        invoke = self.base + ["do", "--session", self.session, "--block", self.anchor, "named_focus"]
        before = rpc("session.list")
        self.assertNotEqual(subprocess.run(invoke, capture_output=True).returncode, 0)
        self.assertEqual(rpc("session.list"), before)
        block = {"block": {"flavor": "com.superlogical.terminal.shell", "label": "named target",
                           "options": {"command": ["/bin/sh", "-c", "sleep 60"]}}}
        made = rpc("session.create", {"label": "named host destination", "initial_windows": [{"layout": block}]})
        r = subprocess.run(invoke, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["resolved"]["session_id"], made["session_id"])
        rpc("session.new_window", {"session_id": made["session_id"], "layout": block})
        before = rpc("session.view", {"session_id": made["session_id"]})
        self.assertNotEqual(subprocess.run(invoke, capture_output=True).returncode, 0)
        self.assertEqual(rpc("session.view", {"session_id": made["session_id"]}), before)

    def test_scratch_palette_pins_rex_for_real_surface_controller(self):
        fragment = self.work / "scratch-pinned.lua"
        r, _ = self.run_json([BIN, "scratch", "palette", "--file", str(fragment), "--teerex", BIN,
                             "--socket", str(self.socket), "--rex", self.rex])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.config.write_text("dofile(" + json.dumps(str(fragment)) + ")\n")
        self.rpc("server.config_reload", {})
        invoke = self.base + ["do", "--session", self.session, "--block", self.anchor, "teerex_scratch_show"]
        r = subprocess.run(invoke, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["outcome"], "created_and_verified")

    def test_registered_seat_focus_palette_requires_live_registration(self):
        fragment = self.work / "seat-focus.lua"
        store = self.work / "seat-boards"
        store.mkdir(mode=0o700)
        cmd = [BIN, "surfaces", "palette", "focus", "--file", str(fragment), "--name", "jump_registered",
               "--title", "Jump registered seat", "--seat", "--board-store", str(store),
               "--socket", str(self.socket), "--teerex", BIN]
        r, _ = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.config.write_text("dofile(" + json.dumps(str(fragment)) + ")\n")
        self.rpc("server.config_reload", {})
        invoke = self.base + ["do", "--session", self.session, "--block", self.anchor, "jump_registered"]
        self.assertNotEqual(subprocess.run(invoke, capture_output=True).returncode, 0)
        register = [BIN, "boards", "seat", "register", "--store", str(store), "--host", "fixture",
                    "--socket", str(self.socket), "--session", self.session, "--block", self.anchor, "--owner", "fixture"]
        r = subprocess.run(register, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run(invoke, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["outcome"], "focused_and_verified")

    def test_palette_fragment_loaded_as_real_rex_action_no_overwrite(self):
        fragment = self.work / "palette.lua"
        marker = self.work / "palette-result"
        cmd = [BIN, "surfaces", "palette", "--file", str(fragment), "--name", "surface_test",
               "--title", "Open α ' inbox", "--label", "palette α", "--layout", "float", "--bounds", "[0.67,0,0.33,1]",
               "--", "/bin/sh", "-c", 'printf "%s" "$1" > "$2"; sleep 60', "sh", "α ' \"", str(marker)]
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(v["registered_in_running_server"])
        self.assertEqual(fragment.stat().st_mode & 0o777, 0o600)
        original = fragment.read_bytes()
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(fragment.read_bytes(), original)
        check = subprocess.run([self.rex, "config", "check", str(fragment), "--json"], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr + check.stdout)
        self.config.write_text("dofile(" + json.dumps(str(fragment)) + ")\n")
        self.rpc("server.config_reload", {})
        actions = subprocess.check_output(self.base + ["actions", "--json"], text=True)
        self.assertIn("surface_test", actions)
        response = json.loads(subprocess.check_output(self.base + ["do", "--session", self.session, "--block", self.anchor, "surface_test"], text=True))
        self.assertEqual(response["outcome"], "created_and_verified")
        self.assertEqual(response["actual"]["layer_kind"], "floating")
        self.rect(response["actual"]["rect"], [.67, 0, .33, 1])
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(.02)
        self.assertEqual(marker.read_text(), "α ' \"")
        self.config.write_text("")
        self.rpc("server.config_reload", {})

    def prepare_install(self, name="managed_surface"):
        fragment = self.work / (name + ".lua")
        r, _ = self.run_json([BIN, "surfaces", "palette", "--file", str(fragment), "--name", name,
                             "--title", "Managed Surface", "--label", "managed", "--layout", "tab", "--", "/bin/echo", "managed palette program"])
        self.assertEqual(r.returncode, 0)
        cmd = [BIN, "surfaces", "palette", "install", "--socket", str(self.socket), "--init", str(self.config),
               "--file", str(fragment), "--plan", str(self.work / (name + ".plan.json"))]
        return fragment, cmd

    def reset_config(self):
        self.config.write_text("")
        self.rpc("server.config_reload", {})

    def install_menu(self, kind, settings, binary=BIN):
        fragment = self.work / (kind + ".lua")
        config = self.work / (kind + ".json")
        config.write_text(json.dumps(settings))
        cmd = [BIN, "surfaces", "palette", kind, "--file", str(fragment), "--teerex", binary,
               "--profiles" if kind == "agents" else "--config", str(config)]
        if kind == "agents":
            cmd += ["--rex", self.rex]
        r, prepared = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(fragment.stat().st_mode & 0o777, 0o600)
        original = self.config.read_bytes()
        self.assertFalse(prepared["registered_in_running_server"])
        r, refused = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(original, self.config.read_bytes())
        cmd = [BIN, "surfaces", "palette", "install", "--socket", str(self.socket), "--init", str(self.config),
               "--file", str(fragment), "--plan", str(self.work / (kind + ".plan"))]
        r, plan = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(set(plan["plan"]["names"]), set(prepared["names"]))
        self.assertEqual(original, self.config.read_bytes())
        r, installed = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(installed["observed_actions"]), len(prepared["names"]))
        self.addCleanup(self.reset_config)
        return prepared["names"]

    def test_generated_host_menu_installs_all_actions_and_opens_named_workspace(self):
        label = "workspace α ' $(literal)"
        marker = self.work / "workspace ran"
        hosts = dict(schema_version=1, hosts=dict(disposable=dict(host_id="test", transport="local", home=str(self.work),
                    platform="macos-arm64" if sys.platform == "darwin" else "linux-x86_64",
                    socket=str(self.socket), rex=self.rex, teerex=BIN, store=str(self.work),
                    workspaces={label: dict(cwd=str(self.work), session="menu " + self.work.name,
                    argv=[sys.executable, "-c", "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('literal α')"]),
                    "Other": dict(cwd=str(self.work), argv=["/bin/sh"])})))
        names = self.install_menu("hosts", hosts)
        self.assertEqual(len(names), 2)
        actions = self.rpc("client.keymap", {})["actions"]
        name = next(a["name"] for a in actions if a.get("title") == "disposable: " + label)
        r = subprocess.run(self.base + ["do", "--session", self.session, "--block", self.anchor, name],
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads(r.stdout)
        self.assertEqual(result["outcome"], "created_and_verified")
        sid = result["actual"]["session_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": sid}))
        self.assertEqual(result["actual"]["label"], label)
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(.02)
        self.assertEqual(marker.read_text(), "literal α")

    def test_generated_agent_menu_runs_managed_ack_and_brief_in_visible_tab(self):
        fixture = self.work / "agent.py"
        log = self.work / "agent-input"
        fixture.write_text("import os,shlex,subprocess,sys,termios,tty\n"
                           "tty.setraw(0, termios.TCSANOW)\nos.write(1,b'\\x1b[?2004h')\n"
                           "protocol=sys.argv[-1]\n"
                           "line=protocol.split('Acknowledge this protocol now by running:\\n',1)[1].split('\\n',1)[0]\n"
                           "r=subprocess.run(shlex.split(line),capture_output=True)\n"
                           "assert r.returncode==0,r.stdout\n"
                           "buf=b''\nwhile True:\n part=os.read(0,65536)\n if not part: break\n buf+=part\n"
                           " if b'PALETTE TASK' in buf:\n  open(" + repr(str(log)) + ",'wb').write(buf)\n")
        registry = self.work / "agents"
        registry.mkdir(mode=0o700)
        settings = dict(schema_version=1, defaults=dict(registry=str(registry), socket=str(self.socket),
                        cwd=str(self.work), host="disposable", owner="operator", purpose="menu test", review_after_ms=60000),
                        profiles=dict(probe=dict(argv=[sys.executable, str(fixture)], harness="synthetic", protocol_mode="argument"),
                                      second=dict(argv=[sys.executable, str(fixture)], harness="synthetic", protocol_mode="argument")))
        names = self.install_menu("agents", settings)
        self.assertEqual(len(names), 2)
        brief = self.work / "brief α.txt"
        brief.write_text("PALETTE TASK α quotes ' $(literal)\n")
        actions = self.rpc("client.keymap", {})["actions"]
        name = next(a["name"] for a in actions if a.get("title") == "Start an agent: probe")
        older = self.work / "older-menu.lua"
        older.write_text((self.work / "agents.lua").read_text().replace('local version=rex.call("server.version")',
                                                                 'local version={api_revision=12}'))
        before = self.view()
        refused = subprocess.run(self.base + ["do", "--session", self.session, "--block", self.anchor,
                                 str(older), "--action", name], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("requires Rex API13", refused.stderr)
        self.assertEqual(before, self.view())
        self.assertEqual(list(registry.glob("agents-*.json")), [])
        r = subprocess.run(self.base + ["do", "--session", self.session, "--block", self.anchor, name,
                           "--args", json.dumps(dict(name="palette worker", brief_file=str(brief)))],
                           capture_output=True, text=True, timeout=20)
        if self.source["api_revision"] != 13:
            self.assertNotEqual(r.returncode, 0, r.stdout)
            self.assertIn("requires Rex API13", r.stderr)
            self.assertEqual(list(registry.glob("agents-*.json")), [])
            return
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        value = json.loads(r.stdout)
        self.assertTrue(value["protocol_acknowledged"])
        self.assertTrue(value["brief_attempted"])
        self.assertEqual(value["target"]["session_id"], self.session)
        self.assertEqual(value["starter"]["block_id"], self.anchor)
        self.assertEqual(value["report_to"]["block_id"], self.anchor)
        self.assertNotEqual(value["target"]["block_id"], self.anchor)
        for _ in range(100):
            if log.exists():
                break
            time.sleep(.02)
        self.assertIn(brief.read_bytes().strip(), log.read_bytes())
        # Palette invocation with no args opens a visible form rather than failing schema validation.
        r = subprocess.run(self.base + ["do", "--session", self.session, "--block", self.anchor, name],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        form = json.loads(r.stdout)
        self.assertEqual(form["outcome"], "agent_form_opened")
        self.assertEqual(form["agent_launch"], "not_yet_attempted")
        bid = form["created"]["block_ids"][0]
        self.assertEqual(self.view()["active_window_id"], form["created"]["window_id"])
        # Drive only the fixture's visible form. Managed launch must retain the original invoking starter.
        subprocess.check_call(self.base + ["send", "--session", self.session, "--block", bid,
                                           "interactive worker\n" + str(brief) + "\n"])
        records = []
        for _ in range(200):
            records = [json.loads(path.read_text()) for path in registry.glob("agents-*.json")]
            if len(records) == 2 and all(v.get("brief_attempted") for v in records):
                break
            time.sleep(.025)
        self.assertEqual(len(records), 2, records)
        self.assertTrue(all(v["protocol_acknowledged"] and v["brief_attempted"] for v in records), records)
        self.assertTrue(all(v["starter"]["block_id"] == self.anchor for v in records))

    def test_palette_managed_plan_apply_preserves_config_and_verifies_action(self):
        self.config.write_text("-- Existing operator config α, preserved exactly.\n")
        self.addCleanup(self.reset_config)
        fragment, cmd = self.prepare_install()
        original = self.config.read_bytes()
        generation = self.rpc("client.keymap", {})["config"]["generation"]
        self.shim("import sys\nsys.exit(91)\n")
        self.env["TEEREX_REX"] = self.rex  # Embedded install must honor the shared explicit Rex pin.
        r, plan = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(plan["outcome"], "planned")
        self.assertFalse(plan["registered_in_running_server"])
        self.assertEqual(self.config.read_bytes(), original)
        r, applied = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(applied["outcome"], "registered_and_verified")
        self.assertTrue(applied["registered_in_running_server"])
        self.assertEqual(self.config.read_bytes(), original + plan["plan"]["append_exactly"].encode())
        self.assertEqual(applied["observed_config"]["generation"], generation + 1)
        self.assertEqual(applied["observed_action"]["name"], "managed_surface")
        result = json.loads(subprocess.check_output(self.base + ["do", "--session", self.session, "managed_surface"], text=True))
        self.assertEqual(result["outcome"], "created_and_verified")
        self.assertEqual(result["actual"]["label"], "managed")
        stable = self.config.read_bytes()
        r, _ = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
        self.assertEqual(r.returncode, 1, "no duplicate append on repeated apply")
        self.assertEqual(self.config.read_bytes(), stable)

    def test_palette_plan_rejects_changed_source_init_plan_and_wrong_server_config(self):
        self.addCleanup(self.reset_config)
        for changed in ("source", "init", "plan"):
            self.reset_config()
            fragment, cmd = self.prepare_install("changed_" + changed)
            r, plan = self.run_json(cmd)
            self.assertEqual(r.returncode, 0, r.stdout)
            path = fragment if changed == "source" else self.config if changed == "init" else Path(cmd[-1])
            path.write_bytes(path.read_bytes() + b"\n")
            stable = self.config.read_bytes()
            generation = self.rpc("client.keymap", {})["config"]["generation"]
            r, refused = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertFalse(refused["registered_in_running_server"])
            self.assertFalse(refused["config_updated"])
            self.assertEqual(self.config.read_bytes(), stable)
            self.assertEqual(self.rpc("client.keymap", {})["config"]["generation"], generation)
        fragment, cmd = self.prepare_install("wrong_config")
        other = self.work / "not-running-init.lua"
        other.write_text("-- not the running configuration\n")
        cmd[cmd.index("--init") + 1] = str(other)
        r, refused = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(refused["failure_reason"], "init_is_not_selected_servers_observed_config")
        self.assertEqual(other.read_text(), "-- not the running configuration\n")

    def test_palette_reload_lost_evidence_stays_unregistered_and_keeps_preserved_bytes(self):
        self.addCleanup(self.reset_config)
        fragment, cmd = self.prepare_install("missing_readback")
        original = self.config.read_bytes()
        r, plan = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout)
        # The actual selected server loads the real fragment, but its final action evidence is lost.
        self.shim("import json,subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True)\n"
                  "if r.returncode:sys.stderr.buffer.write(r.stderr);sys.exit(r.returncode)\n"
                  "v=json.loads(r.stdout)\n"
                  f"if 'client.keymap' in sys.argv and 'dofile' in open({str(self.config)!r}).read():v['actions']=[a for a in v.get('actions',[]) if a.get('name')!='missing_readback']\n"
                  "print(json.dumps(v))\n")
        r, result = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(result["config_updated"])
        self.assertFalse(result["registered_in_running_server"])
        self.assertFalse(result["automatic_rollback"])
        self.assertEqual(result["failure_reason"], "registration_not_verified")
        self.assertEqual(self.config.read_bytes(), original + plan["plan"]["append_exactly"].encode())

    def shim(self, source):
        directory = self.work / "shim"
        directory.mkdir(exist_ok=True)
        path = directory / "rex"
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]

    def test_lost_receipt_is_uncertain_without_retry_or_close(self):
        before = self.view()
        self.shim("import json,subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                  "for line in r.stdout.splitlines():\n"
                  " if json.loads(line)['event']=='attempt':sys.stdout.buffer.write(line+b'\\n')\n"
                  "sys.stdout.flush();sys.stderr.buffer.write(b'\\xff\\x00');sys.exit(77)\n")
        r, v = self.run_json(self.command("tab"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["outcome"], "uncertain")
        self.assertIsNone(v["created"])
        self.assertIsNone(v["actual"])
        self.assertFalse(v["retry_safe"])
        self.assertEqual(base64.b64decode(v["backend_stderr_base64"]), b"\xff\x00")
        self.assertEqual(len(self.view()["windows"]), len(before["windows"]) + 1)

    def test_actual_mismatch_and_missing_readback_never_claim_success(self):
        # Execute real creation, then alter/drop only the evidence at the transport boundary.
        for alteration, expected in [("v['result']['outcome']='geometry_mismatch';v['result']['requested_geometry_verified']=False", "geometry_mismatch"),
                                     ("v['result'].pop('actual',None);v['result']['outcome']='uncertain';v['result']['failure_reason']='created_geometry_unavailable'", "uncertain")]:
            self.shim("import json,subprocess,sys\n"
                      f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                      "for line in r.stdout.splitlines():\n"
                      " v=json.loads(line)\n"
                      f" if v['event']=='result': {alteration}\n"
                      " print(json.dumps(v),flush=True)\n")
            r, v = self.run_json(self.command("tab"))
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertEqual(v["outcome"], expected)
            self.assertIsNotNone(v["created"])
            if expected == "uncertain":
                self.assertIsNone(v["actual"])

    def test_deadline_cancellation_missing_endpoint_and_help(self):
        ready = self.work / "ready"
        self.shim("import signal,time\nfrom pathlib import Path\n"
                  f"Path({str(ready)!r}).touch()\n"
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n")
        for sig, expected in [(None, 124), (signal.SIGINT, 130), (signal.SIGTERM, 143)]:
            ready.unlink(missing_ok=True)
            p = subprocess.Popen(self.command("tab", extra=["--timeout-ms", "200" if sig is None else "5000"]),
                                 env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if sig is not None:
                for _ in range(100):
                    if ready.exists():
                        break
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                p.send_signal(sig)
            out, err = p.communicate(timeout=4)
            self.assertEqual(p.returncode, expected, err)
            self.assertNotEqual(json.loads(out)["outcome"], "created_and_verified")
        self.env["PATH"] = str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"]
        cmd = self.command("tab")
        cmd[cmd.index("--socket") + 1] = str(self.work / "missing.sock")
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.work / "missing.sock").exists())
        self.assertEqual(v["outcome"], "uncertain")
        for args in [["--help"], ["open", "--help"], ["inspect", "--help"], ["rename", "--help"], ["palette", "--help"]]:
            r = subprocess.run([BIN, "surfaces", *args], capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 0)
            self.assertIn("NEW pane share", r.stdout)


if __name__ == "__main__":
    unittest.main()
