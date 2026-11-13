#!/usr/bin/env python3
"""Compare configured held commands on their hosts with finite board rows."""
import argparse
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


def source_rows(host):
    argv = host['held_command']
    if host['transport'] == 'ssh':
        argv = [*targets.ssh_argv(host), shlex.join(argv)]
    data = json.loads(subprocess.check_output(argv, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15))
    if data['schema'] != 1 or not isinstance(data['items'], list):
        raise ValueError('invalid source schema')
    return sorted(data['items'], key=lambda row: row['since'])


def differences(expected, section):
    errors = []
    if not section or section.get('available') is not True:
        return ['held work unavailable']
    actual = section['rows']
    want, got = [r['id'] for r in expected], [r['id'] for r in actual]
    if want != got: errors.append(f'ids/order: source={want} board={got}')
    for i, (a, b) in enumerate(zip(expected, actual)):
        for field in ('text', 'broken'):
            if a[field] != b[field]: errors.append(f'row {i} {field}: source={a[field]!r} board={b[field]!r}')
    if section['count'] != len(actual): errors.append(f'count: rows={len(actual)} header={section["count"]}')
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.path.expanduser('~/.config/teerex/hosts.json'))
    parser.add_argument('--teerex', default=os.environ.get('TEEREX_BIN', str(ROOT/'zig-out/bin/teerex')))
    args = parser.parse_args(argv)
    errors = []
    hosts = list(targets.load_config(args.config)['hosts'])
    try:
        result = subprocess.run([args.teerex, 'board', '--config', args.config, '--hosts', ','.join(hosts), '--json'], capture_output=True, text=True, timeout=90)
        snapshot = json.loads(result.stdout)
        if result.returncode: errors.append(f'board --json exited {result.returncode}')
        if snapshot.get('invalid'): errors.append('board rejected events')
        if [s['host'] for s in snapshot['hosts']] != hosts: errors.append('host coverage differs')
        for host in hosts:
            selected = targets.resolve_host(args.config, host)
            section = next(s for s in snapshot['hosts'] if s['host'] == host).get('held')
            if 'held_command' not in selected:
                if section is not None: errors.append(f'{host}: unexpected held section')
                continue
            try:
                rows = source_rows(selected)
                errors.extend(f'{host}: {e}' for e in differences(rows, section))
                print(f'{host}: source {len(rows)} rows; board {section["count"] if section else "unavailable"}')
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                errors.append(f'{host}: source read failed ({type(exc).__name__})')
    except (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.SubprocessError) as exc:
        errors.append(f'board snapshot failed ({type(exc).__name__})')
    for error in errors: print('DIFF '+error)
    print(f'{len(errors)} differences')
    return int(bool(errors))


if __name__ == '__main__': sys.exit(main())
