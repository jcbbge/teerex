"""Decision contracts against a disposable API13 Rex, private stores and host config."""
import importlib.util
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('send_fixture', ROOT / 'items/send/test_send.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
BIN = fixtures.BIN


class DecideTest(unittest.TestCase):
    setUpClass = classmethod(fixtures.SendTest.setUpClass.__func__)
    stop_server = classmethod(fixtures.SendTest.stop_server.__func__)
    rex_json = classmethod(fixtures.SendTest.rex_json.__func__)
    rpc = classmethod(fixtures.SendTest.rpc.__func__)
    fixture = fixtures.SendTest.fixture
    received = fixtures.SendTest.received
    pasted = staticmethod(fixtures.SendTest.pasted)

    def setUp(self):
        fixtures.SendTest.setUp(self)
        self.env.update(TEEREX_DECISIONS_DIR=str(self.work / 'decisions'), TEEREX_CALL_LOG_DIR=str(self.work / 'logs'))
        self.asker, self.raw = self.fixture()
        self.env.update(REX_SESSION=self.asker[0], REX_BLOCK=self.asker[1])

    def cli(self, *args, code=0, env=None):
        result = subprocess.run([BIN, 'decide', *map(str, args)], env=env or self.env, capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def open(self, ident='choose', *extra, code=0):
        return self.cli('open', '--id', ident, '--title', 'Choose timing', '--ask', 'Ship now?',
                        '--option', 'go::Ship now', '--option', 'hold::Wait', '--default', 'hold', *extra, code=code)

    def row(self, ident='choose'):
        return Path(self.env['TEEREX_DECISIONS_DIR']) / (ident + '.json')

    def test_open_list_private_default_and_no_pane_input(self):
        before = self.raw.read_bytes()
        packet = self.open()
        self.assertFalse(packet['terminal_input_attempted'])
        self.assertEqual(packet['default_policy'], 'proceed_unless_vetoed')
        rows = self.cli('list', '--json')['decisions']
        self.assertEqual(rows[0]['asker']['session'], self.asker[0])
        self.assertEqual(rows[0]['default'], 'hold')
        self.assertEqual(self.row().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.row().parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.raw.read_bytes(), before)
        self.open(code=1)

    def test_answer_only_reaches_asker_and_closes(self):
        resolver, resolver_raw = self.fixture()
        self.open()
        env = dict(self.env, REX_SESSION=resolver[0], REX_BLOCK=resolver[1])
        before = resolver_raw.read_bytes()
        packet = self.cli('answer', '--id', 'choose', '--option', 'go', '--socket', self.socket, env=env)
        self.assertEqual(packet['outcome'], 'answered')
        self.received(self.raw, self.pasted(b'DECISION [choose] Josh chose: Ship now', 'Josh'))
        self.assertEqual(resolver_raw.read_bytes(), before)
        self.assertEqual(self.cli('list')['decisions'], [])
        self.cli('answer', '--id', 'choose', '--default', '--socket', self.socket, code=1)

    def test_accept_default(self):
        self.open()
        packet = self.cli('answer', '--id', 'choose', '--default', '--socket', self.socket)
        self.assertEqual(packet['option'], 'hold')
        self.received(self.raw, self.pasted(b'DECISION [choose] Josh chose: Wait', 'Josh'))

    def test_expiry_is_default_stood_without_delivery(self):
        self.open('old', '--expires-in', '1s')
        time.sleep(1.05)
        self.assertEqual(self.cli('list')['decisions'], [])
        self.assertEqual(json.loads(self.row('old').read_text())['state'], 'default_stood')
        self.assertEqual(self.cli('answer', '--id', 'old', '--option', 'go')['outcome'], 'default_stood')
        self.assertEqual(self.raw.read_bytes(), b'')

    def test_invalid_boundaries_and_symlinks(self):
        for flags in (('--default', 'missing'), ('--expires-in', '0h'), ('--expires-in', '31d'),
                      ('--option', 'go::Duplicate'), ('--asker-block', 'other'), ('--title', '\x1b[31mBad')):
            self.open('invalid', *flags, code=1)
        self.open()
        self.cli('answer', '--id', 'choose', '--option', 'missing', code=1)
        self.assertFalse(json.loads(self.row().read_text()).get('delivery_attempted'))
        self.row().chmod(0o644)
        self.cli('list', code=1)
        self.row().chmod(0o600)
        outside = self.work / 'outside'
        self.row().rename(outside)
        self.row().symlink_to(outside)
        self.cli('list', code=1)
        self.assertEqual(self.raw.read_bytes(), b'')

    def test_failed_delivery_is_not_retried(self):
        self.open()
        self.cli('answer', '--id', 'choose', '--default', '--socket', self.work / 'missing.sock', code=1)
        packet = self.cli('answer', '--id', 'choose', '--default', '--socket', self.socket, code=1)
        self.assertIn('delivery_already_attempted', packet['reason'])
        self.assertEqual(self.raw.read_bytes(), b'')

    def host_config(self):
        hosts = {}
        for name in ('hive', 'm5'):
            home = self.work / name
            home.mkdir()
            hosts[name] = dict(host_id=name, transport='local', home=str(home), platform='macos-arm64' if sys.platform == 'darwin' else 'linux-x86_64',
                               socket=str(self.socket), rex=self.rex, teerex=BIN, store=str(home / 'boards'))
        # A second private Rex proves named-host answer delivery cannot fall back
        # to the first host's server, even though both stores are on this machine.
        socket = self.work / 'm5.sock'
        log = (self.work / 'm5.log').open('w')
        self.addCleanup(log.close)
        process = subprocess.Popen([self.rex, 'server', 'run', '--listen', 'unix://' + str(socket),
            '--restore=false', '--config', '/dev/null', '--state-dir', str(self.work / 'm5-state')], stdout=log, stderr=log)
        def stop():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        self.addCleanup(stop)
        for _ in range(100):
            if socket.exists():
                break
            if process.poll() is not None:
                self.fail('second disposable server exited')
            time.sleep(.05)
        hosts['m5']['socket'] = str(socket)
        # Create an asker on that server, using the exact same raw-input fixture.
        original = self.base
        self.base = [self.rex, '--autostart=false', '--server', 'unix://' + str(socket), '--timeout', '3s']
        # fixture uses the class-level rex_json, so select this instance explicitly.
        def rex_json(*args):
            return json.loads(subprocess.check_output(self.base + list(args), text=True, timeout=10))
        self.rex_json = rex_json
        self.rpc = lambda method, args: rex_json('api', 'call', method, json.dumps(args))
        self.remote_asker, self.remote_raw = self.fixture()
        self.base = original
        del self.rex_json
        del self.rpc
        config = self.work / 'hosts.json'
        config.write_text(json.dumps(dict(schema_version=1, hosts=hosts)))
        return config, hosts

    def test_cross_host_list_answer_and_partial_failure(self):
        config, hosts = self.host_config()
        for name in hosts:
            self.cli('open', '--id', name, '--title', name, '--ask', 'Proceed?', '--option', 'yes::Yes', '--option', 'no::No',
                     '--default', 'no', '--store', hosts[name]['home'] + '/.local/state/teerex/decisions',
                     '--asker-session', (self.remote_asker if name == 'm5' else self.asker)[0],
                     '--asker-block', (self.remote_asker if name == 'm5' else self.asker)[1])
        rows = self.cli('list', '--config', config, '--hosts', 'hive,m5', '--json')
        self.assertTrue(rows['complete'])
        self.assertEqual([r['host'] for r in rows['decisions']], ['hive', 'm5'])
        self.assertEqual(self.cli('answer', '--config', config, '--host', 'm5', '--id', 'm5', '--default')['outcome'], 'answered')
        self.received(self.remote_raw, self.pasted(b'DECISION [m5] Josh chose: No', 'Josh'))
        self.assertEqual(self.raw.read_bytes(), b'')
        hosts['m5']['teerex'] = str(self.work / 'absent')
        config.write_text(json.dumps(dict(schema_version=1, hosts=hosts)))
        packet = self.cli('list', '--config', config, '--hosts', 'hive,m5', '--json', code=1)
        self.assertFalse(packet['complete'])
        self.assertEqual([s['outcome'] for s in packet['sources']], ['observed', 'unknown'])
        self.assertEqual([r['host'] for r in packet['decisions']], ['hive'])

    def test_cross_host_ssh_failure_is_unknown_without_local_fallback(self):
        config, hosts = self.host_config()
        known = self.work / 'known_hosts'
        identity = self.work / 'fixture_identity'
        known.write_text('')
        identity.write_text('not a credential')
        identity.chmod(0o600)
        # Reserve an unused loopback port without listening: no personal SSH endpoint.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            hosts['m5'].update(transport='ssh', address='fixture@127.0.0.1', port=reservation.getsockname()[1],
                               known_hosts=str(known), identity_file=str(identity))
            config.write_text(json.dumps(dict(schema_version=1, hosts=hosts)))
            self.open()
            packet = self.cli('list', '--config', config, '--hosts', 'hive,m5', '--json', code=1)
        self.assertFalse(packet['complete'])
        self.assertEqual(packet['decisions'], [])  # Local default store was not substituted.
        self.assertEqual([s['outcome'] for s in packet['sources']], ['observed', 'unknown'])
        self.assertEqual(self.raw.read_bytes(), b'')

    def test_ask_does_not_mark_question_blocked(self):
        self.rpc('session.set_block_label', dict(session_id=self.asker[0], block_id=self.asker[1], label='seat'))
        card = self.work / 'card.json'
        card.write_text(json.dumps(dict(id='question', title='Choose', ask='Continue?', context='fixture',
            options=[dict(label='Go', gain='Progress', lose='Time'), dict(label='Wait', gain='Time', lose='Delay')], recommend='Go')))
        packet = subprocess.run([BIN, 'ask', '--socket', str(self.socket), '--session', self.asker[0], '--block', self.asker[1],
                                 '--host', 'hive', '--from', 'worker', '--card-file', str(card)], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(packet.returncode, 0, packet.stdout + packet.stderr)
        records = self.rpc('com.superlogical.terminal.program_status', dict(session_id=self.asker[0], block_id=self.asker[1], args={}))['records']
        self.assertFalse(any(r.get('state') in ('blocked', 'error') for r in records))


if __name__ == '__main__':
    unittest.main()
