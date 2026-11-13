"""Count task tool calls without retaining model text or arbitrary arguments."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def append(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(value, separators=(",", ":")) + "\n").encode())
    finally:
        os.close(fd)


def run(config, tool, argv):
    began = time.monotonic_ns()
    target = argv[argv.index("--block") + 1] if "--block" in argv and argv.index("--block") + 1 < len(argv) else None
    allowed = {"observe", "compare", "watch", "run-visible", "run", "surfaces", "open", "close", "send", "ask", "api", "call", "new", "do", "agents", "ack", "stop", "inspect", "version"}
    verbs = [x for x in argv if x in allowed][:2]
    event_input = False
    for argument in argv:
        if argument.startswith("{"):
            try:
                value = json.loads(argument)
                if isinstance(value, dict) and isinstance(value.get("block_id"), str):
                    target = value["block_id"]
                    event_input = "block.event" in argv and value.get("event", {}).get("type") in ("paste", "key", "keypress")
            except ValueError:
                pass
    input_attempted = "send" in verbs or event_input
    interrupted = tool == "agent-send" or tool == "teerex" and "ask" in argv
    blocked = tool == "teerex" and config["condition"] == "plain-rex"
    entry = dict(t=began, tool=tool, verb=verbs, target_block=target, stdout_bytes=0, exit=0, input_attempted=input_attempted)
    if interrupted or blocked:
        entry.update(exit=127 if blocked and not interrupted else 0, blocked=blocked, interruption=interrupted)
        append(config["log"], entry)
        return entry["exit"]
    real = config[tool]
    env = dict(os.environ)
    if tool == "teerex":
        env["TEEREX_INTERNAL_REX"] = config["rex_shim"]
        env["TEEREX_REX"] = config["rex_shim"]
    child = subprocess.Popen([real, *argv], env=env, stdout=subprocess.PIPE)
    chunks = []
    size = 0
    while True:
        data = child.stdout.read(65536)
        if not data:
            break
        size += len(data)
        if size <= 8 * 1024 * 1024:
            chunks.append(data)
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    child.stdout.close()
    code = child.wait()
    entry.update(stdout_bytes=size, exit=code)
    # Ownership is a separate private list, acquired only from creation receipts.
    if code == 0:
        try:
            value = json.loads(b"".join(chunks))
            owned = []
            def walk(node):
                if isinstance(node, dict):
                    if isinstance(node.get("created"), dict):
                        owned.extend(x for k, x in node["created"].items() if k in ("block_id",) and isinstance(x, str))
                    if "block_ids" in node and isinstance(node["block_ids"], list):
                        owned.extend(node["block_ids"])
                    for nested in node.values():
                        walk(nested)
                elif isinstance(node, list):
                    for nested in node:
                        walk(nested)
            walk(value)
            for block in owned:
                append(config["owned"], block)
        except (ValueError, TypeError):
            pass
    append(config["log"], entry)
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    sys.exit(run(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2], sys.argv[3:]))
