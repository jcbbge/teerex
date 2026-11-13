#!/usr/bin/env python3
"""Synthetic failing CLI. Gate files synchronize observation, never submit input."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ASSERTION = b"assertion failed: expected 4 got 5\n"
PREFIX = b"".join(("step %d/40\n" % n).encode() for n in range(1, 41)) + "résumé ✓\n".encode() + b"P" * 6000 + b"\n"


def expected(mode):
    if mode in ("F1", "F4"):
        return PREFIX + (b"PASS\n" if mode == "F1" else b"ok\n"), ASSERTION if mode == "F1" else b""
    return None


def main(mode):
    if mode not in ("F1", "F2", "F3", "F4", "F5", "F6"):
        raise SystemExit(2)
    gate = os.environ.get("FIXTURE_GATE")
    if gate:
        end = time.monotonic() + 15
        while not Path(gate).exists():
            if time.monotonic() >= end:
                raise SystemExit(125)
            time.sleep(.005)
    if mode in ("F1", "F4"):
        stdout, stderr = expected(mode)
        os.write(1, stdout)
        if stderr:
            os.write(2, stderr)
        raise SystemExit(3 if mode == "F1" else 0)
    if mode in ("F2", "F3"):
        if mode == "F2":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        os.write(1, b"starting\n")
        time.sleep(600)
    if mode == "F5":
        os.write(1, b"\x1b]7501;state=done\x07")
        time.sleep(2)
        raise SystemExit(1)
    if mode == "F6":
        root = Path(os.environ["FIXTURE_DIR"])
        same = subprocess.Popen(["/bin/sleep", "600"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        detached = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (root / "same-group.pid").write_text(str(same.pid))
        (root / "detached.pid").write_text(str(detached.pid))
        raise SystemExit(3)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(2)
    main(sys.argv[1])
