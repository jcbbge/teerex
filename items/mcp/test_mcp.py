"""Stdio MCP contracts; only disposable HOME and explicit disposable Rex."""
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("TEEREX_BIN", HERE.parents[1] / "zig-out/bin/teerex")).resolve()
spec = importlib.util.spec_from_file_location("teerex_mcp", HERE / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class Client:
    def __init__(self, env):
        self.process = subprocess.Popen([str(BIN), "mcp"], env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.buffer = bytearray()
        self.identity = 0

    def write(self, value):
        self.process.stdin.write(json.dumps(value).encode() + b"\n")
        self.process.stdin.flush()

    def read(self, timeout=15):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise AssertionError("MCP response timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise AssertionError("MCP process closed output unexpectedly")
            self.buffer.extend(chunk)
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        result = json.loads(line)
        assert result["jsonrpc"] == "2.0", result
        return result

    def request(self, method, params=None):
        self.identity += 1
        self.write(dict(jsonrpc="2.0", id=self.identity, method=method, params=params or {}))
        result = self.read()
        assert result["id"] == self.identity, result
        return result

    def initialize(self):
        result = self.request("initialize", dict(protocolVersion=server.PROTOCOL, capabilities={}, clientInfo=dict(name="test", version="1")))
        self.write(dict(jsonrpc="2.0", method="notifications/initialized"))
        return result

    def call(self, name, arguments):
        return self.request("tools/call", dict(name=name, arguments=arguments))

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdout.close()
        if not self.process.stderr.closed:
            self.diagnostics = self.process.stderr.read().decode("utf-8", errors="replace")
        self.process.stderr.close()


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="teerex-mcp-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.env = dict(os.environ, HOME=str(self.home), REX_SERVER="", REX_SESSION="",
                        TEEREX_CLUTCH_DIR=str(self.home / "clutch"), TEEREX_CALL_LOG_DIR=str(self.home / "calls"))
        self.client = Client(self.env)
        self.addCleanup(self.client.close)

    def test_handshake_list_schemas_and_mutation_annotations(self):
        self.assertEqual(self.client.request("tools/list")["error"]["code"], -32002)
        self.assertEqual(self.client.request("initialize", dict(protocolVersion=server.PROTOCOL, capabilities={}, clientInfo={}))["error"]["code"], -32602)
        result = self.client.initialize()["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertEqual(result["capabilities"], dict(tools=dict(listChanged=False)))
        tools = self.client.request("tools/list")["result"]["tools"]
        names = [t["name"] for t in tools]
        self.assertEqual(names, sorted(server.TOOLS))
        self.assertTrue({"observe", "watch", "compare", "send", "surfaces_open", "surfaces_ensure", "surfaces_resolve",
                         "surfaces_close", "surfaces_focus", "surfaces_rename", "run_visible", "jobs_list", "jobs_doctor",
                         "jobs_present", "agents_launch", "boards_calls", "doctor", "cartridges_list"} <= set(names))
        for tool in tools:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(set(tool["inputSchema"]["required"]) <= set(tool["inputSchema"]["properties"]))
            if not tool["annotations"]["readOnlyHint"]:
                self.assertTrue(tool["annotations"]["destructiveHint"])
                self.assertTrue(tool["annotations"]["openWorldHint"])
        self.assertEqual(self.client.request("ping")["result"], {})
        self.assertEqual(self.client.request("initialize")["error"]["code"], -32602)

    def test_bad_arguments_unknown_tools_and_notifications_do_not_dispatch(self):
        self.client.initialize()
        for name, arguments in (("raw_rex", {}), ("observe", {}), ("observe", dict(block="block:short")),
                                ("cartridges_list", dict(argv=["sh", "-c", "bad"])),
                                ("doctor", dict(socket="relative")), ("doctor", dict(socket="/tmp/socket", timeout_ms=True)),
                                ("doctor", dict(socket="/tmp/socket", timeout_ms=60001)),
                                ("jobs_list", dict(registry="/tmp/r", command="--help")),
                                ("surfaces_rename", dict(socket="/s", session="test", label="x")),
                                ("surfaces_open", dict(socket="/s", session="x", layout="tab", label="x", argv=["/bin/sh", "-c", "bad"]))):
            with self.subTest(name=name, arguments=arguments):
                result = self.client.call(name, arguments)
                self.assertEqual(result["error"]["code"], -32602)
        self.client.write(dict(jsonrpc="2.0", method="tools/call", params=dict(name="cartridges_list", arguments={})))
        self.assertEqual(self.client.request("ping")["result"], {})
        self.assertFalse((self.home / ".local/opt/teerex-cartridges").exists())
        self.assertEqual(self.client.request("unknown")["error"]["code"], -32601)
        self.assertEqual(self.client.request("tools/list", dict(cursor="unrecognized"))["error"]["code"], -32602)

    def test_malformed_duplicate_and_oversize_frames_are_bounded(self):
        for raw, code in ((b'{"jsonrpc":"2.0","id":1,"id":2}\n', -32700),
                          (b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]\n', -32600),
                          (b'{"jsonrpc":"2.0","id":true,"method":"ping"}\n', -32600),
                          (b'{"x":NaN}\n', -32700)):
            self.client.process.stdin.write(raw)
            self.client.process.stdin.flush()
            self.assertEqual(self.client.read()["error"]["code"], code)
        self.client.process.stdin.write(b"x" * (server.MAX_MESSAGE + 1) + b"\n")
        self.client.process.stdin.flush()
        self.assertEqual(self.client.read()["error"]["code"], -32600)
        self.assertEqual(self.client.process.wait(timeout=5), 0)

    def test_cartridges_receipt_is_unmodified_and_repeated_calls_are_not_spuriously_busy(self):
        self.client.initialize()
        direct = subprocess.run([str(BIN), "cartridges", "list"], env=self.env, capture_output=True, text=True, timeout=10)
        for _ in range(10):
            result = self.client.call("cartridges_list", {})["result"]
            native = result["structuredContent"]
            self.assertFalse(result["isError"])
            self.assertEqual((native["exit_code"], native["stdout"], native["stderr"]), (direct.returncode, direct.stdout, direct.stderr))
            self.assertEqual(native["receipt"], json.loads(direct.stdout))
            self.assertEqual(json.loads(result["content"][0]["text"]), native)

    def test_print_config_no_config_writes_and_no_environment_values(self):
        marker = "do-not-disclose-config-environment"
        env = dict(self.env, SECRET_KEY=marker, REX_SERVER="unix:///" + marker)
        for client in ("claude", "codex", "pi"):
            result = subprocess.run([str(BIN), "mcp", "--print-config", client], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(marker, result.stdout + result.stderr)
            if client == "codex":
                self.assertIn("[mcp_servers.teerex]", result.stdout)
                self.assertIn('args = ["mcp"]', result.stdout)
            else:
                self.assertEqual(json.loads(result.stdout)["mcpServers"]["teerex"], dict(command=str(BIN), args=["mcp"]))
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".claude.json").exists())
        self.assertFalse((self.home / ".pi").exists())

    def test_embedded_source_ignores_cwd_and_pythonpath_modules(self):
        self.client.close()
        (self.home / "json.py").write_text('raise RuntimeError("planted cwd module executed")')
        result = subprocess.run([str(BIN), "mcp", "--print-config", "pi"], cwd=self.home,
                                env=dict(self.env, PYTHONPATH=str(self.home)), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["mcpServers"]["teerex"]["command"], str(BIN))

    def test_nonreading_stdio_client_cannot_stall_shutdown(self):
        self.client.initialize()
        # Several large discovery replies fill even larger platform pipe buffers.
        for identity in range(20, 40):
            self.client.write(dict(jsonrpc="2.0", id=identity, method="tools/list"))
        self.assertEqual(self.client.process.wait(timeout=8), 0)

    def test_flag_schemas_build_exact_literal_argv_and_defaults(self):
        session = "session:12345678-1234-1234-1234-123456789abc"
        block = "block:12345678-1234-1234-1234-123456789abc"
        env = dict(REX_SERVER="unix:///tmp/selected", REX_SESSION=session)
        command, body = server.command_for("observe", dict(block=block, max_bytes=256), env)
        self.assertEqual(command, ["observe", "--block", block, "--max-bytes", "256", "--socket", "/tmp/selected", "--session", session])
        self.assertIsNone(body)
        command, body = server.command_for("send", dict(block=block, sender="agent", message="literal ; $(false)\nα"), env)
        self.assertEqual(body, "literal ; $(false)\nα".encode())
        self.assertEqual(command[:5], ["send", "--block", block, "--from", "agent"])
        self.assertIn("--message-file", command)
        self.assertNotIn("literal ; $(false)", command)
        self.assertEqual(server.command_for("cartridges_list", dict(root="/home/me/code"), {})[0], ["cartridges", "--root", "/home/me/code", "list"])
        self.assertEqual(server.command_for("boards_calls", {}, {})[0], ["boards", "calls", "--once", "--json"])
        literal = "$(touch /should-not-run); --socket literal"
        command, _ = server.command_for("surfaces_open", dict(layout="tab", label="test", argv=["/bin/echo", literal, "--socket"]), env)
        self.assertEqual(command[-4:], ["--", "/bin/echo", literal, "--socket"])
        with self.assertRaises(server.InvalidArguments):
            server.command_for("observe", dict(block=block), dict(REX_SERVER="tcp://untrusted", REX_SESSION=session))
        with self.assertRaises(server.InvalidArguments):
            server.command_for("watch", dict(block=block, baseline="/b", timeout_ms=100, status_state=["done", "done"]), env)
        with self.assertRaises(server.InvalidArguments):
            server.command_for("doctor", dict(socket="/s", baseline="--help"), {})

    def test_schema_flags_exist_in_the_native_command_help(self):
        for name, entry in server.TOOLS.items():
            command = entry["command"]
            if command[0] in ("jobs", "surfaces", "cartridges"):
                command = command[:1]
            result = subprocess.run([str(BIN), *command, "--help"], env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for key in entry["public"]["inputSchema"]["properties"]:
                if key == "argv":
                    continue
                flag = "--" + {"sender": "from", "message": "message-file"}.get(key, key.replace("_", "-"))
                with self.subTest(tool=name, flag=flag):
                    self.assertIn(flag, result.stdout)
            for flag in entry["fixed"]:
                self.assertIn(flag, result.stdout)

    def test_supervision_preserves_nonzero_exit_and_bounds_output_deadline_and_cancellation(self):
        cancelled = threading.Event()
        for snippet, expected in (("import sys;print('{}');sys.stderr.write('original error');sys.exit(7)", 7),
                                  ("import os,signal;os.kill(os.getpid(),signal.SIGTERM)", -signal.SIGTERM)):
            result = server.execute([sys.executable, "-I", "-c", snippet], None, cancelled)
            self.assertEqual(result["exit_code"], expected)
            self.assertIsNone(result["transport_error"])
        result = server.execute([sys.executable, "-I", "-c", "import time;time.sleep(30)"], None, cancelled, timeout=.1)
        self.assertEqual(result["transport_error"], "deadline_exceeded")
        cancelled.set()
        result = server.execute([sys.executable, "-I", "-c", "import time;time.sleep(30)"], None, cancelled)
        self.assertEqual(result["transport_error"], "cancelled")
        result = server.execute([sys.executable, "-I", "-c", "import os;os.write(1,b'x'*3000000)"], None, threading.Event())
        self.assertEqual(result["transport_error"], "output_limit_exceeded")
        self.assertLessEqual(len(result["stdout"]), server.MAX_OUTPUT)


class RexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise RuntimeError("Select explicit disposable-test REX_BIN")
        temporary = tempfile.TemporaryDirectory(prefix="tmcp-", dir="/tmp")
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        cls.socket = cls.root / "rex.sock"
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                       "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")], stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 5
        while not cls.socket.exists():
            if cls.server.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError((cls.root / "server.log").read_text())
            time.sleep(.05)
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def setUp(self):
        home = self.root / str(time.monotonic_ns())
        home.mkdir(mode=0o700)
        made = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--", "/bin/sleep", "120"], timeout=10))
        self.session = made["session_id"]
        self.block = made["initial_windows"][0]["block_ids"][0]
        self.env = dict(os.environ, HOME=str(home), REX_SERVER="unix://" + str(self.socket), REX_SESSION=self.session,
                        PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""),
                        TEEREX_INTERNAL_REX=self.rex, TEEREX_CALL_LOG_DIR=str(home / "calls"), TEEREX_CLUTCH_DIR=str(home / "clutch"), XDG_STATE_HOME=str(home / "state"))
        self.client = Client(self.env)
        self.addCleanup(self.client.close)
        self.client.initialize()

    def call(self, tool, args):
        result = self.client.call(tool, args)
        self.assertNotIn("error", result, result)
        native = result["result"]["structuredContent"]
        self.assertEqual(native["exit_code"], 0, native)
        self.assertFalse(result["result"]["isError"])
        return native["receipt"]

    def test_observe_surface_open_resolve_close_round_trip_without_shell_interpolation(self):
        observed = self.call("observe", dict(block=self.block, max_bytes=256))
        self.assertEqual(observed["target"]["block_id"], self.block)
        marker = Path(self.env["HOME"]) / "MUST_NOT_EXIST"
        literal = "$(touch " + str(marker) + "); literal α"
        opened = self.call("surfaces_open", dict(layout="tab", label=literal, argv=["/bin/echo", literal]))
        block = opened["actual"]["block_id"]
        self.assertEqual(opened["actual"]["label"], literal)
        deadline = time.monotonic() + 5
        while True:
            packet = self.call("observe", dict(block=block, max_bytes=4096))
            if literal in packet["capture"]["content"]:
                break
            self.assertLess(time.monotonic(), deadline, "literal argv output never arrived")
            time.sleep(.05)
        resolved = self.call("surfaces_resolve", dict(pane=literal))
        self.assertEqual(resolved["resolved"]["block_id"], block)
        self.call("surfaces_rename", dict(pane=block, label="renamed literal ; $(false)"))
        self.call("surfaces_close", dict(pane=block))
        self.assertFalse(marker.exists())
        error = self.client.call("observe", dict(block=block))["result"]
        self.assertTrue(error["isError"])
        self.assertNotEqual(error["structuredContent"]["exit_code"], 0)

    def test_bounded_watch_cancellation_and_busy_refusal_do_not_queue(self):
        observed = self.call("observe", dict(block=self.block, max_bytes=256))
        baseline = Path(self.env["HOME"]) / "baseline.json"
        baseline.write_text(json.dumps(observed))
        self.client.identity += 1
        watch_id = self.client.identity
        self.client.write(dict(jsonrpc="2.0", id=watch_id, method="tools/call", params=dict(name="watch",
                          arguments=dict(block=self.block, baseline=str(baseline), timeout_ms=60000, status_state=["done"]))))
        busy = self.client.call("cartridges_list", {})
        self.assertEqual(busy["error"]["code"], -32000)
        self.client.write(dict(jsonrpc="2.0", method="notifications/cancelled", params=dict(requestId=watch_id)))
        result = self.client.read()
        self.assertEqual(result["id"], watch_id)
        self.assertTrue(result["result"]["isError"])
        self.assertEqual(result["result"]["structuredContent"]["transport_error"], "cancelled")
        self.assertEqual(self.client.request("ping")["result"], {})

    def test_eof_and_sigterm_cancel_inflight_watch_and_exit(self):
        observed = self.call("observe", dict(block=self.block, max_bytes=256))
        baseline = Path(self.env["HOME"]) / "baseline.json"
        baseline.write_text(json.dumps(observed))
        for eof in (True, False):
            with self.subTest(eof=eof):
                client = Client(self.env)
                self.addCleanup(client.close)
                client.initialize()
                client.identity += 1
                client.write(dict(jsonrpc="2.0", id=client.identity, method="tools/call", params=dict(name="watch",
                             arguments=dict(block=self.block, baseline=str(baseline), timeout_ms=60000, status_state=["done"]))))
                # The busy response proves the first call is active before stop.
                self.assertEqual(client.call("cartridges_list", {})["error"]["code"], -32000)
                if eof:
                    client.process.stdin.close()
                else:
                    client.process.send_signal(signal.SIGTERM)
                self.assertEqual(client.process.wait(timeout=10), 0)

    def test_send_body_is_literal_and_not_logged(self):
        # A disposable cat terminal accepts a complete message; no shell is running.
        opened = self.call("surfaces_open", dict(layout="tab", label="cat input fixture", argv=["/bin/cat"]))
        block = opened["actual"]["block_id"]
        secret_marker = "synthetic-private-message-$(false)"
        self.call("send", dict(block=block, sender="mcp-test", message=secret_marker, draft="ignore"))
        observed = self.call("observe", dict(block=block, max_bytes=4096))
        self.assertIn(secret_marker, observed["capture"]["content"])
        self.call("surfaces_close", dict(pane=block))
        self.client.close()
        self.assertNotIn(secret_marker, self.client.diagnostics)
        # Native call metadata and MCP diagnostics must never include the body.
        for path in Path(self.env["HOME"]).rglob("*.jsonl"):
            self.assertNotIn(secret_marker, path.read_text())


if __name__ == "__main__":
    unittest.main()
