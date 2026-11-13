"""In-pane byte player. Controller supplies numbered private local command files.

Only controller-authored files are used; terminal query replies are discarded.
"""
import base64
import json
import os
from pathlib import Path
import select
import sys
import time
import tty


def main(directory):
    tty.setraw(0)
    root = Path(directory)
    index = 0
    while True:
        command = root / (str(index) + ".json")
        if command.exists():
            value = json.loads(command.read_text())
            data = base64.b64decode(value["bytes"], validate=True)
            while data:
                count = os.write(1, data)
                data = data[count:]
            index += 1
        else:
            readable, _, _ = select.select([0], [], [], .005)
            if readable:
                os.read(0, 65536)


if __name__ == "__main__":
    main(sys.argv[1])
