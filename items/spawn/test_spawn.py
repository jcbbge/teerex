"""Public spawn contract against a private, disposable Rex server.

REX_BIN and TEEREX_BIN select exact executables. No personal/default server is used.
"""
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


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/acceptance'))
from test_environment import isolated_environment

BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex")).resolve())


class SpawnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise RuntimeError("Put the explicitly selected test Rex on PATH")
        tmp = tempfile.TemporaryDirectory(prefix="tspawn-", dir="/tmp")
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
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
        self.env = dict(isolated_environment(), TEEREX_CLUTCH_DIR=str(self.work / "clutch"), PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""),
                        REX_SERVER="unix:///tmp/poison.sock", REX_SESSION="session:poison",
                        REX_BLOCK="block:poison", REX_CLIENT="client:poison")
        value = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--",
                                                                 "/bin/sh", "-c", "sleep 60"], timeout=10))
        self.session = value["session_id"]
        self.parent = value["initial_windows"][0]["block_ids"][0]

    def view(self):
        return self.rpc("session.view", {"session_id": self.session})

    def command(self, *argv, name="worker α", cwd=None, parent=None, report_session=None, timeout=5000):
        return [BIN, "spawn", "--socket", str(self.socket), "--session", self.session, "--name", name,
                "--cwd", str(cwd or self.work), "--report-to-session", report_session or self.session,
                "--report-to-block", parent or self.parent, "--timeout-ms", str(timeout), "--", *argv]

    def invoke(self, *argv, **kwargs):
        result = subprocess.run(self.command(*argv, **kwargs), capture_output=True, text=True, env=self.env, timeout=10)
        return result, json.loads(result.stdout) if result.stdout else None

    def test_exact_argv_environment_location_focus_and_retained_exit(self):
        before = self.view()
        cwd = self.work / "cwd ' α $(never)"
        cwd.mkdir()
        output = self.work / "worker.json"
        keys = ["REX_SESSION", "REX_BLOCK", "AGENT_SESSION", "AGENT_PANE", "LC_REX_SESSION", "LC_REX_BLOCK",
                "AGENT_NAME", "LC_AGENT_NAME", "AGENT_REPORT_TO", "LC_AGENT_REPORT_TO"]
        code = ("import json,os,sys; from pathlib import Path; "
                f"Path({str(output)!r}).write_text(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd(),"
                f"env={{k:os.getenv(k) for k in {keys!r}}})))")
        args = ["", "quote ' \"", "α\nnext", "$(touch NEVER); >&2", "--"]
        label = "worker ' α $(never)"
        report = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--", "/bin/sh", "-c", "sleep 60"], timeout=10))
        report_session = report["session_id"]
        report_block = report["initial_windows"][0]["block_ids"][0]
        report_before = self.rpc("session.view", {"session_id": report_session})
        result, packet = self.invoke(sys.executable, "-c", code, *args, name=label, cwd=cwd, parent=report_block, report_session=report_session)
        self.assertEqual(self.rpc("session.view", {"session_id": report_session}), report_before)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(packet["outcome"], "created_and_attached")
        self.assertEqual(packet["rex_executable"], self.rex)
        self.assertEqual(packet["cwd"], str(cwd))
        self.assertEqual(packet["cwd_source"], "explicit")
        self.assertIsNone(packet["failure_reason"])
        self.assertEqual(packet["backend_term"], {"Exited": 0})
        self.assertTrue(packet["attached_location_verified"])
        self.assertFalse(packet["automatic_close"])
        self.assertFalse(packet["retry_safe"])
        self.assertFalse(packet["exclusive_input_lease"])
        self.assertEqual(packet["agent_readiness"], "not_assessed")
        self.assertEqual(packet["source"], {k: self.source[k] for k in ("rex_version", "platform", "api_revision")})
        created = packet["created"]
        self.assertNotEqual(created["block_id"], self.parent)
        after = self.view()
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual(len(after["windows"]), len(before["windows"]) + 1)
        window = next(w for w in after["windows"] if w["window_id"] == created["window_id"])
        self.assertEqual(window["label"], label)
        for _ in range(100):
            if output.exists():
                break
            time.sleep(.02)
        actual = json.loads(output.read_text())
        self.assertEqual(actual["argv"], args)
        self.assertEqual(actual["cwd"], str(cwd.resolve()))
        expected = dict.fromkeys(["REX_SESSION", "AGENT_SESSION", "LC_REX_SESSION"], self.session)
        expected.update(dict.fromkeys(["REX_BLOCK", "AGENT_PANE", "LC_REX_BLOCK"], created["block_id"]))
        expected.update(dict.fromkeys(["AGENT_NAME", "LC_AGENT_NAME"], label))
        expected.update(dict.fromkeys(["AGENT_REPORT_TO", "LC_AGENT_REPORT_TO"], report_session + " " + report_block))
        self.assertEqual(actual["env"], expected)
        for _ in range(100):
            process = self.rpc("com.superlogical.terminal.process", {"session_id": self.session,
                               "block_id": created["block_id"], "args": {}})
            if process.get("last_exit") is not None:
                break
            time.sleep(.02)
        self.assertEqual(process["last_exit"]["exit_code"], 0)
        self.assertTrue(any(w["window_id"] == created["window_id"] for w in self.view()["windows"]))

    def test_default_cwd_uses_target_home_despite_client_home_and_pinned_rex(self):
        output = self.work / "default-cwd.json"
        code = f"import os;from pathlib import Path;Path({str(output)!r}).write_text(os.getcwd())"
        command = self.command(sys.executable, "-c", code)
        index = command.index("--cwd")
        del command[index:index + 2]
        for global_pin in (False, True):
            if global_pin and Path(BIN).name != "teerex":
                continue  # --rex is a combined-CLI global option; a standalone cartridge payload has no global options.
            with self.subTest(global_pin=global_pin):
                output.unlink(missing_ok=True)
                env = dict(self.env, HOME=str(self.work), PATH="/no-rex-here", TEEREX_REX=self.rex)
                if global_pin:
                    command_run = [BIN, "--rex", self.rex, *command[1:]]
                    env["TEEREX_REX"] = "/does/not/exist"
                else:
                    command_run = command
                result = subprocess.run(command_run, capture_output=True, text=True, env=env, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                packet = json.loads(result.stdout)
                self.assertEqual(packet["rex_executable"], self.rex)
                self.assertEqual(packet["cwd_source"], "target_home")
                self.assertEqual(packet["cwd"], str(Path.home()))
                for _ in range(100):
                    if output.exists(): break
                    time.sleep(.02)
                self.assertEqual(output.read_text(), packet["cwd"])

    def test_missing_report_target_and_encoded_limits_do_not_create(self):
        before = self.view()
        result, packet = self.invoke("/bin/true", parent="block:00000000-0000-0000-0000-000000000000")
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(packet["outcome"], "refused")
        self.assertEqual(packet["failure_reason"], "report_target_not_attached_terminal")
        self.assertFalse(packet["creation_attempt_frame_seen"])
        result, packet = self.invoke("/bin/echo", "<" * 11000)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(packet["failure_reason"], "encoded_spawn_exceeds_limit")
        self.assertFalse(packet["creation_attempt_frame_seen"])
        result, packet = self.invoke("/bin/echo", "x" * 48000)
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(packet)
        self.assertEqual(self.view(), before)

    def test_bad_cwd_never_executes_in_a_fallback_directory(self):
        output = self.work / "must-not-exist"
        result, packet = self.invoke(sys.executable, "-c", f"from pathlib import Path;Path({str(output)!r}).touch()",
                                     cwd=self.work / "missing")
        self.assertIn(result.returncode, [0, 1], result.stderr + result.stdout)
        self.assertIsNotNone(packet)
        time.sleep(.1)
        self.assertFalse(output.exists())
        self.assertEqual(packet["program_start"], "not_assessed")

    def shim(self, body):
        directory = self.work / "shim"
        directory.mkdir(exist_ok=True)
        path = directory / "rex"
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]

    def test_backend_failures_preserve_bounded_diagnostics_and_termination(self):
        before = self.view()
        for body, term, diagnostic, outcome in [
            ("import sys\nsys.exit(7)\n", {"Exited": 7}, "", "backend_error"),
            ("import sys\nsys.stderr.write('synthetic failure:'+'x'*5000);sys.exit(7)\n", {"Exited": 7}, "synthetic failure:" + "x" * (4096 - 18), "backend_error"),
            ("pass\n", {"Exited": 0}, "", "uncertain"),
            ("import sys\nsys.stdout.write('{');sys.exit(7)\n", {"Exited": 7}, "", "uncertain"),
            ("import sys\nprint('not-json');sys.exit(7)\n", None, "", "uncertain"),
            ("print('{',end='')\n", {"Exited": 0}, "", "uncertain"),
            ("import os,signal\nos.kill(os.getpid(),signal.SIGTERM)\n", {"Signal": 15}, "", "uncertain"),
        ]:
            with self.subTest(body=body):
                self.shim(body)
                result, packet = self.invoke("/bin/true")
                self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
                self.assertEqual(packet["outcome"], outcome)
                if term is None:
                    self.assertIsNotNone(packet["failure_reason"])
                else:
                    self.assertEqual(packet["failure_reason"], "rex_backend_nonzero_exit" if outcome == "backend_error" else "rex_transport_incomplete")
                self.assertEqual(packet["backend_term"], term)
                self.assertEqual(result.stderr, "teerex spawn: Rex backend: " + diagnostic + "\n" if diagnostic else "")
                self.assertIsNone(packet["created"])
                self.assertFalse(packet["creation_attempt_frame_seen"])
                self.assertFalse(packet["retry_safe"])
                self.assertFalse(packet["automatic_close"])
        self.env["PATH"] = str(self.work / "no-rex")
        result, packet = self.invoke("/bin/true")
        self.assertEqual(packet["outcome"], "backend_error")
        self.assertEqual(packet["failure_reason"], "FileNotFound")
        self.assertIsNone(packet["backend_term"])
        self.shim("pass\n")
        (self.work / "shim" / "rex").chmod(0o644)
        self.env["PATH"] = str(self.work / "shim")
        result, packet = self.invoke("/bin/true")
        self.assertEqual(packet["outcome"], "backend_error")
        self.assertEqual(packet["failure_reason"], "AccessDenied")
        self.assertIsNone(packet["backend_term"])
        self.env["TEEREX_REX"] = "relative-rex"
        result, packet = self.invoke("/bin/true")
        self.assertEqual(packet["outcome"], "backend_error")
        self.assertEqual(packet["failure_reason"], "RexExecutableMustBeAbsolute")
        self.assertIsNone(packet["rex_executable"])
        self.assertEqual(self.view(), before)

    def test_lost_creation_receipt_is_uncertain_and_does_not_retry_or_close(self):
        for retain_created, malformed in [(False, False), (True, False), (True, True)]:
            with self.subTest(retain_created=retain_created, malformed=malformed):
                before = self.view()
                events = ['source', 'attempt', 'created'] if retain_created else ['source', 'attempt']
                self.shim("import json,subprocess,sys\n"
                          f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                          "for line in r.stdout.splitlines():\n"
                          f" if json.loads(line)['event'] in {events!r}:sys.stdout.buffer.write(line+b'\\n')\n"
                          + ("sys.stdout.buffer.write(b'not-json\\n')\n" if malformed else "")
                          + "sys.stdout.flush();sys.exit(77)\n")
                result, packet = self.invoke("/bin/sh", "-c", "sleep 60")
                self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
                self.assertEqual(packet["outcome"], "uncertain")
                self.assertEqual(packet["source"], {k: self.source[k] for k in ("rex_version", "platform", "api_revision")})
                self.assertTrue(packet["creation_attempt_frame_seen"])
                self.assertFalse(packet["attached_location_verified"])
                self.assertIsNotNone(packet["failure_reason"])
                if malformed:
                    self.assertNotEqual(packet["failure_reason"], "rex_transport_incomplete")
                    self.assertIsNone(packet["backend_term"])
                else:
                    self.assertEqual(packet["failure_reason"], "rex_transport_incomplete")
                    self.assertEqual(packet["backend_term"], {"Exited": 77})
                self.assertFalse(packet["retry_safe"])
                self.assertFalse(packet["automatic_close"])
                after = self.view()
                self.assertEqual(len(after["windows"]), len(before["windows"]) + 1)
                self.assertEqual(after["active_window_id"], before["active_window_id"])
                if retain_created:
                    window = next(w for w in after["windows"] if w["window_id"] == packet["created"]["window_id"])
                    self.assertIn(packet["created"]["block_id"], [b["block_id"] for layer in window["layers"] for b in layer["blocks"]])
                else:
                    self.assertIsNone(packet["created"])

    def test_transport_deadline_and_cancellation_are_not_creation_success(self):
        ready = self.work / "ready"
        self.shim(f"import signal,time\nfrom pathlib import Path\nPath({str(ready)!r}).touch()\n"
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n")
        before = self.view()
        for sig, expected in [(None, 124), (signal.SIGINT, 130), (signal.SIGTERM, 143)]:
            with self.subTest(sig=sig):
                ready.unlink(missing_ok=True)
                proc = subprocess.Popen(self.command("/bin/true", timeout=200 if sig is None else 5000),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
                self.addCleanup(lambda p=proc: p.poll() is None and p.kill())
                if sig is not None:
                    for _ in range(100):
                        if ready.exists():
                            break
                        time.sleep(.01)
                    self.assertTrue(ready.exists())
                    proc.send_signal(sig)
                out, err = proc.communicate(timeout=4)
                self.assertEqual(proc.returncode, expected, err)
                packet = json.loads(out)
                self.assertEqual(packet["outcome"], "deadline_exceeded" if sig is None else "cancel_requested")
                self.assertIsNone(packet["created"])
                self.assertFalse(packet["attached_location_verified"])
                self.assertFalse(packet["retry_safe"])
                self.assertEqual(packet["failure_reason"], "rex_transport_incomplete")
                self.assertEqual(packet["backend_term"], {"Signal": signal.SIGKILL})
        self.assertEqual(self.view(), before)

    def test_usage_rejects_before_contact_and_missing_endpoint_never_autostarts(self):
        valid = self.command("/bin/true")[2:]
        for args in [[], ["--help", "x"], ["--socket", "relative"], valid[:-2],
                     valid[:-2] + ["--socket", str(self.socket), "--", "/bin/true"]]:
            result = subprocess.run([BIN, "spawn", *args], env=dict(self.env, PATH="/no-rex-here"),
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, "")
        before = self.view()
        missing = self.work / "absent.sock"
        command = self.command("/bin/true")
        command[command.index("--socket") + 1] = str(missing)
        result = subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=5)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertFalse(missing.exists())
        packet = json.loads(result.stdout)
        self.assertNotEqual(packet["outcome"], "created_and_attached")
        command[command.index("--socket") + 1] = str(self.socket)
        absent = "session:00000000-0000-0000-0000-000000000000"
        command[command.index("--session") + 1] = absent
        result = subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=5)
        packet = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertEqual(packet["outcome"], "backend_error")
        self.assertEqual(packet["failure_reason"], "rex_backend_nonzero_exit")
        self.assertFalse(packet["creation_attempt_frame_seen"])
        self.assertFalse(packet["retry_safe"])
        self.assertIsNone(packet["created"])
        self.assertEqual(self.view(), before)
        self.assertIn(absent, result.stderr)
        self.assertNotEqual(packet["backend_term"], {"Exited": 0})


if __name__ == "__main__":
    unittest.main()
