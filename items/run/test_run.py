"""Public run contract on disposable macOS/Linux Rex; never use a default/personal server."""

import base64
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


BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex"))


def content(node):
    return node["content"].encode("utf-8") if node["encoding"] == "utf8" else base64.b64decode(node["content"], validate=True)


class RunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform not in ("darwin", "linux"):
            raise RuntimeError("Execution/lifetime validation requires macOS or Linux")
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex or not BIN.is_file():
            raise RuntimeError("Build teerex and put the test Rex binary on PATH first")
        tmp = tempfile.TemporaryDirectory(prefix="trun-", dir="/tmp")
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "2s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen(
            [cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket), "--restore=false",
             "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
            stdout=cls.log, stderr=cls.log,
        )
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                return
            time.sleep(.05)
        raise RuntimeError("Disposable Rex did not start")

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def command(self, argv, *, timeout=10000, limit=4096, socket=None, cwd=None):
        return [str(BIN), "run", "--socket", str(socket or self.socket), "--cwd", str(cwd or self.root),
                "--timeout-ms", str(timeout), "--max-bytes", str(limit), "--", *argv]

    def invoke(self, argv, *, env=None, **kwargs):
        result = subprocess.run(self.command(argv, **kwargs), capture_output=True, text=True, env=env, timeout=15)
        self.assertTrue(result.stdout, result.stderr)
        return result, json.loads(result.stdout)

    def assert_stopped(self, pids):
        for _ in range(100):
            live = []
            for pid in pids:
                status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
                if status and not status.startswith("Z"):
                    live.append(pid)
            if not live:
                return
            time.sleep(.02)
        self.fail(f"Owned fixture processes still live: {live}")

    def fixture(self, mode):
        path = self.root / (self.id().split(".")[-1] + "-" + mode + ".pids")
        self.addCleanup(self.clean_fixture, path)
        grand = (
            "import pathlib,signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "pathlib.Path(sys.argv[1]+'.ready').write_text('ready');time.sleep(30)"
        )
        child_options = "" if mode == "inherited_pipes" else "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL"
        if mode == "detached":
            child_options += ",start_new_session=True"
        script = (
            "import os,pathlib,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            f"c=subprocess.Popen([sys.executable,'-c',{grand!r},sys.argv[1]],{child_options});"
            "\nwhile not pathlib.Path(sys.argv[1]+'.ready').exists():time.sleep(.01)\n"
            "os.write(1,b'BEFORE_STOP\\n');time.sleep(.1);"
            "pathlib.Path(sys.argv[1]).write_text(f'{os.getpid()} {c.pid} {os.getpgrp()}');"
        )
        if mode in ["exit", "inherited_pipes", "detached"]:
            script += "sys.exit(0)"
        elif mode == "backend_exit":
            script += "time.sleep(.1);os.kill(os.getppid(),signal.SIGKILL);time.sleep(30)"
        else:
            script += "time.sleep(30)"
        return path, [sys.executable, "-c", script, str(path)]

    @staticmethod
    def clean_fixture(path):
        if path.exists():
            for token in path.read_text().split()[:2]:
                pid = int(token)
                args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True).stdout
                if str(path) in args:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_literal_argv_cwd_eof_environment_and_no_terminal_mutation(self):
        before = subprocess.run(self.base + ["session", "ls", "--json"], capture_output=True, text=True, check=True).stdout
        arguments = ["literal ; $(touch SHOULD_NOT_EXIST)", "space value", "a\nb", '\"; error("INJECT") --', "α😀"]
        script = "import json,os,sys;print(json.dumps([os.getcwd(),sys.argv[1:],sys.stdin.read(),os.getenv('TEEREX_TEST'),os.getenv('REX_BLOCK')]))"
        env = dict(os.environ, TEEREX_TEST="inherited", REX_SERVER="unix:///tmp/wrong.sock",
                   REX_SESSION="session:poison", REX_BLOCK="block:poison", REX_CLIENT="client:poison")
        result, packet = self.invoke([sys.executable, "-c", script, *arguments], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(content(packet["stdout"])), [str(self.root.resolve()), arguments, "", "inherited", None])
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        self.assertEqual(packet["execution_location"], "cli_local")
        self.assertEqual(packet["server"], "unix://" + str(self.socket))
        version = json.loads(subprocess.check_output(self.base + ["api", "call", "server.version"], text=True))
        self.assertEqual(packet["source"]["api_revision"], version["api_revision"])
        self.assertEqual(len(bytes.fromhex(packet["execution_id"])), 16)
        self.assertNotIn("argv", packet)
        after = subprocess.run(self.base + ["session", "ls", "--json"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(before), json.loads(after))

    def test_actual_zero_nonzero_and_signalled_exits(self):
        for code in [0, 7]:
            with self.subTest(code=code):
                result, packet = self.invoke([sys.executable, "-c", f"print('output');import sys;sys.exit({code})"])
                self.assertEqual(result.returncode, 0 if code == 0 else 1)
                self.assertEqual(packet["exit_report"], {"code": code, "signal": None, "timed_out": False, "ok": code == 0})
                self.assertEqual(packet["outcome"], "exit_reported")
                self.assertEqual(packet["success"], code == 0)
                self.assertEqual(packet["task_completion"], "not_assessed")
                self.assertEqual(content(packet["stdout"]), b"output\n")
                self.assertTrue(packet["stdout"]["complete"])
        result, packet = self.invoke([sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(packet["exit_report"]["code"], -1)
        self.assertIsNotNone(packet["exit_report"]["signal"])
        self.assertFalse(packet["success"])
        # Silence and the Rex connection's three-second timeout are not command exit.
        result, packet = self.invoke([sys.executable, "-c", "import time;time.sleep(3.2);print('late output')"], timeout=5000)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(packet["elapsed_ms"], 3200)
        self.assertEqual(content(packet["stdout"]), b"late output\n")

    def test_split_utf8_lines_binary_and_final_drain(self):
        script = "import os,time;os.write(1,b'first\\n\\xf0\\x9f');time.sleep(.05);os.write(1,b'\\x98\\x80last\\n\\x00');os.write(2,b'\\xff\\x80bad')"
        result, packet = self.invoke([sys.executable, "-c", script])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packet["stdout"]["encoding"], "utf8")
        self.assertEqual(content(packet["stdout"]), "first\n😀last\n\0".encode())
        self.assertEqual(packet["stderr"]["encoding"], "base64")
        self.assertEqual(content(packet["stderr"]), b"\xff\x80bad")
        for node in [packet["stdout"], packet["stderr"]]:
            self.assertEqual(node["retained_bytes"], node["bytes_seen"])
            self.assertTrue(node["complete"])

    def test_shared_byte_budget_boundary_and_large_output(self):
        for limit in [1, 4, 65536]:
            with self.subTest(limit=limit):
                payload = b"abc\xf0\x9f\x98\x80" if limit == 4 else b"x" * (limit + 1)
                result, packet = self.invoke([sys.executable, "-c", f"import os;os.write(1,{payload!r})"], limit=limit)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(content(packet["stdout"]), payload[:limit])
                self.assertEqual(packet["stdout"]["bytes_seen"], len(payload))
                self.assertFalse(packet["stdout"]["complete"])
                self.assertTrue(packet["stderr"]["complete"])
        result, packet = self.invoke([sys.executable, "-c", "import os;os.write(1,b'A'*3000000);os.write(2,b'B'*2000000)"], limit=257)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packet["stdout"]["bytes_seen"], 3000000)
        self.assertEqual(packet["stderr"]["bytes_seen"], 2000000)
        self.assertEqual(sum(packet[s]["retained_bytes"] for s in ["stdout", "stderr"]), 257)
        for stream, byte in [("stdout", b"A"), ("stderr", b"B")]:
            self.assertEqual(content(packet[stream]), byte * packet[stream]["retained_bytes"])

    def test_timeout_kills_term_resistant_parent_and_same_group_child(self):
        path, argv = self.fixture("timeout")
        result, packet = self.invoke(argv, timeout=500)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertEqual(packet["outcome"], "command_timed_out")
        self.assertTrue(packet["exit_report"]["timed_out"])
        self.assertFalse(packet["success"])
        self.assertIn(b"BEFORE_STOP", content(packet["stdout"]))
        pids = [int(n) for n in path.read_text().split()]
        self.assertNotEqual(pids[2], os.getpgrp())
        self.assert_stopped(pids[:2])

    def test_cancellation_retains_partial_output_and_owned_cleanup(self):
        for sig in [signal.SIGINT, signal.SIGTERM]:
            with self.subTest(signal=sig):
                path, argv = self.fixture("cancel" + str(sig))
                proc = subprocess.Popen(self.command(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    for _ in range(150):
                        if path.exists() or proc.poll() is not None:
                            break
                        time.sleep(.02)
                    self.assertTrue(path.exists(), "fixture did not start")
                    time.sleep(.05)
                    start = time.monotonic()
                    proc.send_signal(sig)
                    out, err = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, 128 + sig, err)
                    self.assertLess(time.monotonic() - start, 2)
                    packet = json.loads(out)
                    self.assertEqual(packet["outcome"], "cancel_requested")
                    self.assertEqual(packet["cancellation_signal"], sig)
                    self.assertFalse(packet["success"])
                    self.assertIn(b"BEFORE_STOP", content(packet["stdout"]))
                    self.assertIsNone(packet["exit_report"])
                    self.assertIsNone(packet["stdout"]["bytes_seen"])
                    self.assertFalse(packet["stdout"]["complete"])
                    self.assertFalse(packet["cleanup"]["all_descendants_verified_gone"])
                    self.assert_stopped([int(n) for n in path.read_text().split()[:2]])
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate(timeout=5)

    def test_normal_and_abnormal_backend_exit_clean_remaining_group(self):
        for mode in ["exit", "backend_exit", "inherited_pipes", "detached"]:
            with self.subTest(mode=mode):
                path, argv = self.fixture(mode)
                result, packet = self.invoke(argv)
                self.assertEqual(result.returncode, 1 if mode == "backend_exit" else 0, result.stderr)
                self.assertEqual(packet["outcome"], "backend_error" if mode == "backend_exit" else "exit_reported")
                if mode == "backend_exit":
                    self.assertIsNone(packet["exit_report"])
                    self.assertFalse(packet["stdout"]["complete"])
                pids = [int(n) for n in path.read_text().split()[:2]]
                if mode == "detached":
                    # Demonstrate the documented boundary, then clean this known fixture ourselves.
                    status = subprocess.run(["ps", "-o", "pgid=,stat=", "-p", str(pids[1])], capture_output=True, text=True).stdout.split()
                    self.assertEqual(int(status[0]), pids[1])
                    self.assertFalse(status[1].startswith("Z"))
                    self.assertEqual(packet["cleanup"]["detached_descendants"], "not_covered")
                    self.assertFalse(packet["cleanup"]["all_descendants_verified_gone"])
                    self.clean_fixture(path)
                self.assert_stopped(pids)

    def test_outer_deadline_is_not_pipe_eof_and_does_not_invent_exit(self):
        folder = self.root / "fake-bin"
        folder.mkdir()
        fake = folder / "rex"
        fake.write_text(f"#!{sys.executable}\nimport os,time\nos.close(1)\nos.close(2)\ntime.sleep(30)\n")
        fake.chmod(0o700)
        result, packet = self.invoke(["/usr/bin/true"], timeout=100, env=dict(os.environ, PATH=str(folder)))
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertEqual(packet["outcome"], "outer_deadline_exceeded")
        self.assertIsNone(packet["source"])
        self.assertIsNone(packet["program_pid_reported"])
        self.assertIsNone(packet["exit_report"])
        self.assertFalse(packet["success"])
        self.assertGreaterEqual(packet["elapsed_ms"], 5100)
        self.assertLess(packet["elapsed_ms"], 7500)

    def test_missing_server_cwd_and_executable_fail_without_terminal_fallback(self):
        marker = self.root / "MUST_NOT_EXECUTE"
        argv = [sys.executable, "-c", f"from pathlib import Path;Path({str(marker)!r}).touch()"]
        result, packet = self.invoke(argv, socket=self.root / "absent.sock")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(packet["outcome"], "backend_error")
        self.assertIsNone(packet["source"])
        self.assertFalse((self.root / "absent.sock").exists())
        self.assertFalse(marker.exists())
        result, packet = self.invoke(argv, cwd=self.root / "absent-dir")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIsNotNone(packet["source"])
        self.assertIsNone(packet["program_pid_reported"])
        self.assertFalse(marker.exists())
        result, packet = self.invoke([str(self.root / "absent-program")])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIsNone(packet["exit_report"])
        result = subprocess.run(self.command(argv), env=dict(os.environ, PATH="/no-rex-executable"),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FileNotFound", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(marker.exists())

    def test_fast_exits_do_not_signal_an_unrelated_process(self):
        sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        try:
            for _ in range(20):
                result, packet = self.invoke(["/usr/bin/true"])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(packet["exit_report"]["code"], 0)
                self.assertIsNone(sentinel.poll())
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=5)

    def test_usage_rejects_ambiguous_or_unbounded_requests(self):
        good = ["--socket", str(self.socket), "--cwd", str(self.root)]
        for args in [[], good, good + ["--"], good + ["--", ""],
                     good + ["--timeout-ms", "99", "--", "/usr/bin/true"],
                     good + ["--timeout-ms", "60001", "--", "/usr/bin/true"],
                     good + ["--max-bytes", "0", "--", "/usr/bin/true"],
                     good + ["--max-bytes", "65537", "--", "/usr/bin/true"],
                     good + ["--cwd", str(self.root), "--", "/usr/bin/true"],
                     ["--socket", "relative", "--cwd", "/tmp", "--", "/usr/bin/true"],
                     ["--socket", str(self.socket), "--cwd", "relative", "--", "/usr/bin/true"],
                     good + ["--unknown", "value", "--", "/usr/bin/true"]]:
            with self.subTest(args=args):
                result = subprocess.run([str(BIN), "run", *args], capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
