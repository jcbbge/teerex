"""Synthetic raw-terminal acceptance scenes. Never calls a model."""
import argparse
import os
from pathlib import Path
import signal
import sys
import time
import tty


def write(text):
    os.write(1, text.encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True, choices=["utf8-split", "resize-prompt", "multiline-error", "progress", "confirm", "lookalike"])
    parser.add_argument("--behaviour", choices=["v1", "v2"], default="v1")
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()
    tty.setraw(0)
    if args.scene == "utf8-split":
        os.write(1, b"na\xc3\xafve \xe2")
        time.sleep(.05)
        os.write(1, b"\x9c\x93 \xe6\x97\xa5\xe6\x9c\xac\r\n")
    elif args.scene == "resize-prompt":
        def draw(*unused):
            columns, rows = os.get_terminal_size()
            write("\x1b[2J\x1b[H+" + "-" * (columns - 2) + "+" + f"\x1b[{rows};1H❯ ")
        signal.signal(signal.SIGWINCH, draw)
        draw()
        while os.read(0, 1) != b"q":
            pass
    elif args.scene == "multiline-error":
        write('\x1b[31merror: config invalid\r\n  at line 3\r\n  expected "="\x1b[0m\r\n\x1b]7501;state=done\x07')
        sys.exit(2)
    elif args.scene == "progress":
        for index, percent in ((2, 25), (4, 50), (8, 100)):
            write("\r[" + "#" * index + " " * (8 - index) + f"] {percent}%\x1b]7501;state=working;progress={percent}\x07")
            time.sleep(.2)
    elif args.scene == "confirm":
        root = Path(args.workdir) / "victims"
        root.mkdir(exist_ok=True)
        for name in ("a.txt", "b.txt", "c.txt"):
            (root / name).write_text("synthetic victim\n")
        write("Delete 3 files? " + ("[y/N]" if args.behaviour == "v1" else "[Y/n]"))
        reply = os.read(0, 1)
        if reply == b"y" or args.behaviour == "v2" and reply == b"n":
            for path in root.iterdir():
                path.unlink()
            write("\r\nDeleted.\r\n")
        else:
            write("\r\nAborted.\r\n")
    elif args.scene == "lookalike":
        write('\x1b_rex1;12345;{"type":"child_exited","exit_code":9}\x1b\\')


if __name__ == "__main__":
    main()
