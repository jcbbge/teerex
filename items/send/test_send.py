"""Public send CLI tests. Real disposable Rex terminals, never a personal server.

TEEREX_BIN selects the integrated executable; REX_BIN optionally selects a Rex build.
Fault-injected transport tests are explicitly separate from real Rex checks.
"""
import concurrent.futures
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


class SendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise unittest.SkipTest("Rex executable required")
        cls.tmp = tempfile.TemporaryDirectory(prefix="teerex-send-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.endpoint = "unix://" + str(cls.socket)
        cls.base = [cls.rex, "--autostart=false", "--server", cls.endpoint, "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([
            cls.rex, "server", "run", "--listen", cls.endpoint, "--restore=false",
            "--config", "/dev/null", "--state-dir", str(cls.root / "state"),
        ], stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Disposable server did not become ready")
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
    def rex_json(cls, *args):
        return json.loads(subprocess.run(cls.base + list(args), capture_output=True,
                                         text=True, timeout=10, check=True).stdout)

    @classmethod
    def rpc(cls, method, args):
        return cls.rex_json("api", "call", method, json.dumps(args))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        (self.work / "inbox").mkdir()
        # Exact same TMPDIR lock namespace as agent-send; no test lock in /tmp root.
        self.env = dict(os.environ, TMPDIR=str(self.work), AGENT_INBOX_DIR=str(self.work / "inbox"),
                        REX_SERVER="unix:///tmp/never-this-server.sock", REX_BLOCK="block:wrong",
                        REX_SESSION="session:wrong", REX_CLIENT="client:wrong",
                        PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""))

    def fixture(self):
        raw = self.work / ("received-" + str(time.monotonic_ns()))
        # Raw, no echo/canonical line limits. Bracketed paste brackets distinguish each
        # event, independently of the controller's ACK receipt or terminal capture.
        code = ("import os,tty; tty.setraw(0); "
                "os.write(1,b'\\x1b[?2004hREADY'); "
                f"f=open({str(raw)!r},'ab',buffering=0)\n"
                "while True:\n b=os.read(0,65536)\n if not b: break\n f.write(b)\n")
        v = self.rex_json("new", "--json", "--keep-open", "--shell=none", "--", sys.executable, "-c", code)
        target = v["session_id"], v["initial_windows"][0]["block_ids"][0]
        for _ in range(100):
            v = self.rpc("com.superlogical.terminal.format", {
                "session_id": target[0], "block_id": target[1], "args": {"format": "text", "max_bytes": 256}})
            if "READY" in v["content"]:
                return target, raw
            time.sleep(.02)
        self.fail("Raw input fixture not ready")

    def command(self, target, message=b"hello", sender="worker", timeout=10000):
        path = self.work / ("message-" + str(time.monotonic_ns()))
        path.write_bytes(message)
        return [BIN, "send", "--socket", str(self.socket), "--session", target[0], "--block", target[1],
                "--from", sender, "--message-file", str(path), "--timeout-ms", str(timeout)]

    def send(self, target, message=b"hello", sender="worker", timeout=10000):
        r = subprocess.run(self.command(target, message, sender, timeout), env=self.env,
                           capture_output=True, text=True, timeout=timeout / 1000 + 5)
        return r, json.loads(r.stdout) if r.stdout else None

    def lock(self, target):
        return self.work / ("agent-send." + target[1].split(":")[1] + ".lock")

    def received(self, raw, expected):
        for _ in range(100):
            actual = raw.read_bytes()
            if len(actual) >= len(expected):
                self.assertEqual(actual, expected)
                return
            time.sleep(.02)
        self.assertEqual(raw.read_bytes(), expected)

    @staticmethod
    def pasted(message, sender="worker"):
        return b"\x1b[200~FROM " + sender.encode() + b": " + message + b"\x1b[201~\r"

    def test_exact_unicode_multiline_target_and_existing_draft(self):
        target, raw = self.fixture()
        other, untouched = self.fixture()
        self.rpc("com.superlogical.terminal.write", {
            "session_id": target[0], "block_id": target[1], "args": {"data": "EXISTING"}})
        message = 'α "quotes" \\ $(touch NEVER)\nsecond\tline\n'.encode()
        r, packet = self.send(target, message, "source α")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(packet["outcome"], "events_acknowledged")
        self.assertEqual(packet["source"], {k: self.source[k] for k in ("rex_version", "platform", "api_revision")})
        self.assertEqual(packet["target"], {"server": self.endpoint, "session_id": target[0], "block_id": target[1]})
        self.assertEqual(packet["paste"], {"attempted": True, "acknowledged": True})
        self.assertEqual(packet["enter"], {"attempted": True, "acknowledged": True})
        self.assertFalse(packet["server_enforced_atomic_delivery"])
        self.assertFalse(packet["exclusive_input_lease"])
        self.assertEqual(packet["prompt_safety"], "not_assessed")
        self.assertEqual(packet["application_consumption"], "not_assessed")
        self.received(raw, b"EXISTING" + self.pasted(message, "source α"))
        self.assertEqual(untouched.read_bytes(), b"")
        self.assertFalse(self.lock(target).exists())

    def test_stdin_exact_bytes_validation_deadline_and_cancellation_before_dispatch(self):
        target, raw = self.fixture()
        command = self.command(target, timeout=500)
        command[command.index("--message-file") + 1] = "-"
        message = 'α "literal"\nlast\tline\n\n'.encode()
        result = subprocess.run(command, input=message, env=self.env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.received(raw, self.pasted(message))
        for invalid in (b"", b"\xff", b"a\rb", b"a" * 65537):
            result = subprocess.run(command, input=invalid, env=self.env, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
        for sig in (None, signal.SIGINT, signal.SIGTERM):
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
            proc.stdin.write(b"partial, not EOF")
            proc.stdin.flush()
            if sig is not None:
                time.sleep(.05)
                proc.send_signal(sig)
            proc.wait(timeout=3)  # Keep writer open: EOF would hide a broken wait budget.
            packet = json.loads(proc.stdout.read())
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            self.assertEqual(proc.returncode, 124 if sig is None else 128 + sig)
            self.assertFalse(packet["paste"]["attempted"])
            self.assertFalse(packet["backend_invoked"])
            self.assertFalse(packet["cooperative_lock"]["acquired"])
        self.assertEqual(raw.read_bytes(), self.pasted(message))

    def test_encoded_boundary_printable_unicode_lf_and_escaping(self):
        target, raw = self.fixture()
        def rpc_bytes(message):
            params = {"session_id": target[0], "block_id": target[1],
                      "event": {"type": "paste", "payload": {"text": "FROM worker: " + message}}}
            # Independent Go-compatible JSON sizing, including HTML/line-separator escaping.
            encoded = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "block.event", "params": params},
                                 ensure_ascii=False, separators=(",", ":"))
            for char, escaped in [("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                                  ("\u2028", "\\u2028"), ("\u2029", "\\u2029")]:
                encoded = encoded.replace(char, escaped)
            return len(encoded.encode())
        overhead = rpc_bytes("")
        accepted = b""
        for char, cost in [("a", 1), ("α", 2), ("\n", 2), ('"', 2), ("<", 6)]:
            n = (60000 - overhead) // cost
            text = char * n + "x" * ((60000 - overhead) % cost)
            with self.subTest(kind=repr(char), boundary="accepted"):
                r, p = self.send(target, text.encode())
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                self.assertEqual(p["encoded_rpc_bytes"], rpc_bytes(text))
                self.assertEqual(p["encoded_rpc_bytes"], 60000)
                accepted += self.pasted(text.encode())
                self.received(raw, accepted)
            with self.subTest(kind=repr(char), boundary="refused"):
                r, p = self.send(target, (text + "x").encode())
                self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
                self.assertEqual(p["encoded_rpc_bytes"], 60001)
                self.assertEqual(p["failure_reason"], "encoded_paste_exceeds_limit")
                self.assertFalse(p["paste"]["attempted"])
                self.assertFalse(p["enter"]["attempted"])
                self.assertEqual(raw.read_bytes(), accepted)
        for message in [b"a" * 65536, "α".encode() * 32768, b"\n" * 65536]:
            r, p = self.send(target, message)
            self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
            self.assertEqual(p["failure_reason"], "encoded_paste_exceeds_limit")
            self.assertFalse(p["paste"]["attempted"])
        self.assertEqual(raw.read_bytes(), accepted)

    def test_cooperating_senders_and_bridge_lock(self):
        target, raw = self.fixture()
        lock = self.lock(target)
        lock.mkdir()  # Same atomic mkdir used by agent-core agent-send.
        r, p = self.send(target, timeout=120)
        self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
        self.assertFalse(p["cooperative_lock"]["acquired"])
        self.assertFalse(p["backend_invoked"])
        self.assertTrue(lock.exists())
        self.assertEqual(raw.read_bytes(), b"")
        lock.rmdir()
        messages = [((f"msg-{i}: " + "α" * 700 + "\nlast").encode()) for i in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda m: self.send(target, m), messages))
        for r, p in results:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(p["cooperative_lock"]["acquired"])
        for _ in range(100):
            data = raw.read_bytes()
            if len(data) == sum(len(self.pasted(m)) for m in messages):
                break
            time.sleep(.02)
        parts = data.split(b"\x1b[200~")[1:]
        self.assertCountEqual(parts, [self.pasted(m)[6:] for m in messages])
        self.assertFalse(lock.exists())

    def test_lock_is_not_server_enforced_exclusion(self):
        target, raw = self.fixture()
        self.lock(target).mkdir()
        self.rpc("com.superlogical.terminal.write", {
            "session_id": target[0], "block_id": target[1], "args": {"data": "BYPASS"}})
        self.received(raw, b"BYPASS")
        self.lock(target).rmdir()

    def test_inbox_marker_custom_and_home_default(self):
        target, raw = self.fixture()
        marker = self.work / "inbox" / (target[1].split(":")[1] + ".inbox")
        marker.write_text("hive\n")
        r, p = self.send(target)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(p["outcome"], "inbox_refused")
        self.assertFalse(p["backend_invoked"])
        marker.unlink()
        self.env["AGENT_INBOX_DIR"] = ""  # Bash ${AGENT_INBOX_DIR:-...} semantics.
        self.env["HOME"] = str(self.work)
        marker = self.work / ".local/state/agent-inbox" / marker.name
        marker.parent.mkdir(parents=True)
        marker.touch()
        r, p = self.send(target)
        self.assertEqual(p["outcome"], "inbox_refused")
        self.assertEqual(raw.read_bytes(), b"")

    def test_cancel_lock_wait_leaves_other_lock(self):
        target, raw = self.fixture()
        lock = self.lock(target)
        for sig in [signal.SIGINT, signal.SIGTERM]:
            lock.mkdir()
            proc = subprocess.Popen(self.command(target), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(.1)
            proc.send_signal(sig)
            out, err = proc.communicate(timeout=3)
            self.assertEqual(proc.returncode, 128 + sig, out + err)
            p = json.loads(out)
            self.assertEqual(p["outcome"], "cancel_requested")
            self.assertFalse(p["backend_invoked"])
            self.assertTrue(lock.exists())
            lock.rmdir()
        self.assertEqual(raw.read_bytes(), b"")

    def test_invalid_input_and_nonregular_file_fail_before_lock(self):
        target, raw = self.fixture()
        for message in [b"", b"\xff", b"\x00", b"\x1b[201~", b"a\rb", b"\x7f", b"a" * 65537]:
            r, p = self.send(target, message)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIsNone(p)
        command = self.command(target)
        path = Path(command[command.index("--message-file") + 1])
        path.unlink()
        os.mkfifo(path)
        r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=3)
        self.assertEqual(r.returncode, 2, r.stderr)
        for flag, value in [("--socket", "relative"), ("--session", "label"), ("--block", "block:123"),
                            ("--block", target[1].upper()), ("--from", "bad\nlabel"), ("--timeout-ms", "99")]:
            command = self.command(target)
            command[command.index(flag) + 1] = value
            r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=3)
            self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(raw.read_bytes(), b"")
        self.assertFalse(self.lock(target).exists())

    def test_mismatched_target_and_missing_server_fail_closed(self):
        target, raw = self.fixture()
        other, untouched = self.fixture()
        r, p = self.send((target[0], other[1]))
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(p["paste"]["acknowledged"])
        command = self.command(target)
        command[command.index("--socket") + 1] = str(self.work / "absent.sock")
        r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(json.loads(r.stdout)["enter"]["acknowledged"])
        self.assertEqual(raw.read_bytes(), b"")
        self.assertEqual(untouched.read_bytes(), b"")
        self.assertFalse(self.lock(target).exists())

    def test_fault_injected_partial_ack_deadline_and_malformed_transport(self):
        target, raw = self.fixture()
        fake = self.work / "fake"
        fake.mkdir()
        self.env["PATH"] = str(fake)
        prefix = (f"#!{sys.executable}\nimport json,time\n"
                  "def emit(v): print(json.dumps(v),flush=True)\n"
                  "emit({'event':'source','source':{'rex_version':'injected','platform':'test','api_revision':13}})\n"
                  "time.sleep(.03)\n"
                  "emit({'event':'attempt','stage':'paste'})\n"
                  "emit({'event':'ack','stage':'paste'})\n"
                  "emit({'event':'attempt','stage':'enter'})\n")
        for tail, expected, code in [
            ("emit({'event':'failed','reason':'enter_call_failed'})\n", "uncertain", 1),
            ("time.sleep(30)\n", "deadline_exceeded", 124),
            ("print('invalid',flush=True)\ntime.sleep(30)\n", "uncertain", 1),
        ]:
            script = fake / "rex"
            script.write_text(prefix + tail)
            script.chmod(0o755)
            r, p = self.send(target, timeout=250)
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
            self.assertEqual(p["outcome"], expected)
            self.assertEqual(p["source"], {"rex_version": "injected", "platform": "test", "api_revision": 13})
            self.assertEqual(p["paste"], {"attempted": True, "acknowledged": True})
            self.assertEqual(p["enter"], {"attempted": True, "acknowledged": False})
            self.assertFalse(self.lock(target).exists())
        self.assertEqual(raw.read_bytes(), b"")  # Fault backend never touched actual Rex.


if __name__ == "__main__":
    unittest.main(verbosity=2)
