"""Disposable boxed PTY editor with an independent byte log and draft snapshot."""
import json
import os
from pathlib import Path
import re
import select
import sys
import tty
import unicodedata

tty.setraw(0)
root, initial, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
draft = list(initial)
cursor = len(draft) // 2 if mode == "mid" else len(draft)
pending = b""
pasting = False


def draw():
    (root / "draft").write_text("".join(draft))
    prefix = "" if mode in ("unmarked", "rounded", "square", "vertical", "single-rule") else "❯ "
    rows = [prefix]
    column = len(prefix)
    positions = [(0, column + 1)]
    for char in draft:
        width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if char == "\n" or column + width > 60:
            rows.append("  ")
            column = 2
        if char != "\n":
            rows[-1] += char
            column += width
        positions.append((len(rows) - 1, column + 1))
    row, col = positions[cursor]
    start = max(0, len(rows) - 12)
    rule = "─" * 60
    top = rule if start == 0 else "── ↑ " + str(start) + " more " + rule
    visible = rows[start:]
    if not draft:
        visible[0] += "\x1b[90mSuggestion\x1b[0m"
    elif mode == "placeholder" and not "".join(draft).startswith("FROM "):
        visible, row, col, start = ["❯ [Pasted text #1 +11 lines]"], 0, 29, 0
    screen = "\x1b[?2004h\x1b[2J\x1b[H"
    if mode == "menu":
        screen += "\x1b]7501;state=idle:app=claude\x07" + rule + "\r\nRewind\r\n  ❯ (current)"
        os.write(1, (screen + "\x1b[3;3H").encode())
        return
    if mode in ("rounded", "square", "vertical"):
        corners = "╭╮╰╯" if mode == "rounded" else "┌┐└┘"
        visible = ["│ " + line.ljust(60) + " │" for line in visible]
        col += 2
        top, rule = corners[0] + rule + corners[1], corners[2] + rule + corners[3]
        if mode == "vertical":
            top = rule = ""
    elif mode == "single-rule":
        rule = ""
    screen += "\r\n".join([top, *visible, rule])
    os.write(1, (screen + f"\x1b[{max(0, row-start)+2};{col}H").encode())


with (root / "bytes").open("ab", buffering=0) as raw, (root / "submissions").open("a", buffering=1) as submitted:
    draw()
    while chunk := os.read(0, 65536):
        raw.write(chunk)
        pending += chunk
        redraw = True
        while pending:
            marker = b"\x1b[201~" if pasting else b"\x1b[200~"
            if marker.startswith(pending) and pending != marker:
                break
            if pending.startswith(marker):
                pasting = not pasting
                if not pasting and mode == "delayed-paste":
                    select.select([], [], [], .55)
                if not pasting and mode == "stop-budget":
                    select.select([], [], [], 1.35)
                if not pasting and mode == "progressive":
                    full = draft[:]
                    del draft[len(full) * 2 // 3:]
                    cursor = len(draft)
                    draw()
                    select.select([], [], [], .2)
                    draft[:] = full
                    cursor = len(draft)
                pending = pending[len(marker):]
                continue
            match = re.match(rb"[\xc0-\xff][\x80-\xbf]*|.", pending, re.S)
            token = match[0]
            try:
                char = token.decode()
            except UnicodeDecodeError:
                break
            pending = pending[len(token):]
            if not pasting and char == "\x18":
                draft.clear()
                cursor = 0
            elif not pasting and char == "\x15":
                start = cursor
                while start and draft[start-1] != "\n" and cursor - start < 58:
                    start -= 1
                del draft[start:cursor]
                cursor = start
            elif not pasting and char in "\r\n":
                submitted.write(json.dumps("".join(draft)) + "\n")
                if mode == "settle":
                    draw()
                    readable, _, _ = select.select([0], [], [], .55)
                    redraw = not readable
                draft.clear()
                cursor = 0
            else:
                draft.insert(cursor, char)
                cursor += 1
        if redraw:
            draw()
