#!/usr/bin/env python3
"""Bounded query/reply probe; run inside the terminal being measured."""
import argparse
import json
import os
import select
import termios
import time
import tty

QUERIES = {
    'kitty': b'\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\\x1b[c',
    'kitty_placeholders': b'\x1b_Ga=q,i=32,e=T,U=1,C=1\x1b\\\x1b[c',
    'sixel': b'\x1b[c\x1b[?1;1;0S',
    'truecolor': b'\x1b[38:2::1:2:3m\x1bP$qm\x1b\\\x1b[0m',
    'synchronized_output': b'\x1b[?2026$p',
    'palette': b'\x1b]10;?\x1b\\\x1b]11;?\x1b\\' + b''.join(
        ('\x1b]4;%d;?\x1b\\' % n).encode() for n in range(16)),
}


def run(path):
    fd = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
    saved = termios.tcgetattr(fd)
    result = {'term': os.environ.get('TERM'), 'colorterm': os.environ.get('COLORTERM'), 'queries': {}}
    try:
        tty.setraw(fd)
        for name, query in QUERIES.items():
            os.write(fd, query)
            reply = b''
            deadline = time.monotonic() + .7
            while time.monotonic() < deadline:
                if not select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
                    break
                reply += os.read(fd, 8192)
            result['queries'][name] = {'sent': query.decode(), 'reply': reply.decode('utf-8', 'replace')}
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
        os.close(fd)
    with open(path, 'w') as out:
        json.dump(result, out, indent=2)
    print('Probe recorded; close this temporary pane.')
    # Keep the measured surface alive until its creator explicitly closes it.
    select.select([], [], [], 120)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    run(parser.parse_args().output)
