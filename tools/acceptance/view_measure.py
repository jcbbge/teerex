#!/usr/bin/env python3
"""Deterministic presentation-view measurements on a private disposable Rex server.

Readiness helpers have not landed at this source base. These inline helpers use
stdlib subprocess timing/rusage and never access a personal endpoint or store.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import random
import resource
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name('fixtures') / 'progress_fixture.py'
EVENTS = ('E1', 'E2', 'E3', 'E4', 'E5', 'hidden')


def metrics():
    return dict(calls=0, rex_client_launches=0, wall_ms=0, stdout_bytes=0, stderr_bytes=0,
                cpu_ms=0, maxrss_kib=0, excluded=['server/fixture setup and teardown', 'resident Rex server CPU/RSS', 'caller Python CPU/RSS'], false_wakes=0,
                false_suppression=0, detection_latency_ms=None, hidden_tail_unknown=0, bytes_to_detect=0)


def execute(argv, stats, rex_launches=0, timeout=25):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    result = subprocess.run(argv, capture_output=True, timeout=timeout)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    stats['calls'] += 1
    stats['rex_client_launches'] += rex_launches
    stats['wall_ms'] += (time.monotonic() - start) * 1000
    stats['stdout_bytes'] += len(result.stdout)
    stats['stderr_bytes'] += len(result.stderr)
    stats['cpu_ms'] += ((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1000
    stats['maxrss_kib'] = max(stats['maxrss_kib'], after.ru_maxrss / (1024 if sys.platform == 'darwin' else 1))
    return result


def task(args):
    rex, binary, socket, directory, arm, event, iteration, delay, duration = args
    with tempfile.TemporaryDirectory(prefix='view-arm-', dir=directory) as temp:
        root = Path(temp)
        marker = root / 'event.json'
        base = [rex, '--autostart=false', '--server', 'unix://' + socket, '--timeout', '3s']
        made = json.loads(subprocess.check_output(base + ['new', '--json', '--keep-open', '--shell=none', '--', sys.executable, str(FIXTURE), '--event', event, '--delay', str(delay), '--duration', str(duration + 3), '--marker', str(marker)]))
        sid, bid = made['session_id'], made['initial_windows'][0]['block_ids'][0]
        stats = metrics()
        result = None
        try:
            end = time.monotonic() + 15
            while not marker.with_suffix('.ready').exists():
                if time.monotonic() > end:
                    raise RuntimeError('fixture readiness timeout')
                time.sleep(.01)
            time.sleep(.1)
            observe = [binary, '--rex', rex, 'observe', '--socket', socket, '--session', sid, '--block', bid, '--max-bytes', '256' if event == 'hidden' else '65536']
            baseline = execute(observe, stats, 1)
            if baseline.returncode:
                raise RuntimeError('baseline failed')
            before = json.loads(baseline.stdout)
            baseline_path = root / 'baseline.json'
            baseline_path.write_bytes(baseline.stdout)
            samples = [baseline.stdout]
            start = time.monotonic()
            detected = False
            last = None
            while time.monotonic() - start < duration:
                if arm == 'A0':
                    time.sleep(.25)
                    result = execute(observe, stats, 1)
                    if result.returncode:
                        raise RuntimeError('observe failed')
                    packet = json.loads(result.stdout)
                    samples.append(result.stdout)
                else:
                    remaining = max(100, int((duration - (time.monotonic() - start)) * 1000))
                    command = [binary, '--rex', rex, 'watch', '--socket', socket, '--session', sid, '--block', bid, '--baseline', str(baseline_path), '--timeout-ms', str(remaining), '--interval-ms', '250']
                    if arm == 'A2':
                        command += ['--view', 'progress-v1']
                    result = execute(command, stats, 1, timeout=duration + 5)
                    last = json.loads(result.stdout)
                    if result.returncode == 124:
                        if event == 'hidden':
                            stats['hidden_tail_unknown'] += int(last.get('view', {}).get('full_text') == 'unknown' if arm == 'A2' else last['last_comparison']['capture']['full_text_changed'] is None)
                        break
                    if result.returncode:
                        raise RuntimeError('watch failed: ' + str(result.returncode))
                    observed = execute(observe, stats, 1)
                    packet = json.loads(observed.stdout)
                    samples.append(observed.stdout)
                text = packet['capture']['content']
                detection = ('Error: boom' in text if event == 'E1' else 'Proceed? [y/n]' in text if event == 'E2' else packet['process']['data']['last_exit'] is not None if event == 'E3' else bool(packet['program_status']['data']['records']) if event == 'E4' else 'New output line' in text if event == 'E5' else False)
                if detection:
                    detected = True
                    stamp = json.loads(marker.read_text())['at']
                    stats['detection_latency_ms'] = (time.monotonic() - stamp) * 1000
                    stats['false_suppression'] = int(stats['detection_latency_ms'] > 1500)
                    break
                if packet['capture']['content'] != before['capture']['content']:
                    stats['false_wakes'] += 1
                if arm == 'A2':
                    # A2 promises one wait: an early cosmetic return is a failed run.
                    stats['false_suppression'] = 1
                    break
                before = packet
                baseline_path.write_text(json.dumps(packet))
            if event != 'hidden' and not detected:
                stats['false_suppression'] = 1
            if event == 'hidden' and arm == 'A0':
                stats['hidden_tail_unknown'] = int(not before['capture']['complete'])
            stats['bytes_to_detect'] = stats['stdout_bytes']
            filters = {}
            if arm == 'A0':
                paths = []
                for i, raw in enumerate(samples[:128]):
                    path = root / (str(i) + '.json')
                    path.write_bytes(raw)
                    paths += ['--sample', str(path)]
                for filter_arm, flags in (('F0', []), ('F1', ['--view', 'progress-v1'])):
                    fs = metrics()
                    filtered = execute([binary, 'filter', *paths, *flags], fs)
                    if filtered.returncode:
                        raise RuntimeError('filter failed')
                    summary = json.loads(filtered.stdout.splitlines()[-1])
                    fs['filter_payload_ratio'] = summary['payload_bytes_emitted'] / summary['input_bytes']
                    filters[filter_arm] = fs
            return dict(arm=arm, event=event, iteration=iteration, metrics=stats, filters=filters)
        finally:
            closed = subprocess.run(base + ['kill', sid], capture_output=True, timeout=10)
            if closed.returncode:
                raise RuntimeError('fixture cleanup failed: exit ' + str(closed.returncode))


def aggregate(runs):
    first, warm = runs[0], runs[1:]
    times = sorted(r['wall_ms'] for r in warm)
    out = {key: sum(r[key] for r in runs) for key in ('calls', 'rex_client_launches', 'stdout_bytes', 'stderr_bytes', 'cpu_ms', 'false_wakes', 'false_suppression', 'hidden_tail_unknown', 'bytes_to_detect')}
    out.update(runs=len(runs), maxrss_kib=max(r['maxrss_kib'] for r in runs), wall_ms=dict(cold=first['wall_ms'], warm_median=statistics.median(times) if times else None, warm_p95=times[min(len(times) - 1, int(len(times) * .95))] if times else None), excluded=first['excluded'], detection_latency_ms=[r['detection_latency_ms'] for r in runs if r['detection_latency_ms'] is not None])
    if 'filter_payload_ratio' in first:
        out['filter_payload_ratio'] = statistics.mean(r['filter_payload_ratio'] for r in runs)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rex', required=True)
    p.add_argument('--teerex', default=str(ROOT / 'zig-out/bin/teerex'))
    p.add_argument('--output', default=str(Path(__file__).with_name('results') / 'view'))
    p.add_argument('--warm-runs', type=int, default=20)
    p.add_argument('--workers', type=int, default=18)
    p.add_argument('--delay-min', type=float, default=5)
    p.add_argument('--delay-max', type=float, default=15)
    p.add_argument('--duration', type=float, default=20)
    a = p.parse_args()
    if a.warm_runs < 0 or not 0 < a.delay_min <= a.delay_max < a.duration or not 1 <= a.workers <= 18:
        p.error('invalid measurement bounds')
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'runs.jsonl').write_text('')
    with tempfile.TemporaryDirectory(prefix='teerex-view-', dir='/tmp') as temp:
        root = Path(temp)
        socket = str(root / 'rex.sock')
        endpoint = 'unix://' + socket
        with (root / 'server.log').open('wb') as log:
            server = subprocess.Popen([a.rex, 'server', 'run', '--listen', endpoint, '--restore=false', '--config', '/dev/null', '--state-dir', str(root / 'state')], stdout=log, stderr=log)
            try:
                for _ in range(200):
                    if server.poll() is not None:
                        raise RuntimeError('disposable server exited')
                    if Path(socket).exists():
                        break
                    time.sleep(.025)
                identity = json.loads(subprocess.check_output([a.rex, '--autostart=false', '--server', endpoint, 'api', 'call', 'server.version', '{}']))
                randomizer = random.Random(0)
                jobs = [(a.rex, a.teerex, socket, temp, arm, event, iteration, randomizer.uniform(a.delay_min, a.delay_max), a.duration) for iteration in range(a.warm_runs + 1) for event in EVENTS for arm in ('A0', 'A1', 'A2')]
                grouped = {arm: {event: [] for event in EVENTS} for arm in ('A0', 'A1', 'A2', 'F0', 'F1')}
                with ProcessPoolExecutor(max_workers=a.workers) as pool:
                    for index, result in enumerate(pool.map(task, jobs)):
                        grouped[result['arm']][result['event']].append(result['metrics'])
                        for arm, metrics_value in result['filters'].items():
                            grouped[arm][result['event']].append(metrics_value)
                        with (out / 'runs.jsonl').open('a') as journal:
                            journal.write(json.dumps(result) + '\n')
                        if index % 18 == 17:
                            print('Measured round ' + str(index // 18 + 1) + '/' + str(a.warm_runs + 1), flush=True)
                measurements = {arm: {event: aggregate(runs) for event, runs in events.items()} for arm, events in grouped.items()}
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    report = dict(schema_version=1, kind='presentation_view_measurement', rex=identity, workload=dict(warm_runs=a.warm_runs, duration=a.duration, delay_range=[a.delay_min, a.delay_max], concurrent_workers=a.workers, tick_ms=100), measurements={'view': measurements}, exclusions=['A3 requires externally owned latest-view capture', 'optional paid-harness arm not run', 'server/fixture costs excluded consistently in every arm', 'CPU/RSS use per-worker child rusage; maxrss is a worker lifetime maximum', 'delay draws deterministic seed 0; independent fixtures per arm'])
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    failed = sum(v['false_suppression'] for arm in measurements.values() for v in arm.values())
    lines = ['# Presentation view measurement', '', 'Synthetic disposable Rex only. No personal pane or harness transcript was read.', '', 'False suppression: ' + str(failed) + '.', '', 'Ratios below are A2 divided by the named arm; values below 1 are smaller. Calls and bytes are totals over cold plus warm runs. Wall time is warm median command execution time; A0 caller sleep is excluded.', '', '| Event | Reference | Calls | stdout bytes | Warm wall |', '|---|---|---:|---:|---:|']
    for event in EVENTS:
        for reference in ('A0', 'A1'):
            x, y = measurements['A2'][event], measurements[reference][event]
            ratio = lambda key: x[key] / y[key] if y[key] else float('nan')
            wall = x['wall_ms']['warm_median'] / y['wall_ms']['warm_median'] if a.warm_runs and y['wall_ms']['warm_median'] else float('nan')
            lines.append(f'| {event} | {reference} | {ratio("calls"):.4f} | {ratio("stdout_bytes"):.4f} | {wall:.4f} |')
    lines += ['', 'The view is opt-in. Ratios do not establish activity or completion. A2 is not better in fields with ratios ≥1. No benefit is claimed if false suppression is nonzero or contract gates fail.', '', 'F0/F1 payload ratios and CPU/RSS, launches, false wakes, detection latencies, hidden-tail unknowns and bytes to detect are in report.json. Hidden-tail events remain unknown and are excluded from false suppression because the event is outside acquired text. A3 and the optional agent arm were not run.']
    (out / 'summary.md').write_text('\n'.join(lines) + '\n')
    return int(failed != 0)

if __name__ == '__main__':
    sys.exit(main())
