"""Bounded, explicit private-server fixtures and waited-exec measurements."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = ["rex_server", "gui", "neighbour_panes", "whole_machine_energy"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, mode=0o600):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as output:
        os.chmod(temporary, mode)
        output.write(value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())
    temporary.replace(path)


def execute(argv, env=None, timeout=30, cancel=None):
    """wait4 gives this waited child's high-water RSS, not a cumulative RSS delta."""
    start = time.monotonic_ns()
    process = subprocess.Popen(list(map(str, argv)), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    streams = [bytearray(), bytearray()]
    stop_sent = False
    killed = False
    with selectors.DefaultSelector() as selector:
        for index, pipe in enumerate((process.stdout, process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, index)
        try:
            while True:
                elapsed = (time.monotonic_ns() - start) / 1e9
                if cancel and not stop_sent and elapsed >= cancel[0]:
                    process.send_signal(cancel[1])
                    stop_sent = True
                if elapsed >= timeout and not killed:
                    process.kill()
                    killed = True
                for key, _ in selector.select(.02):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if chunk:
                        streams[key.data].extend(chunk)
                        if len(streams[key.data]) > 8 * 1024 * 1024:
                            raise ValueError("acceptance_output_limit")
                    else:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                if not selector.get_map():
                    pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                    if pid:
                        process.returncode = os.waitstatus_to_exitcode(status)
                        break
                if elapsed > timeout + 5:
                    raise TimeoutError("acceptance_exec_deadline")
        finally:
            if process.returncode is None:
                process.kill()
                process.wait()
            for pipe in (process.stdout, process.stderr):
                pipe.close()
    metrics = dict(calls=1, rex_client_launches=0, wall_ms=(time.monotonic_ns() - start) / 1e6,
        stdout_bytes=len(streams[0]), stderr_bytes=len(streams[1]),
        cpu_ms=(usage.ru_utime + usage.ru_stime) * 1000,
        maxrss_kib=usage.ru_maxrss / (1024 if sys.platform == "darwin" else 1))
    return subprocess.CompletedProcess(argv, process.returncode, bytes(streams[0]), bytes(streams[1])), metrics


class Server:
    def __init__(self, rex, root):
        self.rex = str(Path(rex).resolve())
        self.root = Path(root).resolve()
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.socket = self.root / "rex.sock"
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", os.defpath), PYTHONDONTWRITEBYTECODE="1")
        for key in ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT", "TEEREX_INTERNAL_REX", "TEEREX_REX", "TEEREX_BIN"):
            self.env.pop(key, None)
        self.base = [self.rex, "--autostart=false", "--server", "unix://" + str(self.socket), "--timeout", "3s"]
        self.log = (self.root / "server.log").open("wb")
        os.chmod(self.root / "server.log", 0o600)
        self.process = subprocess.Popen([self.rex, "server", "run", "--listen", "unix://" + str(self.socket), "--restore=false", "--config", "/dev/null", "--state-dir", str(self.root / "state")], env=self.env, stdout=self.log, stderr=self.log)
        try:
            end = time.monotonic() + 5
            while not self.socket.exists():
                if self.process.poll() is not None or time.monotonic() >= end:
                    raise RuntimeError("private_server_start_failed")
                time.sleep(.02)
            self.version = self.rpc("server.version")
            self.identity = self.rpc("server.status")
        except BaseException:
            self.close()
            raise

    def command(self, *args, **kwargs):
        return execute([*self.base, *args], self.env, **kwargs)[0]

    def rpc(self, method, args=None):
        result = self.command("api", "call", method, json.dumps(args or {}))
        if result.returncode:
            raise RuntimeError("rex_rpc_failed:" + method)
        return json.loads(result.stdout)

    def fixture(self, marker="READINESS_SENTINEL"):
        script = "import os,sys,time;print(sys.argv[1],flush=True);print('\\x1b]7501;state=working\\x07',end='',flush=True);time.sleep(900)"
        result = self.command("new", "--json", "--keep-open", "--shell=none", "--", sys.executable, "-c", script, marker)
        if result.returncode:
            raise RuntimeError("sentinel_creation_failed")
        value = json.loads(result.stdout)
        session, block = value["session_id"], value["initial_windows"][0]["block_ids"][0]
        end = time.monotonic() + 5
        while marker not in self.terminal(session, block, "format", dict(format="text", max_bytes=65534)).get("content", ""):
            if time.monotonic() >= end:
                raise RuntimeError("sentinel_not_ready")
            time.sleep(.02)
        return session, block

    def terminal(self, session, block, method, args=None):
        return self.rpc("com.superlogical.terminal." + method, dict(session_id=session, block_id=block, args=args or {}))

    def close(self):
        if getattr(self, "process", None) is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.close()


def observations(binary, server, session, block, maximum=4096):
    return [str(binary), "observe", "--socket", str(server.socket), "--session", session, "--block", block, "--max-bytes", str(maximum)]


def controls(server, session, block, sentinel):
    view = server.rpc("session.view", dict(session_id=session))
    # Client ownership is connection-lifetime metadata, not a layout mutation.
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in {"revision", "owner", "desired", "updated_at", "client_id"}}
        if isinstance(value, list):
            return [strip(x) for x in value]
        return value
    return dict(N1=sorted(b["block_id"] for b in server.rpc("session.list_blocks", dict(session_id=session))["blocks"]),
        N2=strip(view), N3=dict(capture=server.terminal(session, block, "format", dict(format="text", max_bytes=65534)),
            status=server.terminal(session, block, "program_status"), process=server.terminal(session, block, "process")),
        N4=dict(pid=server.process.pid, alive=server.process.poll() is None, version=server.version),
        N5=sentinel.poll() is None,
        N6=sorted(str(p.relative_to(server.home)) for p in server.home.rglob("*")))


def alive(pid):
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")
