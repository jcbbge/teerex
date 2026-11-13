"""P0: documented wire contract against a private disposable Rex server only."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from wire import Control, data_connect


class WireProbe(unittest.TestCase):
    def test_echo_snapshot_resize_and_child_exit(self):
        rex = os.environ.get("REX_BIN") or shutil.which("rex")
        self.assertTrue(rex, "REX_BIN must select a test Rex")
        with tempfile.TemporaryDirectory(prefix="replay-p0-", dir="/tmp") as directory:
            root = Path(directory)
            path = root / "rex.sock"
            with (root / "server.log").open("w+") as log:
                server = subprocess.Popen([rex, "server", "run", "--listen", "unix://" + str(path),
                                           "--restore=false", "--config", "/dev/null", "--state-dir", str(root / "state")], stdout=log, stderr=log)
                try:
                    for _ in range(100):
                        if path.exists():
                            break
                        if server.poll() is not None:
                            log.seek(0)
                            self.fail(log.read())
                        time.sleep(.05)
                    self.assertTrue(path.exists(), "private server did not start")
                    control = Control(path)
                    try:
                        version = control.call("server.version", {})
                        print("P0 Rex:", json.dumps(version), flush=True)
                        session = control.call("session.create", {"label": "private replay P0"})["session_id"]
                        control.call("session.attach", {"session_id": session})
                        # CLI owns command construction; the child waits for a local gate,
                        # so echo cannot exit before the data stream is listening.
                        gate = root / "go"
                        script = "import pathlib,time,os; p=pathlib.Path(__import__('sys').argv[1]);\nwhile not p.exists(): time.sleep(.01)\nos.execl('/bin/echo','echo','teerex-p0')"
                        created = json.loads(subprocess.check_output([rex, "--autostart=false", "--server", "unix://" + str(path),
                            "run", "-s", session, "--shell=none", "--keep-open", "--json", "--", sys.executable, "-c", script, str(gate)], timeout=10))
                        block = created["block_ids"][0]
                        stream, nonce = data_connect(control, path, session, block)
                        try:
                            buffer = bytearray()
                            pattern = re.compile(rb"\x1b_rex1;" + str(nonce).encode() + rb";(.+?)\x1b\\", re.DOTALL)
                            while not (markers := list(pattern.finditer(buffer))):
                                buffer.extend(stream.receive())
                            first = markers[0]
                            self.assertGreater(first.start(), 0, "snapshot absent before first APC")
                            self.assertEqual(json.loads(first[1])["type"], "resize")
                            print("P0 snapshot bytes:", first.start(), "first marker: resize", flush=True)
                            gate.touch()
                            while not any(json.loads(m[1]).get("type") == "child_exited" for m in pattern.finditer(buffer)):
                                buffer.extend(stream.receive())
                            events = [json.loads(m[1]) for m in pattern.finditer(buffer)]
                            self.assertIn(b"teerex-p0\r\n", buffer)
                            self.assertEqual(next(e for e in events if e["type"] == "child_exited")["exit_code"], 0)
                        finally:
                            stream.close()
                        control.call("session.destroy", {"session_id": session})
                    finally:
                        control.close()
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
