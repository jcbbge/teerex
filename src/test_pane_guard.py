"""Authority checks against disposable Rex and throwaway authority stores only."""
import base64
import importlib.util
import hashlib
import json
import os
import pty
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_surface_fixture', ROOT / 'items/surfaces/test_surfaces.py')
_fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_fixtures)


class GuardTest(_fixtures.SurfacesTest):
    @classmethod
    def setUpClass(cls):
        # A server inherited from a human shell must not lend its marker to workers.
        keys = ('TEEREX_OPERATOR', 'LC_TEEREX_OPERATOR', 'TEEREX_OPERATOR_ACTIVE', 'LC_TEEREX_OPERATOR_ACTIVE')
        saved = {key: os.environ.get(key) for key in keys}
        try:
            os.environ.update({key: '1' for key in keys})
            super().setUpClass()
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.store = self.work / 'boards'
        self.store.mkdir(mode=0o700)
        self.env = dict(os.environ, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get('PATH', ''),
                        REX_SERVER='unix:///tmp/poison.sock', REX_SESSION='session:poison',
                        REX_BLOCK='block:poison', REX_CLIENT='client:poison',
                        XDG_STATE_HOME=str(self.work / 'state'), AGENT_REGISTRY=str(self.work / 'registry'))
        self.env['TEEREX_BOARDS_STORE'] = str(self.store)
        self.env['TEEREX_CLUTCH_DIR'] = str(self.work / 'clutch')
        self.session = self.rpc('session.create', {'label': 'guard disposable'})['session_id']
        self.anchor = self.open('tab')['actual']['block_id']
        self.addCleanup(lambda: self.rpc('session.destroy', {'session_id': self.session}))
        self.env['REX_BLOCK'] = self.anchor
        self.env['REX_SESSION'] = self.session

    def register(self, block):
        target = dict(host='test', server='unix://' + str(self.socket), session_id=self.session, block_id=block)
        (self.store / 'state.json').write_text(json.dumps(dict(seats=[dict(target=target)])))

    def cli(self, *args, env=None):
        return subprocess.run([_fixtures.BIN, *args], env=env or self.env, capture_output=True, text=True, timeout=20)

    def control(self, op, pane, *args):
        return self.cli('surfaces', op, '--socket', str(self.socket), '--session', self.session, '--pane', pane, *args)

    def refused(self, result, reason):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        output = result.stdout + result.stderr
        try:
            output += base64.b64decode(json.loads(result.stdout).get('backend_stderr_base64', '')).decode()
        except (ValueError, TypeError):
            pass
        self.assertIn(reason, output)

    def test_seat_controls(self):
        neighbour = self.open('tiled', label='seat neighbour')['actual']['block_id']
        other = self.open('tab', label='other tab')['actual']['block_id']
        self.register(self.anchor)
        for pane in (self.anchor, neighbour):
            for op, extra in (('close', ()), ('rename', ('--label', 'changed')),
                              ('focus', ()), ('move', ('--anchor', other, '--focus', 'yes'))):
                with self.subTest(pane=pane, op=op):
                    self.refused(self.control(op, pane, *extra), 'registered_seat_tab')
        label = self.rpc('session.view', {'session_id': self.session})['windows'][0]['label']
        self.refused(self.control('close', label), 'registered_seat_tab')
        self.assertNotEqual(self.cli('surfaces', 'session', 'close', '--socket', str(self.socket), '--session', self.session).returncode, 0)
        self.refused(self.cli('clutch', 'take', '--socket', str(self.socket), '--session', self.session, '--pane', neighbour), 'registered_seat_tab')
        self.assertEqual({self.anchor, neighbour, other}, {b['block_id'] for b in self.rpc('session.list_blocks', {'session_id': self.session})['blocks']})

    def test_spawner_ownership(self):
        own = self.open('tab', label='owned pane')['actual']['block_id']
        self.assertEqual(self.control('rename', own, '--label', 'owned rename').returncode, 0)
        foreign_actor = self.open('tab', label='other agent')['actual']['block_id']
        self.env['REX_BLOCK'] = foreign_actor
        foreign = self.open('tab', label='foreign pane')['actual']['block_id']
        self.env['REX_BLOCK'] = self.anchor
        for op, extra in (('close', ()), ('rename', ('--label', 'stolen')),
                          ('move', ('--anchor', self.anchor, '--focus', 'yes'))):
            self.refused(self.control(op, foreign, *extra), 'recorded spawner: ' + self.session + ' ' + foreign_actor)
        self.assertEqual(self.control('close', own).returncode, 0)
        self.env['REX_BLOCK'] = foreign_actor
        self.assertEqual(self.control('close', foreign).returncode, 0)

    def test_supervisor_closes_viewer(self):
        worker = self.open('tab', label='worker')['actual']['block_id']
        viewer = self.open('tab', label='viewer')['actual']['block_id']
        self.remove_creator(viewer)
        registry = self.work / 'registry'
        registry.mkdir(mode=0o700)
        self.env['AGENT_REGISTRY'] = str(registry)
        target = dict(server='unix://' + str(self.socket), session_id=self.session, block_id=worker)
        starter = dict(session_id=self.session, block_id=self.anchor)
        (registry / ('agents-' + 'a' * 32 + '.json')).write_text(json.dumps(dict(
            target=target, starter=starter, scratch_pane_receipt=dict(outcome='created_and_verified', created=dict(block_id=viewer)))))
        self.env['REX_BLOCK'] = worker
        self.assertEqual(self.control('close', viewer).returncode, 0)

    def remove_creator(self, block):
        key = hashlib.sha256(('unix://' + os.path.realpath(self.socket)).encode()).hexdigest()
        (Path(self.env['XDG_STATE_HOME']) / 'teerex/pane-creators' / key / (block.replace(':', '-') + '.json')).unlink()

    def test_registry_only_managed_agent(self):
        worker = self.open('tab', label='pre-existing worker')['actual']['block_id']
        stranger = self.open('tab', label='stranger')['actual']['block_id']
        self.remove_creator(worker)
        registry = self.work / 'legacy-registry'
        registry.mkdir(mode=0o700)
        self.env['AGENT_REGISTRY'] = str(registry)
        target = dict(server='unix://' + str(self.socket), session_id=self.session, block_id=worker)
        starter = dict(session_id=self.session, block_id=self.anchor)
        (registry / ('agents-' + 'b' * 32 + '.json')).write_text(json.dumps(dict(target=target, starter=starter)))
        self.env['REX_BLOCK'] = stranger
        self.refused(self.control('close', worker), 'recorded spawner: ' + self.session + ' ' + self.anchor)
        self.env['REX_BLOCK'] = self.anchor
        self.assertEqual(self.control('close', worker).returncode, 0)

    def test_session_spawner(self):
        result = self.cli('surfaces', 'session', 'ensure', '--socket', str(self.socket), '--label', 'owned empty session')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        sid = json.loads(result.stdout)['resolved']['session_id']
        env = dict(self.env, REX_BLOCK='block:00000000-0000-0000-0000-000000000001')
        command = ('surfaces', 'session', 'close', '--socket', str(self.socket), '--session', sid)
        self.refused(self.cli(*command, env=env), 'recorded spawner: ' + self.session + ' ' + self.anchor)
        self.assertEqual(self.cli(*command).returncode, 0)

    def test_session_close_client_kind_decisions(self):
        # Simulate only client.list shapes: inventory, receipts, guard, destroy
        # and absence readback still run against the disposable Rex server.
        import pane_guard
        from unittest.mock import patch
        source = (ROOT / 'items/surfaces/surfaces.lua').read_text()
        for kinds in (['app'], ['app', 'app'], ['cli'], ['app', 'cli'],
                      ['agent'], ['other'], ['future'], [None]):
            for actor in ('creator', 'bystander', 'unrecorded', 'operator', 'seat', 'pane'):
                with self.subTest(kinds=kinds, actor=actor):
                    made = self.cli('surfaces', 'session', 'ensure', '--socket', str(self.socket),
                                    '--label', 'client decision ' + str(time.monotonic_ns()))
                    self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
                    sid = json.loads(made.stdout)['resolved']['session_id']
                    if actor == 'unrecorded':
                        self.remove_creator(sid)
                    if actor == 'pane':
                        opened = self.cli('surfaces', 'open', '--socket', str(self.socket),
                                          '--session', sid, '--layout', 'tab', '--label', 'present pane', '--', '/bin/sh', '-c', 'sleep 60')
                        self.assertEqual(opened.returncode, 0, opened.stdout + opened.stderr)
                    with patch.dict(os.environ, self.env, clear=True):
                        policy = pane_guard.snapshot('unix://' + str(self.socket))
                    policy['operator'] = actor == 'operator'
                    if actor == 'bystander':
                        policy['actor']['block_id'] = 'block:00000000-0000-0000-0000-000000000001'
                    if actor == 'seat':
                        policy['seats'] = [dict(session_id=sid)]
                    clients = [dict(client_id='client:fixture-' + str(n),
                                    info=dict(kind=kind)) if kind else dict(client_id='client:fixture-' + str(n))
                               for n, kind in enumerate(kinds)]
                    lua = "local native=rex.call; rex.call=function(m,p) if m=='client.list' then return rex.json.decode(" + json.dumps(json.dumps(dict(clients=clients))) + ") end return native(m,p) end\n"
                    lua += 'do local GUARD_DATA=' + json.dumps(json.dumps(policy)) + '\n' + pane_guard.LUA + '\nend\n'
                    lua += source + '\nlocal ok,r=pcall(surface,' + '{operation="session-close",session_id=' + json.dumps(sid) + '}); print(rex.json.encode({ok=ok,result=r}))'
                    result = subprocess.run(self.base + ['do', '-e', lua], env=self.env,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    packet = json.loads(result.stdout)
                    apps = all(kind == 'app' for kind in kinds)
                    expected = apps and actor in ('creator', 'operator')
                    present = sid in [v['session_id'] for v in self.rpc('session.list', {})['sessions']]
                    self.assertEqual(present, not expected)
                    if expected:
                        self.assertTrue(packet['ok'], packet)
                        self.assertEqual(packet['result']['outcome'], 'session_closed_and_absent')
                        self.assertTrue(packet['result']['session_absence_verified'])
                    else:
                        if actor == 'pane' or not apps:
                            self.assertTrue(packet['ok'], packet)
                            self.assertEqual(packet['result']['failure_reason'],
                                             'session_has_panes' if actor == 'pane' else 'session_has_attached_clients')
                            self.assertFalse(packet['result'].get('control_attempted', False))
                        else:
                            self.assertFalse(packet['ok'], packet)
                            reason = dict(bystander='recorded spawner: ' + self.session + ' ' + self.anchor,
                                          unrecorded='no_recorded_spawner', seat='registered_seat_session_cannot_be_closed')[actor]
                            self.assertIn(reason, packet['result'])
                        self.rpc('session.destroy', {'session_id': sid})

    def test_session_destroy_wire_guard_protects_seat(self):
        import pane_guard
        from unittest.mock import patch
        for operator in (False, True):
            policy = dict(operator=operator, seats=[dict(session_id=self.session)])
            with patch.object(pane_guard, 'snapshot', return_value=policy):
                with self.assertRaisesRegex(ValueError, 'registered_seat_session_cannot_be_closed'):
                    pane_guard.authorize('unused', 'session.destroy', dict(session_id=self.session),
                                         lambda *_: self.fail('seat destruction must refuse before RPC'))

    def test_session_close_operator_guards(self):
        authority = _fixtures.pane_authority
        args = [_fixtures.BIN, 'surfaces', 'session', 'close', '--socket', str(self.socket)]
        # Even an operator cannot close a session containing a pane.
        self.refused(authority.operator(args + ['--session', self.session], self.env,
                                       text=True, timeout=20), 'session_has_panes')
        sid = self.rpc('session.create', {'label': 'operator empty'})['session_id']
        # The real operator path may close an unowned empty session.
        result = authority.operator(args + ['--session', sid], self.env, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)['session_absence_verified'])
        sid = self.rpc('session.create', {'label': 'operator seat'})['session_id']
        self.addCleanup(lambda: self.rpc('session.destroy', {'session_id': sid}))
        target = dict(server='unix://' + str(self.socket), session_id=sid, block_id=self.anchor)
        (self.store / 'state.json').write_text(json.dumps(dict(seats=[dict(target=target)])))
        result = authority.operator(args + ['--session', sid], self.env, text=True, timeout=20)
        self.refused(result, 'registered_seat_session_cannot_be_closed')
        self.assertIn(sid, [v['session_id'] for v in self.rpc('session.list', {})['sessions']])
        # Real attached CLI clients remain protected in the operator path.
        (self.store / 'state.json').write_text(json.dumps(dict(seats=[])))
        client = subprocess.Popen(self.base + ['do', '--session', sid, '--for', '10m', '-e',
                                  "rex.on('session_changed',function() end)"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not self.rpc('client.list', dict(session_id=sid))['clients']:
                self.assertIsNone(client.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.03)
            result = authority.operator(args + ['--session', sid], self.env, text=True, timeout=20)
            self.refused(result, 'session_has_attached_clients')
            self.assertIsNone(client.poll())
        finally:
            client.terminate()
            client.wait(timeout=5)

    def test_operator_terminal(self):
        pane = self.open('tab', label='operator target')['actual']['block_id']
        self.register(pane)
        args = [_fixtures.BIN, 'surfaces', 'rename', '--operator', '--socket', str(self.socket),
                '--session', self.session, '--pane', pane, '--label', 'operator renamed']
        env = {k: v for k, v in self.env.items() if not k.startswith(('AGENT_', 'LC_AGENT_'))}
        env['TEEREX_OPERATOR'] = '1'
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=20)
        self.refused(result, 'interactive human terminal')
        master, slave = pty.openpty()
        try:
            result = subprocess.run(args, env=env, stdin=slave, stderr=slave, stdout=subprocess.PIPE, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout)
            env['REX_BLOCK'] = pane
            result = subprocess.run(args, env=env, stdin=slave, stderr=slave, stdout=subprocess.PIPE, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            env['REX_BLOCK'] = self.anchor
            env['AGENT_LAUNCH_ID'] = 'a' * 32
            result = subprocess.run(args, env=env, stdin=slave, stderr=slave, stdout=subprocess.PIPE, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
        finally:
            os.close(slave)
            os.close(master)

    def test_seat_message_guard(self):
        pane = self.open('tab', '/bin/sh', '-c', 'printf "\\n❯ "; exec cat', label='message target')['actual']['block_id']
        self.register(pane)
        message = self.work / 'message.txt'
        message.write_text('disposable guarded message')
        command = ('send', '--socket', str(self.socket), '--session', self.session, '--block', pane,
                   '--from', 'guard-test', '--message-file', str(message), '--draft-wait-ms', '3000', '--timeout-ms', '7000')
        result = self.cli(*command)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['outcome'], 'events_acknowledged')
        result = self.cli(*command, '--draft', 'ignore')
        self.assertNotEqual(result.returncode, 0)

    def test_inherited_registration_and_missing_spawner(self):
        pane = self.open('tab', label='ordinary owned pane')['actual']['block_id']
        target = dict(host='test', server='unix://' + str(self.socket), session_id=self.session,
                      block_id='block:00000000-0000-0000-0000-000000000002')
        (self.store / 'state.json').write_text(json.dumps(dict(seats=[dict(target=target, inherited_to=dict(target, block_id=self.anchor))])))
        self.assertEqual(self.control('rename', pane, '--label', 'still ordinary').returncode, 0)
        self.remove_creator(pane)
        result = self.control('close', pane)
        self.refused(result, 'no_recorded_spawner')
        self.assertEqual(json.loads(result.stdout)['failure_reason'], 'no_recorded_spawner')

    def test_tab_rename_and_suffix_resolution(self):
        neighbour = self.open('tiled', label='protected neighbour')['actual']['block_id']
        self.register(self.anchor)
        window = self.inspect(neighbour)['window_id']
        self.refused(self.cli('surfaces', 'rename', '--socket', str(self.socket), '--session', self.session,
                             '--window', window, '--label', 'changed tab'), 'registered_seat_tab')
        self.refused(self.control('close', neighbour[-12:]), 'registered_seat_tab')

    def test_spawn_receipt_and_operator_environment(self):
        proof = self.work / 'worker-environment.txt'
        script = ('test -z "$TEEREX_OPERATOR$LC_TEEREX_OPERATOR$TEEREX_OPERATOR_ACTIVE$LC_TEEREX_OPERATOR_ACTIVE" '
                  '&& printf cleaned > "$1"; sleep 60')
        result = self.cli('spawn', '--socket', str(self.socket), '--session', self.session,
                          '--name', 'guard spawned worker', '--cwd', str(self.work),
                          '--report-to-session', self.session, '--report-to-block', self.anchor,
                          '--', '/bin/sh', '-c', script, 'guard-test', str(proof))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pane = json.loads(result.stdout)['created']['block_id']
        # Observe actual child output completion, without touching any live pane.
        end = time.monotonic() + 3
        while not proof.exists() and time.monotonic() < end:
            time.sleep(.01)
        self.assertEqual(proof.read_text(), 'cleaned')
        self.assertEqual(self.control('close', pane).returncode, 0)

    def test_resize_raw_keys_and_relative_focus(self):
        neighbour = self.open('tiled', label='resize neighbour')['actual']['block_id']
        self.register(self.anchor)
        actual = self.inspect(self.anchor)
        endpoint = 'unix://' + str(self.socket)
        generated = subprocess.run([sys.executable, str(ROOT / 'src/pane_guard.py'), endpoint],
                                   env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        script = generated.stdout + '\nreturn rex.call(rex.args.method,rex.args.params)'
        cases = [
            ('session.resize_pane', dict(before_block_id=self.anchor, after_block_id=neighbour, direction='horizontal', ratio=.5)),
            ('session.resize_layer', dict(layer_id=actual['layer_id'], bounds=[0, 0, .5, .5])),
            ('session.zoom_block', dict(block_id=self.anchor)),
            ('session.close_window', dict(window_id=actual['window_id'])),
            ('session.close_layer', dict(layer_id=actual['layer_id'])),
            ('session.focus_next_window', {}),
            ('block.event', dict(block_id=self.anchor, event=dict(type='key', payload=dict(key='c', mods='ctrl')))),
        ]
        for method, params in cases:
            with self.subTest(method=method):
                params['session_id'] = self.session
                result = subprocess.run(self.base + ['do', '-e', script, '--args', json.dumps(dict(method=method, params=params)), '--json'],
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('registered_seat_tab', result.stderr)

    def test_socket_alias_protects_same_seat(self):
        self.register(self.anchor)
        alias = self.work / 'socket-alias'
        alias.symlink_to(self.socket)
        self.refused(self.cli('clutch', 'take', '--socket', str(alias), '--session', self.session, '--pane', self.anchor),
                     'registered_seat_tab')
        self.refused(self.cli('surfaces', 'focus', '--socket', str(alias), '--session', self.session, '--pane', self.anchor),
                     'registered_seat_tab')


if __name__ == '__main__':
    # This file reuses fixture helpers, never the unrelated surfaces suite.
    names = [n for n in GuardTest.__dict__ if n.startswith('test_')]
    suite = unittest.TestSuite(GuardTest(n) for n in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
