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
ignore_clear = mode == "ignore-clear" or mode.endswith("-ignore-clear")
submitted = 0
draft, pending, pasting = b"", b"", False
log.touch()
os.write(1, b"\x1b[?2004h")


def draw():
    # Claude Code renders internal runs of spaces as cursor-forward movements.
    content = draft if draft else b"\x1b[90m" + suggestion.encode() + b"\x1b[0m"
    content = re.sub(rb" +", lambda m: b"\x1b[" + str(len(m[0])).encode() + b"C", content)
    if mode.startswith("codex"):
        # Captured Codex prompt: bold chevron, RGB background, reset, then a dim placeholder.
        background = b"\x1b[48;2;41;44;49m"
        content = background + draft if draft else b"\x1b[2m" + background + suggestion.encode()
        content = re.sub(rb" +", lambda m: b"\x1b[" + str(len(m[0])).encode() + b"C", content)
        prefix = b"\r\x1b[2K\x1b[0m\x1b[1m" + background + "›".encode() + b"\x1b[0m" + background + b" \x1b[0m"
        os.write(1, prefix + content + b"\x1b[0m" + background + b"\x1b[54X\x1b[54C\x1b[0m")
    elif mode == "busy":
        # Captured busy Claude Code prompt: greyed marker + NBSP, reset, then the human's text or a grey hint.
        marker = b"\x1b[0m\x1b[38;2;153;153;153m" + "❯\xa0".encode() + b"\x1b[0m"
        hint = b"\x1b[38;2;153;153;153m" + suggestion.encode() + b"\x1b[0m"
        body = re.sub(rb" +", lambda m: b"\x1b[" + str(len(m[0])).encode() + b"C", draft) if draft else hint
        os.write(1, b"\r\x1b[2K" + marker + body)
    else:
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
