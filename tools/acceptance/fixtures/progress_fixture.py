#!/usr/bin/env python3
"""Synthetic progress shapes, markers and explicit asymmetric events; no harness."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--event', choices=('E1', 'E2', 'E3', 'E4', 'E5', 'hidden'), required=True)
    p.add_argument('--delay', type=float, required=True)
    p.add_argument('--duration', type=float, default=20)
    p.add_argument('--marker', required=True)
    a = p.parse_args()
    if a.event == 'hidden':
        print('PREFIX ' + 'x' * 4000)
    sys.stdout.write('⠋ Thinking (0s')
    sys.stdout.flush()
    marker = Path(a.marker)
    marker.with_suffix('.ready').write_text('ready')
    start = time.monotonic()
    emitted = False
    tick = 0
    while time.monotonic() - start < a.duration:
        if not emitted and time.monotonic() - start >= a.delay:
            marker.write_text(json.dumps({'event': a.event, 'at': time.monotonic()}))
            emitted = True
            if a.event == 'E3':
                return 3
            if a.event == 'E4':
                sys.stdout.write('\x1b]7501;state=done:app=teerex-view-measure\x1b\\')
            else:
                print('\n' + {'E1': 'Error: boom', 'E2': 'Proceed? [y/n]', 'E5': 'New output line', 'hidden': 'Error: hidden'}[a.event])
            sys.stdout.flush()
            # Event remains in capture; process identity does not change.
            time.sleep(max(0, a.duration - (time.monotonic() - start)))
            return 0
        sys.stdout.write('\r\x1b[K' + ('⠋' if tick % 2 else '⠙') + ' Thinking (' + str(tick) + 's')
        sys.stdout.flush()
        tick += 1
        time.sleep(.1)
    return 0

if __name__ == '__main__':
    sys.exit(main())
