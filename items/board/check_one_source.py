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
rex, socket = sys.argv[1:3]
profiles = pathlib.Path(sys.argv[3]) if len(sys.argv)>3 else pathlib.Path.home()/'.config/teerex/profiles.json'
def canonical(value):
    if not isinstance(value,str) or not value:return None
    try:return str(pathlib.Path(value).resolve()) if pathlib.Path(value).exists() else value
    except (OSError,RuntimeError):return value
executables=set()
try:
    configured=json.loads(profiles.read_text())['profiles']
    for profile in configured.values():
        if isinstance(profile,dict) and isinstance(profile.get('argv'),list) and profile['argv']:
            value=canonical(profile['argv'][0])
            if value:executables.add(value)
except (OSError,ValueError,UnicodeError,KeyError,TypeError,AttributeError):pass
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
        process=call('block','call','--session',sid,'--block',block,'process','{}')
        matched=any(canonical((process.get(role) or {}).get(field)) in executables
                    for role in ('child','foreground') for field in ('argv0','path'))
        if block not in launches and not managed and not matched:continue
        report=managed[-1] if managed else max(reports,key=lambda r:priority.get(r.get('state'),0),default={})
        rows.append(dict(block=block,session=sid,state=report.get('state','unknown')))
print(json.dumps(rows))
'''


def rex_rows(config, host, profiles=None):
    selected = targets.resolve_host(config, host)
    argv = ['python3', '-c', PROBE, selected['rex'], selected['socket']] + ([profiles] if profiles else [])
    if selected['transport'] == 'ssh':
        argv = [*targets.ssh_argv(selected), shlex.join(argv)]
    return json.loads(subprocess.check_output(argv, timeout=60, stderr=subprocess.PIPE))


def differences(expected, snapshot):
    """Return every identity/state/count discrepancy, including duplicates."""
    errors = []
    differing_blocks = set()
    actual = snapshot['rows']
    for label, rows in [('Rex', expected), ('board', actual)]:
        for block, count in Counter(r['block'] for r in rows).items():
            if count != 1:
                errors.append(f'{label} duplicate {block}: {count} rows')
                differing_blocks.add(block)
    want = {r['block']: r for r in expected}
    got = {r['block']: r for r in actual}
    for block in sorted(want.keys() | got.keys()):
        if block not in got:
            errors.append(f'missing board row {block}')
            differing_blocks.add(block)
        elif block not in want:
            errors.append(f'extra board row {block}')
            differing_blocks.add(block)
        else:
            for field in ('session', 'state'):
                if want[block][field] != got[block][field]:
                    errors.append(f'{block} {field}: Rex={want[block][field]} board={got[block][field]}')
                    differing_blocks.add(block)
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
    return errors, differing_blocks


def check_run(args, hosts):
    errors, summaries = [], []
    def read_rex(phase):
        result = {}
        for host in hosts:
            try: result[host] = rex_rows(args.config, host, args.profiles) if getattr(args,'profiles',None) else rex_rows(args.config, host)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                errors.append(f'{host}: Rex {phase} read failed ({type(exc).__name__})')
        return result
    before = read_rex('before')
    snapshot = None
    try:
        board = subprocess.run([args.teerex, 'board', '--config', args.config, '--hosts', ','.join(hosts), '--json'], capture_output=True, text=True, timeout=90)
        snapshot = json.loads(board.stdout)
        if board.returncode: errors.append(f'board --json exited {board.returncode}')
        if snapshot.get('invalid'): errors.append(f'board rejected {snapshot["invalid"]} events')
        actual_hosts = [s['host'] for s in snapshot['hosts']]
        if Counter(actual_hosts) != Counter(hosts): errors.append(f'host coverage: config={hosts} board={actual_hosts}')
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        errors.append(f'board snapshot failed ({type(exc).__name__})')
        snapshot = None
    after = read_rex('after')
    retry = False
    if snapshot is not None:
        for host_snapshot in snapshot['hosts']:
            host = host_snapshot['host']
            if host not in before or host not in after: continue
            old = {r['block']: (r['session'], r['state']) for r in before[host]}
            new = {r['block']: (r['session'], r['state']) for r in after[host]}
            in_flux = {block for block in old.keys() | new.keys() if old.get(block) != new.get(block)}
            for expected in (before[host], after[host]):
                found, blocks = differences(expected, host_snapshot)
                retry |= bool(blocks & in_flux)
                errors.extend(f'{host}: {error}' for error in found)
            summaries.append(f'{host}: Rex {len(before[host])} before / {len(after[host])} after agent panes; board {len(host_snapshot["rows"])} rows; header {host_snapshot["counts"]["total"]}')
    return list(dict.fromkeys(errors)), summaries, retry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.path.expanduser('~/.config/teerex/hosts.json'))
    parser.add_argument('--teerex', default=os.environ.get('TEEREX_BIN', str(ROOT/'zig-out/bin/teerex')))
    parser.add_argument('--profiles', help='absolute profiles file override on each host')
    args = parser.parse_args(argv)
    if args.profiles and not os.path.isabs(args.profiles):parser.error('absolute --profiles required')
    hosts = list(targets.load_config(args.config)['hosts'])
    for run in range(3):
        errors, summaries, retry = check_run(args, hosts)
        if not retry: break
    for summary in summaries: print(summary)
    print(f'{run} reruns')
    for error in errors: print('DIFF '+error)
    print(f'{len(errors)} differences')
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
