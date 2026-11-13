"""Synthetic bracketed-paste prompt for disposable draft-guard tests only."""
import json
import os
from pathlib import Path
import sys
import tty
import time
import re

tty.setraw(0)
log = Path(sys.argv[1])
suggestion = sys.argv[2] if len(sys.argv) > 2 else "suggestion"
mode = sys.argv[3] if len(sys.argv) > 3 else "clear"
ignore_clear = mode == "ignore-clear"
submitted = 0
draft, pending, pasting = b"", b"", False
log.touch()
os.write(1, b"\x1b[?2004h")


def draw():
    # Claude Code renders internal runs of spaces as cursor-forward movements.
    content = draft if draft else b"\x1b[90m" + suggestion.encode() + b"\x1b[0m"
    content = re.sub(rb" +", lambda m: b"\x1b[" + str(len(m[0])).encode() + b"C", content)
    os.write(1, "\r\x1b[2K❯\xa0".encode() + content)


draw()
while True:
    pending += os.read(0, 65536)
    while pending:
        if pending.startswith(b"\x1b"):
            marker = b"\x1b[201~" if pasting else b"\x1b[200~"
            if len(pending) < len(marker):
                break
            if pending.startswith(marker):
                pasting = not pasting
                pending = pending[len(marker):]
                continue
        byte, pending = pending[:1], pending[1:]
        if not pasting and byte == b"\x15":
            if not ignore_clear:
                draft = b""
        elif not pasting and byte in (b"\r", b"\n"):
            with log.open("a") as f:
                f.write(json.dumps(draft.decode("utf-8")) + "\n")
            draft = b""
            submitted += 1
            if mode == "late-redraw":
                time.sleep(.6)
        elif pasting and submitted and mode == "drop-restore":
            pass
        else:
            draft += byte
    draw()
