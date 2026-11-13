"""Best-effort local tty report. The caller bounds this process independently of delivery."""
import json
import os
import re
import stat
import subprocess
import sys


def write_status(pid, report):
    try:
        if sys.platform == "linux":
            tty = os.readlink('/proc/%d/fd/1' % pid)
        elif sys.platform == "darwin":
            name = subprocess.check_output(['ps', '-p', str(pid), '-o', 'tty='], timeout=.1).decode().strip()
            if not re.fullmatch(r'ttys[0-9A-Za-z]+', name):
                return 'tty_unavailable'
            tty = '/dev/' + name
        else:
            return 'unsupported_platform'
        if not re.fullmatch(r'/dev/(pts/[0-9]+|ttys[0-9A-Za-z]+)', tty):
            return 'tty_unavailable'
        fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISCHR(os.fstat(fd).st_mode):
                return 'tty_unavailable'
            raw = report.encode()
            return 'written' if os.write(fd, raw) == len(raw) else 'short_write'
        finally:
            os.close(fd)
    except (OSError, subprocess.SubprocessError):
        return 'tty_unavailable'


print(json.dumps(write_status(int(sys.argv[1]), sys.argv[2])))
