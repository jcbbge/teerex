"""Local stdio MCP 2025-11-25; fixed teerex verbs, literal argv, no network listener.

Sources: MCP 2025-11-25 lifecycle/transports/server/tools; client configuration
sources and local flag owners are linked in README.md. Python 3.9+, stdlib only.
"""
import argparse
import base64
import json
import math
import os
from pathlib import Path
import re
import select
import selectors
import signal
import subprocess
import sys
import threading
import time

PROTOCOL = "2025-11-25"
MAX_MESSAGE = 256 * 1024
MAX_OUTPUT = 2 * 1024 * 1024
CALL_SECONDS = 180
ID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"


def string(maximum=4096, **extra):
    return dict(type="string", minLength=1, maxLength=maximum, **extra)


def integer(low, high, **extra):
    return dict(type="integer", minimum=low, maximum=high, **extra)


PATH = string(pattern=r"^/", description="Absolute path on the MCP server's command host.")
SESSION = string(pattern="^session:" + ID + "$", description="Canonical session ID; defaults to REX_SESSION when omitted.")
BLOCK = string(pattern="^block:" + ID + "$")
SELECTOR = string(description="Canonical ID, unique suffix, or exact label; surfaces resolves ambiguity without guessing.")
SOCKET = dict(PATH, description="Absolute existing Rex socket; defaults to unix:///ABS in REX_SERVER.")
TIMEOUT = integer(100, 60000)
YES_NO = string(enum=["yes", "no"])
LABEL = string(128)
TEXT = string(256)
ARGV = dict(type="array", minItems=1, maxItems=128,
            items=dict(type="string", maxLength=4096),
            description="Literal argv for a visible program; absolute executable required. No shell or raw Rex entrypoint.")
GEOMETRY = dict(layout=string(enum=["tab", "tiled", "float"]), anchor=SELECTOR,
                direction=string(enum=["right", "left", "up", "down"]),
                ratio=dict(type="number", exclusiveMinimum=0, exclusiveMaximum=1),
                bounds=dict(type="array", minItems=4, maxItems=4, items=dict(type="number", minimum=0, maximum=1)))


def tool(command, properties, required=(), write=False, fixed=()):
    """One allowlist entry owns both discovery schema and validation/argv input."""
    return dict(command=command, fixed=fixed,
                public=dict(name="_".join(command), description="teerex " + " ".join(command) + "; returns the original stdout/stderr and exit code. No retry or inferred success.",
                            inputSchema=dict(type="object", properties=properties, required=list(required), additionalProperties=False),
                            annotations=dict(readOnlyHint=not write, destructiveHint=write, openWorldHint=write, idempotentHint=not write)))


TOOLS = {}
for entry in [
    tool(["observe"], dict(socket=SOCKET, session=SESSION, block=BLOCK, max_bytes=integer(256, 65536), timeout_ms=TIMEOUT), ["block"]),
    tool(["watch"], dict(socket=SOCKET, session=SESSION, block=BLOCK, baseline=PATH, timeout_ms=TIMEOUT,
                         interval_ms=integer(50, 5000), status_state=dict(type="array", minItems=1, maxItems=5, uniqueItems=True,
                         items=string(enum=["idle", "working", "done", "blocked", "error"])), status_id=string(1024)), ["block", "baseline", "timeout_ms"]),
    tool(["compare"], dict(before=PATH, after=PATH, view=string(enum=["progress-v1"]), view_rules=PATH), ["before", "after"]),
    tool(["send"], dict(socket=SOCKET, session=SESSION, block=BLOCK, sender=LABEL,
                        message=dict(type="string", minLength=1, maxLength=65536, description="UTF-8 body sent on child stdin; never interpolated or logged by MCP."),
                        draft=string(enum=["guard", "ignore"]), draft_wait_ms=integer(0, 55000), timeout_ms=integer(100, 115000)), ["block", "sender", "message"], write=True),
    tool(["surfaces", "resolve"], dict(socket=SOCKET, session=SELECTOR, pane=SELECTOR, window=SELECTOR, timeout_ms=TIMEOUT)),
    tool(["surfaces", "open"], dict(socket=SOCKET, session=SELECTOR, label=LABEL, cwd=PATH, timeout_ms=TIMEOUT, argv=ARGV, **GEOMETRY), ["layout", "label", "argv"], write=True),
    tool(["surfaces", "ensure"], dict(socket=SOCKET, session=SELECTOR, label=LABEL, cwd=PATH, timeout_ms=TIMEOUT, argv=ARGV,
                                      focus=YES_NO, create_session=SELECTOR, **GEOMETRY), ["label", "argv"], write=True),
    *[tool(["surfaces", op], dict(socket=SOCKET, session=SELECTOR, pane=SELECTOR, timeout_ms=TIMEOUT), ["pane"], write=op != "inspect") for op in ("inspect", "focus", "close")],
    tool(["surfaces", "rename"], dict(socket=SOCKET, session=SELECTOR, pane=SELECTOR, window=SELECTOR, label=LABEL, timeout_ms=TIMEOUT), ["label"], write=True),
    tool(["run-visible"], dict(socket=SOCKET, session=SESSION, cwd=PATH, env_file=PATH, stdin_file=PATH,
                               app=LABEL, title=LABEL, argv=ARGV, layout=string(enum=["tab", "tiled"]),
                               anchor=BLOCK, direction=GEOMETRY["direction"], ratio=GEOMETRY["ratio"],
                               timeout_ms=TIMEOUT, startup_ms=integer(1000, 60000), max_bytes=integer(1, 65536),
                               keep_open=dict(type="boolean"), output_dir=PATH, registry=PATH, owner=LABEL, purpose=TEXT),
         ["cwd", "env_file", "stdin_file", "app", "title", "argv"], write=True),
    tool(["jobs", "list"], dict(registry=PATH), ["registry"]),
    tool(["jobs", "doctor"], dict(registry=PATH, socket=SOCKET, timeout_ms=TIMEOUT), ["registry"]),
    tool(["jobs", "present"], dict(registry=PATH, socket=SOCKET, session=SESSION, block=BLOCK, owner=LABEL,
                                   generation=integer(1, 2**63 - 1), reason=TEXT, anchor=BLOCK, focus=YES_NO,
                                   label=LABEL, relocate=YES_NO, timeout_ms=TIMEOUT),
         ["registry", "block", "owner", "generation", "reason", "anchor", "focus"], write=True),
    tool(["agents", "launch"], dict(config=PATH, profile=LABEL, registry=PATH, socket=SOCKET, session=SESSION,
                                    name=LABEL, cwd=PATH, starter_session=SESSION, starter_block=BLOCK,
                                    report_to_session=SESSION, report_to_block=BLOCK, host=LABEL, owner=LABEL,
                                    purpose=TEXT, store=PATH, brief_file=PATH, review_at=integer(1, 2**63 - 1),
                                    launch_wait_ms=integer(0, 60000), ack_timeout_ms=integer(100, 60000)), ["config", "profile"], write=True),
    tool(["boards", "calls"], dict(limit=integer(1, 128), config=PATH, hosts=string()), fixed=["--once", "--json"]),
    tool(["doctor"], dict(socket=SOCKET, timeout_ms=TIMEOUT, baseline=PATH)),
    tool(["cartridges", "list"], dict(root=PATH)),
]:
    # Tool names deliberately use underscores, including the root run-visible verb.
    name = entry["public"]["name"].replace("-", "_")
    entry["public"]["name"] = name
    TOOLS[name] = entry


class InvalidArguments(ValueError):
    pass


def validate(value, schema):
    kind = schema["type"]
    if kind == "object":
        if type(value) is not dict or set(value) - set(schema["properties"]):
            raise InvalidArguments("unknown or non-object arguments")
        if set(schema["required"]) - set(value):
            raise InvalidArguments("required arguments missing")
        for key, item in value.items():
            validate(item, schema["properties"][key])
    elif kind == "string":
        if type(value) is not str:
            raise InvalidArguments("string required")
        try:
            encoded = value.encode("utf-8")
        except UnicodeError:
            raise InvalidArguments("valid UTF-8 required") from None
        if not schema.get("minLength", 0) <= len(value) <= schema["maxLength"] or len(encoded) > 65536:
            raise InvalidArguments("string outside bounds")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise InvalidArguments("invalid path or canonical target")
        if "enum" in schema and value not in schema["enum"]:
            raise InvalidArguments("invalid enum value")
        if "\0" in value:
            raise InvalidArguments("NUL refused")
    elif kind in ("integer", "number"):
        if type(value) not in ((int,) if kind == "integer" else (int, float)) or not math.isfinite(value):
            raise InvalidArguments("finite number required")
        if not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
            raise InvalidArguments("number outside bounds")
        if value <= schema.get("exclusiveMinimum", -math.inf) or value >= schema.get("exclusiveMaximum", math.inf):
            raise InvalidArguments("number outside exclusive bounds")
    elif kind == "boolean":
        if type(value) is not bool:
            raise InvalidArguments("boolean required")
    elif kind == "array":
        if type(value) is not list or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise InvalidArguments("array outside bounds")
        for item in value:
            validate(item, schema["items"])
        if schema.get("uniqueItems") and len(set(value)) != len(value):
            raise InvalidArguments("duplicate array value")


def command_for(name, arguments, environment):
    if name not in TOOLS:
        raise InvalidArguments("unknown tool")
    entry = TOOLS[name]
    schema = entry["public"]["inputSchema"]
    if type(arguments) is not dict:
        raise InvalidArguments("arguments must be an object")
    arguments = arguments.copy()
    if "socket" in schema["properties"] and "socket" not in arguments and environment.get("REX_SERVER"):
        endpoint = environment["REX_SERVER"]
        if not endpoint.startswith("unix:///"):
            raise InvalidArguments("REX_SERVER must be unix:///ABS; supply socket explicitly")
        arguments["socket"] = endpoint[len("unix://"):]
    if "session" in schema["properties"] and "session" not in arguments and environment.get("REX_SESSION"):
        arguments["session"] = environment["REX_SESSION"]
    validate(arguments, schema)
    for field in ("socket", "session"):
        if field in schema["properties"] and field not in arguments and name != "jobs_doctor":
            raise InvalidArguments("explicit target or server environment required")
    for key, value in arguments.items():
        if isinstance(value, str) and key != "message" and (value.startswith("-") or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise InvalidArguments("option-like or control-bearing value refused")
    if name == "surfaces_rename" and ("pane" in arguments) == ("window" in arguments):
        raise InvalidArguments("choose pane or window")
    if name == "surfaces_resolve" and "pane" in arguments and "window" in arguments:
        raise InvalidArguments("choose pane or window")
    if name == "watch" and "status_id" in arguments and "status_state" not in arguments:
        raise InvalidArguments("status_id needs status_state")
    if name == "compare" and "view" in arguments and "view_rules" in arguments:
        raise InvalidArguments("choose view or view_rules")
    argv = list(entry["command"])
    if name == "cartridges_list" and "root" in arguments:
        argv = ["cartridges", "--root", arguments.pop("root"), "list"]
    data = None
    for key, value in arguments.items():
        if key == "argv":
            continue
        flag = "--" + {"sender": "from", "message": "message-file"}.get(key, key.replace("_", "-"))
        if key == "message":
            data = value.encode("utf-8")
            if any(byte < 32 and byte not in (9, 10) or byte == 127 for byte in data):
                raise InvalidArguments("invalid message control bytes")
            argv += [flag, "-"]
        elif type(value) is bool:
            if value:
                argv.append(flag)
        elif key == "bounds":
            argv += [flag, json.dumps(value, separators=(",", ":"))]
        elif type(value) is list:
            for item in value:
                argv += [flag, str(item)]
        else:
            argv += [flag, str(value)]
    argv += list(entry["fixed"])
    if "argv" in arguments:
        program = arguments["argv"][0]
        if not os.path.isabs(program) or Path(program).name in {"sh", "bash", "zsh", "dash", "fish", "ksh", "rex", "Rex Server"}:
            raise InvalidArguments("absolute non-shell, non-Rex visible program required")
        argv += ["--", *arguments["argv"]]
    return argv, data


def decoded(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        return dict(encoding="base64", data=base64.b64encode(raw).decode("ascii"))


def execute(argv, data, cancelled, timeout=CALL_SECONDS):
    """Keep the leader unreaped until all owned-group cancellation is finished.

    No shell. EOF/INT/TERM/request cancellation reach only this tool invocation's
    group. This cannot undo Rex mutation or certify remote/detached descendants.
    """
    output = [bytearray(), bytearray()]
    error = None
    with subprocess.Popen(argv, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True) as process:
        try:
            stop_at = None
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as streams:
                for index, stream in enumerate((process.stdout, process.stderr)):
                    os.set_blocking(stream.fileno(), False)
                    streams.register(stream, selectors.EVENT_READ, index)
                if data is not None:
                    os.set_blocking(process.stdin.fileno(), False)
                    streams.register(process.stdin, selectors.EVENT_WRITE, 2)
                sent = 0
                while streams.get_map():
                    now = time.monotonic()
                    if stop_at is None and (cancelled.is_set() or now >= deadline or error):
                        error = error or ("cancelled" if cancelled.is_set() else "deadline_exceeded")
                        try:
                            os.killpg(process.pid, signal.SIGINT)
                        except ProcessLookupError:
                            pass
                        stop_at = now + 3
                    if stop_at is not None and now >= stop_at:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        # A detached descendant might still hold a pipe. Never wait
                        # indefinitely or kill unrelated work after reaping the leader.
                        break
                    for key, _ in streams.select(.05):
                        if key.data == 2:
                            try:
                                sent += os.write(key.fd, data[sent:sent + 8192])
                            except BrokenPipeError:
                                sent = len(data)
                            if sent == len(data):
                                streams.unregister(key.fileobj)
                                key.fileobj.close()
                        else:
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                streams.unregister(key.fileobj)
                            else:
                                retained = sum(map(len, output))
                                output[key.data].extend(chunk[:max(0, MAX_OUTPUT - retained)])
                                if retained + len(chunk) > MAX_OUTPUT:
                                    error = "output_limit_exceeded"
                try:
                    code = process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    error = error or "deadline_exceeded"
                    os.killpg(process.pid, signal.SIGKILL)
                    code = process.wait(timeout=3)
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
    stdout, stderr = map(bytes, output)
    receipt = None
    if error != "output_limit_exceeded":
        try:
            receipt = strict_json(stdout)
        except (ValueError, UnicodeError, RecursionError):
            pass
    return dict(exit_code=code, stdout=decoded(stdout), stderr=decoded(stderr), receipt=receipt,
                transport_error=error, effect="not_reinterpreted; inspect original receipt before any retry")


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("nonfinite JSON number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


class Server:
    def __init__(self, executable):
        self.executable = executable
        self.initialized = False
        self.ready = False
        self.active = None
        self.guard = threading.Lock()
        self.writer = threading.Lock()
        self.stopping = threading.Event()
        self.worker = None

    def send(self, value):
        raw = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"
        with self.writer:
            deadline = time.monotonic() + 5
            try:
                while raw and not self.stopping.is_set():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("stdio consumer is not reading")
                    if select.select([], [sys.stdout.fileno()], [], .1)[1]:
                        try:
                            count = os.write(sys.stdout.fileno(), raw[:65536])
                        except BlockingIOError:
                            continue
                        raw = raw[count:]
            except OSError:
                self.stopping.set()
                with self.guard:
                    if self.active:
                        self.active[1].set()

    def reply(self, identity, result=None, error=None):
        self.send(dict(jsonrpc="2.0", id=identity, **({"error": error} if error else {"result": result})))

    def fail(self, identity, code, message):
        self.reply(identity, error=dict(code=code, message=message))

    def call(self, identity, name, command, data, cancelled):
        try:
            try:
                result = execute([self.executable, *command], data, cancelled)
            except OSError:
                result = dict(exit_code=None, stdout="", stderr="", receipt=None, transport_error="tool_transport_failed",
                              effect="unknown; inspect before retry")
            failed = result["exit_code"] != 0 or result["transport_error"] is not None
            with self.guard:
                if self.active and self.active[1] is cancelled:
                    self.active = None
            self.reply(identity, dict(content=[dict(type="text", text=json.dumps(result, ensure_ascii=True))],
                                      structuredContent=result, isError=failed))
            # Metadata only: never request IDs, arguments, bodies, captures or env.
            metadata = json.dumps(dict(kind="mcp_call", tool=name, exit_code=result["exit_code"],
                                       transport_error=result["transport_error"])).encode() + b"\n"
            try:
                os.write(sys.stderr.fileno(), metadata)
            except OSError:
                pass  # Best effort: an unread diagnostic pipe must not stall tools.
        finally:
            with self.guard:
                if self.active and self.active[1] is cancelled:
                    self.active = None

    def handle(self, message):
        if type(message) is not dict or set(message) - {"jsonrpc", "id", "method", "params"} or message.get("jsonrpc") != "2.0" or type(message.get("method")) is not str:
            self.fail(None, -32600, "invalid request")
            return
        identity = message.get("id")
        if "id" in message and (type(identity) not in (int, str) or isinstance(identity, str) and len(identity) > 128):
            self.fail(None, -32600, "invalid request id")
            return
        method = message["method"]
        params = message.get("params", {})
        if "id" not in message:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            elif method == "notifications/cancelled" and type(params) is dict:
                with self.guard:
                    if self.active and type(params.get("requestId")) is type(self.active[0]) and params.get("requestId") == self.active[0]:
                        self.active[1].set()
            return  # Notifications, including tools/call, never cause dispatch.
        if type(params) is not dict:
            self.fail(identity, -32602, "params must be an object")
        elif method == "ping":
            self.reply(identity, {})
        elif method == "initialize":
            info = params.get("clientInfo")
            if self.initialized or type(params.get("protocolVersion")) is not str or type(params.get("capabilities")) is not dict or type(info) is not dict or any(type(info.get(key)) is not str or not 1 <= len(info[key]) <= 128 for key in ("name", "version")):
                self.fail(identity, -32602, "invalid initialization")
                return
            self.initialized = True
            self.reply(identity, dict(protocolVersion=PROTOCOL, capabilities=dict(tools=dict(listChanged=False)),
                                      serverInfo=dict(name="teerex", version="1"),
                                      instructions="Tools preserve native receipts. Mutations require caller authorization; annotations are hints. Never blindly retry uncertain effects."))
        elif not self.ready:
            self.fail(identity, -32002, "initialize and notifications/initialized required")
        elif method == "tools/list":
            if set(params) - {"_meta", "cursor"} or params.get("cursor") is not None:
                self.fail(identity, -32602, "invalid cursor or params")
            else:
                self.reply(identity, dict(tools=[TOOLS[name]["public"] for name in sorted(TOOLS)]))
        elif method == "tools/call":
            if set(params) - {"name", "arguments", "_meta"} or type(params.get("name")) is not str:
                self.fail(identity, -32602, "invalid tool call")
                return
            try:
                command, data = command_for(params["name"], params.get("arguments", {}), os.environ)
            except (InvalidArguments, TypeError, ValueError, OverflowError):
                self.fail(identity, -32602, "invalid tool arguments; consult tools/list schema and explicit target requirements")
                return
            with self.guard:
                busy = self.active is not None
                if not busy:
                    cancelled = threading.Event()
                    self.active = (identity, cancelled)
            if busy:
                self.fail(identity, -32000, "tool call busy; no request was queued or dispatched")
                return
            self.worker = threading.Thread(target=self.call, args=(identity, params["name"], command, data, cancelled))
            self.worker.start()
        else:
            self.fail(identity, -32601, "method not found")

    def run(self):
        def stop(_signal, _frame):
            self.stopping.set()
        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, stop)
        os.set_blocking(sys.stdout.fileno(), False)
        os.set_blocking(sys.stderr.fileno(), False)
        pending = bytearray()
        try:
            while not self.stopping.is_set():
                if not select.select([sys.stdin.buffer], [], [], .1)[0]:
                    continue
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    if pending:
                        self.fail(None, -32700, "unterminated JSON-RPC frame")
                    break
                pending.extend(data)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    if len(line) > MAX_MESSAGE:
                        self.fail(None, -32600, "message exceeds 256 KiB")
                        self.stopping.set()
                        break
                    try:
                        message = strict_json(line.decode("utf-8"))
                    except (ValueError, UnicodeError, RecursionError):
                        self.fail(None, -32700, "invalid JSON")
                        continue
                    self.handle(message)
                if len(pending) > MAX_MESSAGE:
                    self.fail(None, -32600, "message exceeds 256 KiB")
                    break
        finally:
            self.stopping.set()
            with self.guard:
                if self.active:
                    self.active[1].set()
            if self.worker:
                self.worker.join(timeout=10)


def main():
    # The compiled wrapper supplies its own absolute executable; no client tool
    # can choose a replacement binary, command family, script or interpreter.
    executable = sys.argv[1]
    parser = argparse.ArgumentParser(prog="teerex mcp", description=__doc__)
    parser.add_argument("--print-config", choices=("claude", "codex", "pi"), help="print registration snippet only; never writes config or starts a server")
    options = parser.parse_args(sys.argv[2:])
    if options.print_config == "codex":
        print('[mcp_servers.teerex]\ncommand = ' + json.dumps(executable) + '\nargs = ["mcp"]\nenv_vars = ["REX_SERVER", "REX_SESSION", "TEEREX_REX", "TEEREX_INTERNAL_REX"]\ndefault_tools_approval_mode = "prompt"')
    elif options.print_config:
        print(json.dumps(dict(mcpServers=dict(teerex=dict(command=executable, args=["mcp"]))), indent=2))
    else:
        Server(executable).run()


if __name__ == "__main__":
    main()
