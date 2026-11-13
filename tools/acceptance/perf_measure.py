#!/usr/bin/env python3
"""Q12 CLI latency/RSS on an explicitly selected disposable local Rex server.

Cold means first invocation in a fresh fixture, not a flushed OS page cache.
Each verb has one cold and 20 warm runs by default. Setup/cleanup are excluded.
No real HOME, registry, calls log, input target or default Rex endpoint is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
WORKLOADS = ('observe', 'watch_to_change', 'send_ignore', 'send_guard', 'send_guard_saved_draft', 'surfaces_open', 'surfaces_close', 'run_visible_small', 'agents_prune_plan', 'boards_calls', 'cartridges_list')

class CommandFailed(RuntimeError):
    def __init__(self, row, stdout, stderr):
        self.row = row
        try: self.receipt = json.loads(stdout)
        except (ValueError, UnicodeError): self.receipt = {'non_json_stdout_bytes':len(stdout)}
        self.diagnostic = stderr.decode('utf-8', 'replace')[-1500:]
        super().__init__('measured command failed: exit ' + str(row['exit_code']))


def measured(argv, env, after_start=None, timeout=30):
    # wait4 gives this invocation's rusage; cumulative RUSAGE_CHILDREN maxima
    # would silently attribute an earlier heavy verb's RSS to later small verbs.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        start = time.monotonic()
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env, start_new_session=True)
        try:
            if after_start:
                after_start()
            while True:
                pid, status, usage = os.wait4(p.pid, os.WNOHANG)
                if pid:
                    p.returncode = os.waitstatus_to_exitcode(status)
                    break
                if time.monotonic() - start > timeout:
                    raise TimeoutError('measurement command deadline')
                time.sleep(.001)
        finally:
            if p.returncode is None:
                os.killpg(p.pid, signal.SIGKILL)
                _, status, usage = os.wait4(p.pid, 0)
                p.returncode = os.waitstatus_to_exitcode(status)
        elapsed = (time.monotonic() - start) * 1000
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(1048577), err.read(1048577)
        if len(stdout) > 1048576 or len(stderr) > 1048576:
            raise RuntimeError('measurement output bound exceeded')
        row = dict(wall_ms=elapsed, cpu_ms=(usage.ru_utime + usage.ru_stime) * 1000,
                   maxrss_kib=usage.ru_maxrss / (1024 if sys.platform == 'darwin' else 1),
                   stdout_bytes=len(stdout), stderr_bytes=len(stderr), exit_code=p.returncode)
        if p.returncode:
            raise CommandFailed(row, stdout, stderr)
        return row, json.loads(stdout)


def summarize(rows):
    warm = rows[1:]
    times = sorted(r['wall_ms'] for r in warm)
    return dict(cold_ms=rows[0]['wall_ms'], warm_p50_ms=statistics.median(times) if times else None,
                warm_p95_ms=times[max(0, (95 * len(times) + 99) // 100 - 1)] if times else None,
                maxrss_kib=max(r['maxrss_kib'] for r in rows),
                warm_maxrss_kib=max((r['maxrss_kib'] for r in warm), default=None),
                calls=len(rows), stdout_bytes=sum(r['stdout_bytes'] for r in rows),
                stderr_bytes=sum(r['stderr_bytes'] for r in rows), trials=rows)


class Fixture:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.socket = root / 'rex.sock'
        home = root / 'home'; home.mkdir(mode=0o700)
        self.env = dict(os.environ, HOME=str(home), TMPDIR=str(root), TEEREX_CALL_LOG_DIR=str(root / 'calls'),
                        TEEREX_CLUTCH_DIR=str(root / 'clutch'), AGENT_INBOX_DIR=str(root / 'inbox'))
        for key in ('REX_SERVER', 'REX_SESSION', 'REX_BLOCK', 'REX_CLIENT'):
            self.env.pop(key, None)
        self.env['PATH'] = str(Path(args.rex).parent) + os.pathsep + os.environ.get('PATH', '')
        self.base = [args.rex, '--autostart=false', '--server', 'unix://' + str(self.socket), '--timeout', '3s']
        self.cli = [args.teerex, '--rex', args.rex]
        self.log = (root / 'server.log').open('wb')
        self.server = subprocess.Popen([args.rex, 'server', 'run', '--listen', 'unix://' + str(self.socket), '--restore=false', '--config', '/dev/null', '--state-dir', str(root / 'rex-state')], env=self.env, stdout=self.log, stderr=self.log)
        try:
            for _ in range(400):
                if self.server.poll() is not None:
                    raise RuntimeError('disposable Rex exited during startup')
                if self.socket.exists(): break
                time.sleep(.025)
            else: raise RuntimeError('disposable Rex startup deadline')
            self.identity = self.rpc('server.version')
            if self.identity.get('api_revision') != 13:
                raise RuntimeError('Q12 fixtures require API13')
            self.sid, self.bid = self.new(['/bin/cat'])
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.server.poll() is None:
            self.server.terminate()
            try: self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill(); self.server.wait()
        self.log.close()

    def rpc(self, method, args=None):
        return json.loads(subprocess.check_output(self.base + ['api', 'call', method, json.dumps(args or {})], env=self.env, timeout=10))

    def new(self, argv):
        made = json.loads(subprocess.check_output(self.base + ['new', '--json', '--keep-open', '--shell=none', '--', *argv], env=self.env, timeout=15))
        return made['session_id'], made['initial_windows'][0]['block_ids'][0]

    def invoke(self, argv):
        p = subprocess.run(self.cli + argv, env=self.env, capture_output=True, timeout=30)
        if p.returncode:
            raise RuntimeError('fixture setup/cleanup command failed: ' + p.stderr.decode('utf-8', 'replace')[-1500:])
        return json.loads(p.stdout)

    def target(self, sid=None, bid=None):
        return ['--socket', str(self.socket), '--session', sid or self.sid, '--block', bid or self.bid]

    def pane(self):
        return ['--socket', str(self.socket), '--session', self.sid]

    def run(self):
        n = self.args.warm_runs + 1
        results, observations = {}, {}
        def collect(name, command, validate=lambda value: None, prepare=None, finish=None, cause=None):
            if self.args.workload and name not in self.args.workload: return
            rows = []
            for i in range(n):
                if prepare: prepare(i)
                argv, start_hook = command(i)
                try:
                    row, packet = measured(self.cli + argv, self.env, start_hook)
                except CommandFailed as exc:
                    self.args.output.mkdir(parents=True, exist_ok=True)
                    (self.args.output / 'failure.json').write_text(json.dumps(dict(machine=self.args.machine, workload=name, trial=i, metrics=exc.row, receipt=exc.receipt, diagnostic=exc.diagnostic), indent=2)+'\n')
                    raise
                validate(packet)
                if finish: finish(packet)
                rows.append(row)
            result = summarize(rows)
            result['fixture'] = cause or 'No intentional delay; resident disposable server.'
            result['finding_over_500ms_p50'] = result['warm_p50_ms'] is not None and result['warm_p50_ms'] > 500
            results[name] = result
            print(name + ': p50=' + ('unknown' if result['warm_p50_ms'] is None else str(round(result['warm_p50_ms'], 2))) + ' ms', flush=True)
        collect('observe', lambda i: (['observe', *self.target()], None))
        # File gate triggers one new line after 100ms. One baseline per trial is
        # setup, excluded; the measured watch uses its normal 250ms interval.
        gate = self.root / 'watch-gate'
        script = ("import os,sys,time; p=sys.argv[1]; old=''; print('BASE',flush=True); open(p+'.ready','w').write('ready')\n"
                  "while True:\n v=open(p).read() if os.path.exists(p) else ''\n if v!=old:\n  old=v; time.sleep(.1); print('EVENT '+v,flush=True); open(p+'.emitted','w').write(v)\n time.sleep(.005)\n")
        sid, bid = self.new([sys.executable, '-c', script, str(gate)])
        for _ in range(400):
            if gate.with_suffix('.ready').exists(): break
            time.sleep(.025)
        else: raise RuntimeError('watch fixture did not start')
        baseline = self.root / 'baseline.json'
        expected_watch = {}
        def trigger_watch(i):
            pending = gate.with_suffix('.next')
            pending.write_text(str(i))
            pending.replace(gate)
        def watch_prepare(i):
            expected_watch['index'] = str(i)
            baseline.write_text(json.dumps(self.invoke(['observe', *self.target(sid, bid)])))
        def watch_valid(packet):
            if packet['outcome'] != 'change_observed' or gate.with_suffix('.emitted').read_text() != expected_watch['index']:
                raise RuntimeError('watch did not detect the intended fixture event')
        collect('watch_to_change', lambda i: (['watch', *self.target(sid, bid), '--baseline', str(baseline), '--timeout-ms', '5000'], lambda: trigger_watch(i)), prepare=watch_prepare, validate=watch_valid,
                cause='Includes a controlled 100ms event delay and the default 250ms polling interval; baseline collection excluded.')
        message = self.root / 'message'; message.write_text('synthetic qualification message')
        for mode in ('ignore', 'guard'):
            collect('send_' + mode, lambda i, mode=mode: (['send', *self.target(), '--from', 'qualification', '--message-file', str(message), '--draft', mode], None),
                    cause='Empty rendered draft; guard adds its VT capture/parser; ignore skips it. ACK latency is not application consumption.')
        # Reuse the repository's synthetic prompt; seed input is test setup only.
        prompt_log = self.root / 'prompt-log'
        psid, pbid = self.new([sys.executable, str(ROOT / 'items/send/prompt_fixture.py'), str(prompt_log), '', 'clear'])
        for _ in range(400):
            if prompt_log.exists(): break
            time.sleep(.025)
        self.rpc('com.superlogical.terminal.write', dict(session_id=psid, block_id=pbid, args={'data': 'SYNTHETIC_SAVED_DRAFT'}))
        def verify_draft(packet):
            if not packet['draft']['detected'] or not packet['draft']['restore_verified']:
                raise RuntimeError('guard fixture did not exercise verified draft restoration')
            observations['draft_guard_receipt'] = {k: packet['draft'].get(k) for k in ('waited_ms', 'detected', 'restore_verified', 'bound_reached')}
        collect('send_guard_saved_draft', lambda i: (['send', *self.target(psid, pbid), '--from', 'qualification', '--message-file', str(message), '--draft', 'guard'], None), validate=verify_draft,
                cause='Intentional 1500ms draft quiet window plus 400ms post-submit restoration timer; verified restored synthetic draft. No suggestion/draft content retained in results.')
        def close_created(packet):
            bid = packet['created']['block_id']
            self.invoke(['surfaces', 'close', *self.pane(), '--pane', bid])
        collect('surfaces_open', lambda i: (['surfaces', 'open', *self.pane(), '--layout', 'tab', '--label', 'qualification-pane', '--', '/bin/cat'], None), finish=close_created)
        opened = {}
        def prepare_close(i):
            packet = self.invoke(['surfaces', 'open', *self.pane(), '--layout', 'tab', '--label', 'qualification-close', '--', '/bin/cat'])
            opened['bid'] = packet['created']['block_id']
        collect('surfaces_close', lambda i: (['surfaces', 'close', *self.pane(), '--pane', opened['bid']], None), prepare=prepare_close)
        true_executable = shutil.which('true')
        if true_executable is None: raise RuntimeError('system true executable unavailable')
        envfile = self.root / 'env.json'; envfile.write_text('{}'); envfile.chmod(0o600)
        def visible_valid(p):
            if not p['success'] or p['exit_report']['exit_code'] != 0: raise RuntimeError('visible small command lacked exit0/cleanup proof')
            observations['run_visible_cleanup'] = dict(outcome=p['outcome'], exit_code=p['exit_report']['exit_code'], block_absence_verified=p['cleanup']['block_absence_verified'])
        collect('run_visible_small', lambda i: (['run-visible', '--socket', str(self.socket), '--session', self.sid, '--cwd', str(self.root), '--env-file', str(envfile), '--stdin-file', '/dev/null', '--app', 'qualification', '--title', 'Small command', '--timeout-ms', '10000', '--', true_executable], None), validate=visible_valid,
                cause='Python foreground controller plus visible placement, identity/permit handshake, child exit and verified pane cleanup. No shell command work (system true executable selected on this host).')
        registry = self.root / 'registry'; registry.mkdir(mode=0o700)
        collect('agents_prune_plan', lambda i: (['agents', 'prune', '--registry', str(registry)], None), cause='Empty private registry; Python entry and plan/registry validation only, no live-agent retirement.')
        collect('boards_calls', lambda i: (['boards', 'calls', '--once', '--json', '--limit', '32'], None), cause='Reads only this fixture private call log, with up to 32 metadata entries; no message bodies or remote hosts.')
        collect('cartridges_list', lambda i: (['cartridges', 'list'], None), cause='Absent root under disposable HOME; no root created. Python manager startup and empty-state projection.')
        return results, observations


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rex', required=True)
    p.add_argument('--teerex', required=True)
    p.add_argument('--machine', required=True, help='explicit command-host label, recorded as supplied')
    p.add_argument('--source-revision', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--warm-runs', type=int, default=20)
    p.add_argument('--workload', action='append', choices=WORKLOADS, help='select explicit workloads; default is all')
    a = p.parse_args()
    if a.warm_runs < 0: p.error('warm-runs must be nonnegative')
    a.rex, a.teerex = str(Path(a.rex).resolve()), str(Path(a.teerex).resolve())
    with tempfile.TemporaryDirectory(prefix='teerex-perf-', dir='/tmp') as temp:
        fixture = Fixture(Path(temp).resolve(), a)
        try: results, observations = fixture.run()
        finally: fixture.close()
    a.output.mkdir(parents=True, exist_ok=True)
    report = dict(schema_version=1, kind='teerex_performance_measurement', machine=a.machine,
                  identity=dict(label_basis='explicit_caller_label', system=platform.system(), release=platform.release(), machine=platform.machine(), python=platform.python_version(), rex=fixture.identity),
                  source_revision=a.source_revision, binary_sha256=hashlib.sha256(Path(a.teerex).read_bytes()).hexdigest(),
                  driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), warm_runs=a.warm_runs,
                  qualified_warm_count=a.warm_runs >= 20, requested_workloads=a.workload or list(WORKLOADS), measurements=results, receipt_evidence=observations,
                  scope='Local command host against own API13 server; no personal state. Cold is first invocation, no OS cache flush.',
                  excluded=['server startup and resident server CPU/RSS', 'fixture preparation and teardown', 'SSH transport', 'caller Python CPU/RSS'],
                  rss_scope='Per invocation wait4 rusage, KiB; includes waited helper descendants, not resident Rex server or arbitrary detached processes.')
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Performance qualification: ' + a.machine, '', 'One cold plus ' + str(a.warm_runs) + ' warm invocations per workload; no OS cache flush. Native local execution, private API13 server and state. SSH/setup/teardown excluded.', '', '| Workload | Cold ms | Warm p50 ms | Warm p95 ms | Max RSS KiB | >500ms p50 |', '|---|---:|---:|---:|---:|---|']
    for name,r in results.items():
        fmt=lambda v: 'unknown' if v is None else f'{v:.2f}'
        lines.append('| ' + ' | '.join((name,fmt(r['cold_ms']),fmt(r['warm_p50_ms']),fmt(r['warm_p95_ms']),fmt(r['maxrss_kib']),'yes' if r['finding_over_500ms_p50'] else 'no')) + ' |')
    lines += ['', '## Findings', '']
    for name,r in sorted(results.items(), key=lambda x:x[1]['warm_p50_ms'] or 0, reverse=True):
        if r['finding_over_500ms_p50']:
            lines.append('- ' + name + ': ' + r['fixture'])
    lines += ['', 'These are the stated fixture workloads, not production-agent productivity, energy, throughput, large registries or remote RTT qualification. Full per-invocation measurements and exact build identity are in report.json.']
    (a.output / 'summary.md').write_text('\n'.join(lines) + '\n')

if __name__ == '__main__':
    main()
