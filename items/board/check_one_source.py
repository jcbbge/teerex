#!/usr/bin/env python3
"""Compare Rex agent panes, finite board rows and header counts, read-only."""
import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('targets', ROOT / 'src/targets.py')
targets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(targets)

# Runs where the configured host lives, through the same named-host SSH transport
# as board feed. The probe deliberately reads Rex independently of feed.State.
PROBE = r'''
import json, pathlib, subprocess, sys
rex, socket = sys.argv[1:]
def call(*args):
    return json.loads(subprocess.check_output([rex, '--autostart=false', '--server', 'unix://'+socket, '--timeout', '2s', *args], timeout=3))
launches=set()
for path in (pathlib.Path.home()/'.local/state/teerex-agents').glob('*.json'):
    try:
        data=json.loads(path.read_text())
        for r in data.get('entries',[data]):
            if isinstance(r,dict):launches.add((r.get('target') or {}).get('block_id') or r.get('block_id'))
    except (OSError,ValueError,TypeError):pass
rows=[]
priority={'error':5,'blocked':4,'waiting':4,'working':3,'done':2,'idle':1}
for session in call('api','call','session.list','{}').get('sessions',[]):
    sid=session['session_id']
    panes=call('block','ls','--session',sid,'--json')
    for pane in panes.get('blocks',[]) if isinstance(panes,dict) else panes:
        block=pane['block_id']
        reports=call('block','call','--session',sid,'--block',block,'program_status','{}').get('records',[])
        managed=[r for r in reports if r.get('app')=='teerex-agent']
        if block not in launches and not managed:continue
        report=managed[-1] if managed else max(reports,key=lambda r:priority.get(r.get('state'),0),default={})
        rows.append(dict(block=block,session=sid,state=report.get('state','unknown')))
print(json.dumps(rows))
'''


def rex_rows(config, host):
    selected = targets.resolve_host(config, host)
    argv = ['python3', '-c', PROBE, selected['rex'], selected['socket']]
    if selected['transport'] == 'ssh':
        argv = [*targets.ssh_argv(selected), shlex.join(argv)]
    return json.loads(subprocess.check_output(argv, timeout=60, stderr=subprocess.PIPE))


def differences(expected, snapshot):
    """Return every identity/state/count discrepancy, including duplicates."""
    errors = []
    actual = snapshot['rows']
    for label, rows in [('Rex', expected), ('board', actual)]:
        for block, count in Counter(r['block'] for r in rows).items():
            if count != 1: errors.append(f'{label} duplicate {block}: {count} rows')
    want = {r['block']: r for r in expected}
    got = {r['block']: r for r in actual}
    for block in sorted(want.keys() | got.keys()):
        if block not in got: errors.append(f'missing board row {block}')
        elif block not in want: errors.append(f'extra board row {block}')
        else:
            for field in ('session', 'state'):
                if want[block][field] != got[block][field]:
                    errors.append(f'{block} {field}: Rex={want[block][field]} board={got[block][field]}')
    counts = dict.fromkeys(('working', 'waiting', 'blocked', 'error_count', 'idle', 'done', 'unknown'), 0)
    for row in actual:
        state = row['state']
        key = 'error_count' if state == 'error' else state if state in counts else 'unknown'
        counts[key] += 1
    counts['total'] = len(actual)
    for key in sorted(counts.keys() | snapshot['counts'].keys()):
        if counts.get(key) != snapshot['counts'].get(key):
            errors.append(f'header {key}: rows={counts.get(key)} header={snapshot["counts"].get(key)}')
    if snapshot.get('reachable') is not True: errors.append('board host is unavailable or unproven')
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.path.expanduser('~/.config/teerex/hosts.json'))
    parser.add_argument('--teerex', default=os.environ.get('TEEREX_BIN', str(ROOT/'zig-out/bin/teerex')))
    args = parser.parse_args(argv)
    hosts = list(targets.load_config(args.config)['hosts'])
    errors = []
    expected = {}
    for host in hosts:
        try: expected[host] = rex_rows(args.config, host)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            errors.append(f'{host}: Rex read failed ({type(exc).__name__})')
    try:
        board = subprocess.run([args.teerex, 'board', '--config', args.config, '--hosts', ','.join(hosts), '--json'], capture_output=True, text=True, timeout=90)
        snapshot = json.loads(board.stdout)
        if board.returncode: errors.append(f'board --json exited {board.returncode}')
        if snapshot.get('invalid'): errors.append(f'board rejected {snapshot["invalid"]} events')
        actual_hosts = [s['host'] for s in snapshot['hosts']]
        if Counter(actual_hosts) != Counter(hosts): errors.append(f'host coverage: config={hosts} board={actual_hosts}')
        for host_snapshot in snapshot['hosts']:
            host = host_snapshot['host']
            if host in expected:
                errors.extend(f'{host}: {error}' for error in differences(expected[host], host_snapshot))
                print(f'{host}: Rex {len(expected[host])} agent panes; board {len(host_snapshot["rows"])} rows; header {host_snapshot["counts"]["total"]}')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        errors.append(f'board snapshot failed ({type(exc).__name__})')
    for error in errors: print('DIFF '+error)
    print(f'{len(errors)} differences')
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
