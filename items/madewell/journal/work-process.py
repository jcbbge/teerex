"""Run one already-assigned hand or card and own its Linux process group."""

import importlib.machinery
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ITEM = Path(__file__).resolve().parents[1]
BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def stat(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0], int(fields[2]), int(fields[3]), fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def publish(path, data, once=False):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stage:
        staged = Path(stage.name)
        try:
            json.dump(data, stage)
            stage.flush()
            os.fsync(stage.fileno())
            if once:
                os.link(staged, path)
            else:
                os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)


def reap_abandoned(directory, owner):
    """The group leader is gone. Verify membership and use pidfds to avoid PID reuse."""
    if owner["boot"] != BOOT:
        return
    group = owner["pid"]
    marker = f"MW_WORK_ATTEMPT={directory.name}".encode()
    members = []
    verified = False
    try:
        for path in Path("/proc").iterdir():
            if not path.name.isdecimal():
                continue
            pid = int(path.name)
            current = stat(pid)
            if not current or current[0] == "Z" or current[1:3] != (group, group):
                continue
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            if stat(pid) != current:
                os.close(fd)
                continue
            members.append(fd)
            try:
                verified |= marker in (path / "environ").read_bytes().split(b"\0")
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
        if members and not verified:
            # The group may have been reused. Never signal an unverified process.
            sys.exit(2)
        for fd in members:
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if members:
            sys.exit(1)  # Let the actor observe the reap on its next wake.
    finally:
        for fd in members:
            os.close(fd)


def hand_command(spec):
    drive = importlib.machinery.SourceFileLoader(
        "mw_drive", str(ITEM / "bin/mw-drive")
    ).load_module()
    briefing = drive.briefing(spec["key"], spec["doc"], spec["phase"], spec["step"], spec["who"])
    return drive.command(spec["who"], briefing), None


def card_command(spec, attempt):
    session = spec["session"]
    try:
        clients = json.loads(subprocess.check_output(
            ["rex", "client", "ls", "--json"], timeout=10
        ))["clients"]
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None, None
    # With no initiating tab, use a sitting attached to the operator's Mac app.
    attached = [s for c in clients if c.get("info", {}).get("platform") == "macos"
                and c.get("info", {}).get("kind") == "app"
                and c.get("connection_state") == "connected" for s in c.get("session_ids", [])]
    if session not in attached:
        session = attached[0] if attached else None
    if session is None:
        return None, None
    question = {
        "request_id": attempt.replace("-", ""),
        "session": session,
        "pane": "block:none",
        "from": f"Made Well work {spec['key']}",
        "title": f"{spec['key']} is blocked at {spec['step']}",
        "task": f"This work was opened to do the following. {spec['what']}",
        "purpose": f"Every hand hired for {spec['step']} failed to check the step yes.",
        "intent": "Keep the work open until you decide whether to retry the step or stop.",
        "ask": f"Should Made Well retry {spec['step']} for {spec['key']}, or stop the work?",
        "options": [
            {"id": "A", "gain": "Retry after a temporary failure.", "loss": "The step may fail again."},
            {"id": "B", "gain": "Keep the evidence and stop.", "loss": "The work will stay unfinished."},
        ],
        "recommend": {"id": "B", "why": "Every hand already had a chance to finish this step."},
    }
    return ["agent-ask", "--native-json"], question


def run(directory):
    try:
        spec = json.loads((directory / "launch.json").read_text())
        pid = os.getpid()
        if os.getsid(0) != pid or os.getpgrp() != pid:
            raise RuntimeError("work process requires its own session and process group")
        publish(directory / "pgid", {"pid": pid, "boot": BOOT, "start": stat(pid)[3]}, once=True)
    except (FileExistsError, FileNotFoundError):
        return  # A concurrent launcher claimed the attempt, or it was already reaped.

    cancel = directory / "cancel"
    if cancel.exists():
        return
    result = {"kind": "launch-error"}
    try:
        os.environ["MW_WORK_ATTEMPT"] = directory.name
        if spec["kind"] == "hand":
            os.environ.update(AGENT_PANE=f"work:{spec['key']}", MW_HIRED=spec["label"],
                              MW_HARNESS=spec["who"]["harness"], MW_STEP_LIST=f"plan.{spec['phase']}",
                              MW_STEP_ID=str(spec["step"]["id"]))
            argv, question = hand_command(spec)
        else:
            argv, question = card_command(spec, directory.name)
        if argv is None:
            result = {"kind": "exit", "code": 75}
            return
        # The wrapper holds the pgrp until it has recorded the exit and killed any stragglers.
        with tempfile.TemporaryFile(mode="w+", dir=directory) as answer:
            child = subprocess.Popen(argv, stdin=subprocess.PIPE if question else subprocess.DEVNULL,
                                     stdout=answer if question else subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, text=True)
            if question:
                json.dump(question, child.stdin)
                child.stdin.close()
            while child.poll() is None:
                if cancel.exists():
                    result = {"kind": "cancelled"}
                    return
                if spec.get("deadline") and time.time() * 1000 >= spec["deadline"]:
                    result = {"kind": "stalled"}
                    return
                time.sleep(0.2)
            result = {"kind": "exit", "code": child.returncode}
            if question and child.returncode == 0:
                answer.seek(0)
                data = json.loads(answer.read(65536))
                if all(isinstance(data.get(key), str) and data[key] for key in ("answer", "text", "receipt")):
                    text = data["text"].strip()
                    result = {"kind": "answer", "retry": data["answer"] == "A"
                              or bool(re.fullmatch(r"(?:a|retry)[.!]?", text, re.IGNORECASE)),
                              "text": text, "receipt": data["receipt"]}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass  # Record a fixed outcome. The hand's streamed turns are available on the work.
    finally:
        try:
            publish(directory / "exit", result)
        finally:
            os.killpg(os.getpgrp(), signal.SIGKILL)


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    if len(sys.argv) == 3 and sys.argv[2] == "reap":
        reap_abandoned(directory, json.loads((directory / "pgid").read_text()))
    else:
        run(directory)
