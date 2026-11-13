"""Public run-visible acceptance against disposable Rex only (Linux/Mac).

TEEREX_BIN may name the combined CLI or items/run/test_visible_cli.zig build.
REX_BIN must select the deliberately downloaded disposable test Rex.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())


def raw(node):
    return node["content"].encode() if node["encoding"] == "utf8" else base64.b64decode(node["content"], validate=True)


class VisibleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = str(Path(os.environ.get("REX_BIN") or shutil.which("rex") or "MISSING_REX").resolve())
        cls.temp = tempfile.TemporaryDirectory(prefix="tvisible-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                      "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
                                     stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("disposable server startup failed")
        cls.version = cls.rpc("server.version", {})
        print("Real Rex:", cls.version, flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def rpc(cls, method, params):
        return json.loads(subprocess.check_output(cls.base + ["api", "call", method, json.dumps(params)], timeout=10))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.envfile = self.work / "env.json"
        self.envfile.write_text(json.dumps({"PATH": "/usr/bin:/bin", "TEEREX_LITERAL": "a\n'α😀", "EMPTY": ""}))
        self.stdin = self.work / "stdin"
        self.stdin.write_bytes(b"input\x00\xff\n\n")
        self.session = self.rpc("session.create", {"label": "run-visible disposable"})["session_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": self.session}))
        self.runtime_env = dict(os.environ, REX_SERVER="unix:///tmp/wrong.sock", REX_BLOCK="block:wrong",
                                PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""))
        self.anchor = None

    def command(self, script="print('hello visible')", *, argv=None, extra=(), rex=None):
        return [BIN, "--rex", rex or self.rex, "run-visible", "--socket", str(self.socket), "--session", self.session,
                "--cwd", str(self.work), "--env-file", str(self.envfile), "--stdin-file", str(self.stdin),
                "--app", "teerex-test", "--title", "Visible α command", *extra,
                "--", *(argv if argv is not None else [sys.executable, "-c", script])]

    def invoke(self, *args, **kwargs):
        r = subprocess.run(self.command(*args, **kwargs), env=self.runtime_env, capture_output=True, text=True, timeout=20)
        self.assertTrue(r.stdout, r.stderr)
        v = json.loads(r.stdout)
        if v.get("storage_retained") and not v.get("full_output_requested"):
            self.addCleanup(shutil.rmtree, v["storage_dir"], True)
        return r, v

    def assert_good(self, r, v):
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(v["success"])
        self.assertEqual(v["outcome"], "exit_reported")
        self.assertFalse(v["retry_safe"])
        self.assertFalse(v["all_descendants_verified_gone"])
        self.assertEqual(v["source"]["api_revision"], 13)
        self.assertEqual(v["placement"]["receipt"]["actual"]["block_id"], v["created"]["block_id"])
        self.assertEqual(v["pane_identity_report"]["block_id"], v["created"]["block_id"])

    def blocks(self):
        return {b["block_id"] for b in self.rpc("session.list_blocks", {"session_id": self.session})["blocks"]}

    def anchor_pane(self):
        r = subprocess.run([BIN, "--rex", self.rex, "surfaces", "open", "--socket", str(self.socket),
                            "--session", self.session, "--layout", "tab", "--label", "unrelated sentinel",
                            "--", "/bin/sleep", "60"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.anchor = json.loads(r.stdout)["created"]["block_id"]
        return self.anchor

    def test_exact_argv_cwd_env_binary_stdin_and_owned_close(self):
        anchor = self.anchor_pane()
        before = self.rpc("session.view", {"session_id": self.session})
        arguments = ["", "a'b\"", "a\nb", "α😀", "$(touch SHOULD_NOT_EXIST)", "semi;colon"]
        script = "import os,sys,json;print(json.dumps([sys.argv[1:],os.getcwd(),os.environ['TEEREX_LITERAL'],os.environ['EMPTY'],sys.stdin.buffer.read().hex(),os.environ['REX_SESSION'],os.environ['REX_BLOCK'],os.getenv('REX_SERVER')]))"
        r, v = self.invoke(argv=[sys.executable, "-c", script, *arguments])
        self.assert_good(r, v)
        self.assertEqual(json.loads(raw(v["stdout"])), [arguments, str(self.work.resolve()), "a\n'α😀", "", self.stdin.read_bytes().hex(), self.session, v["created"]["block_id"], None])
        self.assertFalse((self.work / "SHOULD_NOT_EXIST").exists())
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assertEqual(self.blocks(), {anchor})
        after = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual(after["windows"][0]["focused_block_id"], before["windows"][0]["focused_block_id"])

    def test_anchored_placement_and_keep_open_actual_exit(self):
        anchor = self.anchor_pane()
        r, v = self.invoke("print('retained terminal')", extra=["--layout", "tiled", "--anchor", anchor, "--direction", "right", "--ratio", ".23", "--keep-open"])
        self.assert_good(r, v)
        self.assertEqual(self.blocks(), {anchor, v["created"]["block_id"]})
        self.assertAlmostEqual(v["placement"]["receipt"]["actual"]["pane_share"], .23)
        self.assertTrue(v["pane_retained_on_request"])
        self.assertFalse(v["cleanup"]["attempted"])
        self.assertEqual(v["exit_report"]["exit_code"], 0)
        status = self.rpc("com.superlogical.terminal.program_status", {"session_id": self.session, "block_id": v["created"]["block_id"], "args": {}})
        self.assertEqual(status["records"][0]["state"], "done")
        self.assertEqual(status["records"][0]["app"], "teerex-test")
        self.assertEqual(status["records"][0]["title"], "Visible α command")

    def test_exit7_signal_and_silent_wait(self):
        for script, code, sig in [("import sys;sys.exit(7)", 7, None),
                                  ("import os,signal;os.kill(os.getpid(),signal.SIGTERM)", None, 15)]:
            r, v = self.invoke(script)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual(v["exit_report"]["exit_code"], code)
            self.assertEqual(v["exit_report"]["signal"], sig)
            self.assertEqual(v["outcome"], "exit_reported")
            self.assertTrue(v["cleanup"]["block_absence_verified"])
        r, v = self.invoke("import time;time.sleep(3.2);print('late bytes')", extra=["--timeout-ms", "5000"])
        self.assert_good(r, v)
        self.assertGreaterEqual(v["exit_report"]["elapsed_ms"], 3200)
        self.assertEqual(raw(v["stdout"]), b"late bytes\n")

    def test_split_utf8_binary_trailing_bytes_and_large_output(self):
        script = "import os,time;os.write(1,b'head\\xf0\\x9f');time.sleep(.05);os.write(1,b'\\x98\\x80tail\\n\\n\\0');os.write(2,b'\\xff\\x80bad')"
        r, v = self.invoke(script)
        self.assert_good(r, v)
        self.assertEqual(raw(v["stdout"]), "head😀tail\n\n\0".encode())
        self.assertEqual(raw(v["stderr"]), b"\xff\x80bad")
        self.assertTrue(v["stdout"]["complete"])
        self.assertTrue(v["stderr"]["complete"])
        r, v = self.invoke("import os;os.write(1,b'A'*3000000);os.write(2,b'B'*2000000)", extra=["--max-bytes", "257"])
        self.assert_good(r, v)
        self.assertEqual(v["stdout"]["bytes_seen"], 3000000)
        self.assertEqual(v["stderr"]["bytes_seen"], 2000000)
        self.assertEqual(sum(v[s]["retained_bytes"] for s in ("stdout", "stderr")), 257)
        for stream, byte in [("stdout", b"A"), ("stderr", b"B")]:
            self.assertEqual(raw(v[stream]), byte * v[stream]["retained_bytes"])
            self.assertFalse(v[stream]["complete"])
        r, v = self.invoke("import os;os.write(1,b'abc\\xf0\\x9f\\x98\\x80')", extra=["--max-bytes", "4"])
        self.assert_good(r, v)
        self.assertEqual(v["stdout"]["encoding"], "base64")
        self.assertEqual(raw(v["stdout"]), b"abc\xf0")

    def test_full_output_lifetime_privacy_and_disk_bound(self):
        output = self.work / "full-output"
        r, v = self.invoke("import os;os.write(1,b'A'*100000);os.write(2,b'B'*70000)", extra=["--output-dir", str(output), "--max-bytes", "7"])
        self.assert_good(r, v)
        self.assertTrue(v["storage_retained"])
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        for stream, byte, count in [("stdout", b"A", 100000), ("stderr", b"B", 70000)]:
            self.assertEqual(Path(v[stream]["full_path"]).read_bytes(), byte * count)
            self.assertTrue(v[stream]["full_complete"])
            self.assertEqual(stat.S_IMODE(Path(v[stream]["full_path"]).stat().st_mode), 0o600)
        r, v = self.invoke("import os;os.write(1,b'x'*(65*1024*1024))", extra=["--output-dir", str(self.work / "too-large")])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "full_output_limit_exceeded")
        self.assertEqual(sum(Path(v[s]["full_path"]).stat().st_size for s in ("stdout", "stderr")), 64 * 1024 * 1024)
        self.assertFalse(v["stdout"]["full_complete"])
        self.assertTrue(v["cleanup"]["block_absence_verified"])

    def long_command(self):
        pidfile = self.work / "pid"
        script = ("import os,pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                  f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));"
                  "print('before stop',flush=True);time.sleep(60)")
        return pidfile, script

    def assert_stopped(self, pid):
        for _ in range(100):
            status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
            if not status or status.startswith("Z"):
                return
            time.sleep(.02)
        self.fail(f"fixture still running: {pid}")

    def test_deadline_and_cancel_int_term_override_keep_open(self):
        pidfile, script = self.long_command()
        r, v = self.invoke(script, extra=["--timeout-ms", "400", "--keep-open"])
        self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
        self.assertEqual(v["exit_report"]["signal"], 9)
        self.assertEqual(v["outcome"], "deadline_exceeded")
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assert_stopped(int(pidfile.read_text()))
        for sig in (signal.SIGINT, signal.SIGTERM):
            pidfile.unlink()
            p = subprocess.Popen(self.command(script, extra=["--keep-open"]), env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(200):
                    if pidfile.exists() or p.poll() is not None:
                        break
                    time.sleep(.02)
                self.assertTrue(pidfile.exists())
                # The still-running child must have an actual working report, not just a final done/error.
                output_blocks = self.blocks()
                self.assertEqual(len(output_blocks), 1)
                status = self.rpc("com.superlogical.terminal.program_status", {"session_id": self.session,
                    "block_id": next(iter(output_blocks)), "args": {}})
                self.assertEqual(status["records"][0]["state"], "working")
                self.assertEqual(status["records"][0]["app"], "teerex-test")
                self.assertEqual(status["records"][0]["title"], "Visible α command")
                p.send_signal(sig)
                out, err = p.communicate(timeout=10)
                v = json.loads(out)
                self.assertEqual(p.returncode, 128 + sig, out + err)
                self.assertEqual(v["outcome"], "cancel_requested")
                self.assertTrue(v["cleanup"]["block_absence_verified"])
                self.assertIn(b"before stop", raw(v["stdout"]))
                self.assert_stopped(int(pidfile.read_text()))
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait()

    def test_pipe_eof_is_not_exit_and_child_group_scope_is_honest(self):
        r, v = self.invoke("import os,time;os.close(1);os.close(2);time.sleep(60)", extra=["--timeout-ms", "400"])
        self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
        self.assertGreaterEqual(v["exit_report"]["elapsed_ms"], 400)
        self.assertEqual(v["exit_report"]["signal"], 15)
        sentinel = self.anchor_pane()
        for detached in (False, True):
            pidfile = self.work / ("detached" if detached else "same-group")
            grand = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
            script = ("import subprocess,sys,pathlib,time;"
                      f"p=subprocess.Popen([sys.executable,'-c',{grand!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session={detached});"
                      f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid));time.sleep(.1)")
            try:
                r, v = self.invoke(script)
                self.assert_good(r, v)
                pid = int(pidfile.read_text())
                if detached:
                    os.kill(pid, 0)
                else:
                    self.assert_stopped(pid)
                self.assertIn(sentinel, self.blocks())
                self.assertFalse(v["all_descendants_verified_gone"])
            finally:
                if pidfile.exists():
                    with __import__('contextlib').suppress(ProcessLookupError):
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)

    def test_bad_cwd_env_stdin_and_old_api_refuse_before_creation(self):
        before = self.blocks()
        r, v = self.invoke(argv=["/teerex-test-nonexistent-executable"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "launch_error")
        self.assertIsNone(v["exit_report"]["exit_code"])
        self.assertIsNone(v["exit_report"]["signal"])
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assertEqual(self.blocks(), before)
        command = self.command()
        command[command.index("--cwd") + 1] = str(self.work / "missing")
        r = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cwd_not_directory", r.stdout)
        self.assertEqual(self.blocks(), before)
        self.envfile.write_text('{"REX_BLOCK":"spoof"}')
        r = subprocess.run(self.command(), capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2)
        self.assertIn("reserved", r.stderr)
        self.envfile.write_text('{}')
        self.stdin.unlink()
        os.mkfifo(self.stdin)
        r, v = self.invoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("regular_file_required", v["failure_reason"])
        self.assertEqual(self.blocks(), before)
        self.stdin.unlink()
        self.stdin.write_bytes(b'')
        wrapper, log = self.wrapper("old-api")
        r, v = self.invoke(rex=wrapper)
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires_observed_api13", v["failure_reason"])
        self.assertFalse(log.exists(), "old API refusal must precede surfaces mutation")
        self.assertEqual(self.blocks(), before)

    def wrapper(self, mode):
        wrapper = self.work / (mode + "-rex")
        log = self.work / (mode + "-calls")
        wrapper.write_text(f"#!{sys.executable}\n" +
            "import json,os,subprocess,sys\n" +
            f"real={self.rex!r}; mode={mode!r}; log={str(log)!r}\n" +
            "a=sys.argv[1:]\n"
            "operation=None\n"
            "if '--args' in a:\n"
            " try: operation=json.loads(a[a.index('--args')+1]).get('operation')\n"
            " except (ValueError,IndexError): pass\n"
            "if operation:\n"
            " with open(log,'a') as f:f.write(operation+'\\n')\n"
            "p=subprocess.run([real,*a],capture_output=True)\n"
            "out=p.stdout\n"
            "if mode=='old-api' and 'server.version' in a: out=json.dumps({'api_revision':12}).encode()\n"
            "if mode=='foreign-identity' and operation=='open':\n"
            " from pathlib import Path\n"
            " import time\n"
            " root=Path(json.loads(a[a.index('--args')+1])['argv'][-1]); ready=root/'ready.json'\n"
            " for unused in range(100):\n"
            "  if ready.exists(): break\n"
            "  time.sleep(.02)\n"
            " value=json.loads(ready.read_text());value['machine']='different-observed-kernel';ready.write_text(json.dumps(value))\n"
            "if (mode=='drop-create' and operation=='open') or (mode=='drop-close' and operation=='close'): out=b''\n"
            "if mode=='drop-create-final' and operation=='open': out=b'\\n'.join(l for l in out.splitlines() if b'\"event\":\"result\"' not in l)+b'\\n'\n"
            "sys.stdout.buffer.write(out);sys.stderr.buffer.write(p.stderr);sys.exit(p.returncode)\n")
        wrapper.chmod(0o700)
        return str(wrapper), log

    def test_lost_creation_and_close_acks_are_not_retried(self):
        sentinel = self.anchor_pane()
        for mode in ("drop-create", "drop-create-final", "drop-close"):
            wrapper, log = self.wrapper(mode)
            marker = self.work / (mode + "-ran")
            r, v = self.invoke(f"from pathlib import Path;Path({str(marker)!r}).write_text('ran')", rex=wrapper)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertFalse(v["success"])
            calls = log.read_text().splitlines()
            self.assertEqual(calls.count("open"), 1)
            self.assertEqual(v["cleanup"]["block_absence_verified"], mode == "drop-create-final")
            self.assertTrue(v["storage_retained"])
            if mode == "drop-create-final":
                self.assertIsNotNone(v["created"])
                self.assertEqual(v["outcome"], "creation_or_placement_uncertain")
                self.assertFalse(marker.exists())
                self.assertEqual(calls.count("close"), 1)
                self.assertNotIn(v["created"]["block_id"], self.blocks())
            elif mode == "drop-create":
                self.assertIsNone(v["created"])
                self.assertEqual(v["outcome"], "creation_or_placement_uncertain")
                self.assertFalse(marker.exists(), "unacknowledged creation must not execute argv")
                self.assertEqual(calls.count("close"), 0)
                self.assertEqual(len(self.blocks()), 2)
            else:
                self.assertIsNotNone(v["created"])
                self.assertTrue(marker.exists())
                self.assertEqual(calls.count("close"), 1)
                self.assertNotIn(v["created"]["block_id"], self.blocks())
            self.assertIn(sentinel, self.blocks())

    def test_observed_foreign_identity_refuses_without_executing_argv(self):
        wrapper, log = self.wrapper("foreign-identity")
        marker = self.work / "must-not-run"
        r, v = self.invoke(f"from pathlib import Path;Path({str(marker)!r}).touch()", rex=wrapper)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "foreign_pane_host_or_identity_refused")
        self.assertFalse(marker.exists())
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assertEqual(log.read_text().splitlines(), ["open", "close"])
        self.assertFalse((Path(v["storage_dir"]) / "permit.json").exists())

    def test_supervisor_loss_leaves_actual_exit_unknown_not_pane_death(self):
        output = self.work / "supervisor-loss"
        pidfile = self.work / "survivor"
        script = ("import os,pathlib,signal,time;"
                  f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));"
                  "os.kill(os.getppid(),signal.SIGKILL);time.sleep(60)")
        try:
            r, v = self.invoke(script, extra=["--timeout-ms", "200", "--output-dir", str(output)])
            self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
            self.assertIsNone(v["exit_report"])
            self.assertFalse(v["success"])
            self.assertTrue(v["cleanup"]["block_absence_verified"])
            self.assertFalse(v["all_descendants_verified_gone"])
            pid = int(pidfile.read_text())
            os.kill(pid, 0)  # Closing the pane did NOT prove this child died.
            record = json.loads((output / "controller.json").read_text())
            self.assertEqual(record["created"], v["created"])
        finally:
            if pidfile.exists():
                with __import__('contextlib').suppress(ProcessLookupError):
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)

    def test_controller_sigkill_retains_known_ids_and_helper_own_deadline(self):
        output = self.work / "controller-loss"
        pidfile, script = self.long_command()
        p = subprocess.Popen(self.command(script, extra=["--timeout-ms", "700", "--output-dir", str(output)]),
                             env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(200):
                if pidfile.exists() or p.poll() is not None:
                    break
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            p.kill()
            out, err = p.communicate(timeout=5)
            self.assertEqual(p.returncode, -signal.SIGKILL)
            self.assertEqual(out, "")
            for _ in range(200):
                if (output / "result.json").exists():
                    break
                time.sleep(.02)
            result = json.loads((output / "result.json").read_text())
            self.assertEqual(result["stop_reason"], "deadline_exceeded")
            self.assertEqual(result["signal"], 9)
            self.assert_stopped(int(pidfile.read_text()))
            record = json.loads((output / "controller.json").read_text())
            self.assertFalse(record["cleanup"]["attempted"])
            self.assertIn(record["created"]["block_id"], self.blocks())
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()


if __name__ == "__main__":
    unittest.main()
