"""Waiting contracts on two disposable API13 servers, with Lua action invocation."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get('TEEREX_BIN', Path(__file__).resolve().parents[2] / 'zig-out/bin/teerex')).resolve())
REX = os.environ.get('REX_BIN') or shutil.which('rex')


class WaitingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='twait-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hosts = {}
        for name in ('hive', 'm5'):
            socket = self.root / (name + '.sock')
            log = (self.root / (name + '.log')).open('w')
            self.addCleanup(log.close)
            process = subprocess.Popen([REX, 'server', 'run', '--listen', 'unix://' + str(socket),
                '--restore=false', '--config', '/dev/null', '--state-dir', str(self.root / name)], stdout=log, stderr=log)
            def stop(p=process):
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
            self.addCleanup(stop)
            for _ in range(100):
                if socket.exists(): break
                if process.poll() is not None: self.fail('server stopped')
                time.sleep(.05)
            self.hosts[name] = dict(host_id=name, transport='local', home=str(self.root),
                platform='macos-arm64' if sys.platform == 'darwin' else 'linux-x86_64',
                socket=str(socket), rex=REX, teerex=BIN, store=str(self.root / 'store'))
        self.config = self.root / 'hosts.json'
        self.config.write_text(json.dumps(dict(schema_version=1, hosts=self.hosts)))
        self.state = self.root / 'navigation.json'

    def rex(self, host, *args):
        return json.loads(subprocess.check_output([REX, '--autostart=false', '--server',
            'unix://' + self.hosts[host]['socket'], *args], text=True, timeout=15))

    def rpc(self, host, method, **args):
        return self.rex(host, 'api', 'call', method, json.dumps(args))

    def pane(self, host, status=None, session=None, registered=True):
        script = "import time; "
        if status:
            script += "print('\\x1b]7501;state=" + status + ":app=fixture\\x1b\\\\',flush=True); "
        script += 'time.sleep(120)'
        argv = [sys.executable, '-c', script]
        if session:
            made = self.rpc(host, 'session.new_block', session_id=session, flavor='com.superlogical.terminal.shell',
                options=dict(shell='none', command=argv, exit=dict(on_completion=False)))
            block = made['block_id']
        else:
            made = self.rex(host, 'new', '--json', '--shell=none', '--', *argv)
            session, block = made['session_id'], made['initial_windows'][0]['block_ids'][0]
        if registered:
            self.register(host, session, block)
        return session, block

    def register(self, host, session, block, name='worker'):
        root = self.root / '.local/state/teerex-agents'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        import uuid
        (root / ('agents-' + uuid.uuid4().hex + '.json')).write_text(json.dumps(dict(
            tracked=True, socket=self.hosts[host]['socket'], name=name,
            target=dict(session_id=session, block_id=block))))

    def invoke(self, operation='list', **flags):
        argv = [BIN, 'waiting', operation, '--config', str(self.config), '--state', str(self.state)]
        for key, value in flags.items():
            argv.append('--' + key.replace('_', '-'))
            if value is not True: argv.append(str(value))
        result = subprocess.run(argv, text=True, capture_output=True, timeout=40)
        return result, json.loads(result.stdout) if result.stdout else None

    def wait_rows(self, count):
        for _ in range(40):
            result, value = self.invoke()
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            if len(value['waiting']) == count: return value
            time.sleep(.05)
        self.fail(str(value))

    def test_public_help(self):
        result = subprocess.run([BIN, 'waiting', '--help'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith('usage: teerex waiting '), result.stdout)
        self.assertIn('--hosts', result.stdout)

    def test_timestamp_offsets_and_nanoseconds(self):
        spec = importlib.util.spec_from_file_location('waiting', Path(__file__).with_name('waiting.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.timestamp('2026-11-13T11:00:00.123456789-08:00'),
                         module.timestamp('2026-11-13T19:00:00.123456789Z'))
        self.assertLess(module.timestamp('2026-11-13T19:00:00.123456788Z'),
                        module.timestamp('2026-11-13T19:00:00.123456789Z'))

    def test_both_hosts_rank_visit_back_and_detached(self):
        hs, hb = self.pane('hive', 'done')
        ms, mb = self.pane('m5')
        _, detached = self.pane('m5', 'blocked', ms)
        rows = self.wait_rows(2)['waiting']
        self.assertEqual([p['host'] for p in rows], ['m5', 'hive'])
        self.assertTrue(rows[0]['detached'])
        result, value = self.invoke('next', focus=True, here_host='hive', here_session=hs, here_block=hb)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(value['moved'])
        blocks = self.rpc('m5', 'session.list_blocks', session_id=ms)['blocks']
        self.assertEqual(next(p for p in blocks if p['block_id'] == detached)['placement'], 'placed')
        self.assertEqual(len(self.invoke()[1]['waiting']), 1)
        result, value = self.invoke('back', focus=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(value['winner']['block_id'], hb)
        result, value = self.invoke('put-away', here_server='unfamiliar-app-label', here_session=ms, here_block=detached)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        result, _ = self.invoke('put-away', here_host='hive', here_session=hs, here_block=hb)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('last pane', result.stderr)

    def test_excludes_unregistered_and_protected_registered_panes(self):
        self.pane('hive', 'error', registered=False)
        sid, block = self.pane('hive', 'error', registered=False)
        self.register('hive', sid, block, name='seat')
        for label in ('seat', 'board', 'worker scratchpad', 'worker receipt'):
            sid, bid = self.pane('hive', 'done')
            self.rpc('hive', 'session.set_block_label', session_id=sid, block_id=bid, label=label)
        sid, bid = self.pane('hive', 'blocked')
        store = self.root / 'store'
        store.mkdir()
        (store / 'state.json').write_text(json.dumps(dict(seats=[dict(target=dict(
            server='unix://' + self.hosts['hive']['socket'], session_id=sid, block_id=bid))])))
        sid, expected = self.pane('hive', 'done')
        self.assertEqual([r['block_id'] for r in self.wait_rows(1)['waiting']], [expected])

    def test_back_does_not_offer_old_seat_or_unregistered_history(self):
        sid, block = self.pane('hive', 'done', registered=False)
        self.state.write_text(json.dumps(dict(visited={}, trail=[dict(host='hive', session_id=sid, block_id=block)])))
        result, value = self.invoke('back', focus=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIsNone(value['winner'])
        self.assertFalse(value['moved'])

    def test_partial_scan_refuses_to_focus(self):
        self.pane('hive', 'blocked')
        self.wait_rows(1)
        config = json.loads(self.config.read_text())
        config['hosts']['m5']['socket'] = str(self.root / 'missing.sock')
        self.config.write_text(json.dumps(config))
        result, value = self.invoke('next', focus=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(value['complete'])
        self.assertFalse(value['moved'])
        self.assertFalse(self.state.exists())

    def test_action_from_each_server_focuses_other_host(self):
        fixture = os.environ.get('WAITING_LUA')
        if not fixture:
            self.skipTest('WAITING_LUA selects rexconfig action fixture')
        source = Path(fixture).read_text()
        source = source.replace('(os.getenv("HOME") or "") .. "/.local/state/rexconfig"', json.dumps(str(self.root)))
        # Substitute only executable/config/state destinations in the scratch fixture.
        source = source.replace('home .. "/.local/opt/teerex-managed/current/teerex"', json.dumps(BIN))
        source = source.replace('home .. "/.config/teerex/hosts.json"', json.dumps(str(self.config)))
        source = source.replace('"--config", ' + json.dumps(str(self.config)),
            '"--state", ' + json.dumps(str(self.state)) + ', "--config", ' + json.dumps(str(self.config)))
        action = self.root / 'waiting.lua'
        action.write_text(source)
        for origin, destination in [('m5', 'hive'), ('hive', 'm5')]:
            sid, bid = self.pane(destination, 'blocked')
            self.wait_rows(1)
            result = self.rex(origin, 'do', str(action), '--action', 'next_waiting', '--json')
            self.assertTrue(result['moved'])
            self.assertEqual(result['winner']['host'], destination)
            self.assertEqual(result['winner']['block_id'], bid)
            view = self.rpc(destination, 'session.view', session_id=sid)
            active = next(w for w in view['windows'] if w['window_id'] == view['active_window_id'])
            self.assertEqual(active['focused_block_id'], bid)
            self.rpc(destination, 'session.destroy', session_id=sid)


if __name__ == '__main__':
    unittest.main()
