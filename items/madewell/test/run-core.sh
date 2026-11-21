#!/bin/sh
set -eu
exec python3 - "$(dirname "$0")" "$@" <<'PY'
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

test_dir = Path(sys.argv[1]).resolve()
item = test_dir.parent
cases = sys.argv[2:] or ["one", "wiring", "lua", "span", "resume", "restart", "limit"]

with tempfile.TemporaryDirectory(prefix="mw-core.", dir=os.getenv("XDG_RUNTIME_DIR")) as work:
    work = Path(work)
    fixture = work / "item"
    fixture.mkdir()
    (fixture / "lua").symlink_to(item / "lua")
    wrapper = item / "hand"
    shutil.copy2(wrapper if wrapper.exists() else test_dir / "hand-stub", fixture / "hand")
    (work / "state").mkdir()
    (work / "init.lua").write_text("-- disposable Made Well checks\n")
    socket = work / "rex.sock"
    env = os.environ.copy()
    env["TMPDIR"] = str(work)
    for key in ("REX_SESSION", "REX_BLOCK", "REX_CLIENT"):
        env.pop(key, None)
    rex = ["rex", "-S", f"unix://{socket}", "--autostart=false"]

    def invoke(*args, **kwargs):
        return subprocess.run([*rex, *args], check=True, env=env, timeout=30, **kwargs)

    def start(max_blocks=0):
        invoke("server", "start", "--state-dir", str(work / "state"),
               "--config", str(work / "init.lua"), "--restore=false",
               "--max-blocks", str(max_blocks), "--max-windows", "0", "--max-panes", "0", "--max-sessions", "0")
        return invoke("new", "core-test", capture_output=True, text=True).stdout.strip()

    def stop():
        invoke("server", "stop")
        assert not socket.exists(), "disposable Rex socket survived server stop"

    def config(case, **extra):
        return json.dumps(dict(item=str(fixture), root=str(work / "runs"), test=case,
            fifo=str(work / f"{case}.fifo"), retry_flag=str(work / "retried"),
            restart_flag=str(work / "restarted"), **extra))

    def run_case(session, case, **extra):
        command = [*rex, "do", "-s", session, str(test_dir / "core.lua"), "--args", config(case, **extra)]
        result = subprocess.run(command, env=env, stdout=subprocess.PIPE, text=True, timeout=30)
        print(re.sub(r"\x1b\]7501;[^\x1b]*\x1b\\", "", result.stdout), end="", flush=True)
        result.check_returncode()

    def watch(session, case, **trigger):
        args = dict(endpoint=f"unix://{socket}", session=session, tmp=str(work),
                    script=str(test_dir / "core.lua"), config=config(case), **trigger)
        invoke("do", "-s", session, str(test_dir / "watch-core.lua"), "--args", json.dumps(args))

    try:
        session = start()
        for case in cases:
            if case == "one":
                watch(session, case, title="one.1", state="done")
            elif case == "restart":
                os.mkfifo(work / "restart.fifo")
                watch(session, case, title="unfinished.1", state="working", msg="Hand started")
                stop()
                (work / "restarted").touch()
                session = start()
                run_case(session, case, restarted=True)
            elif case == "limit":
                stop()
                session = start(max_blocks=1)
                run_case(session, case)
            else:
                run_case(session, case)
    finally:
        if socket.exists():
            stop()
PY
