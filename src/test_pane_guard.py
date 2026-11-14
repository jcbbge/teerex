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
        key = hashlib.sha256(('unix://' + str(self.socket)).encode()).hexdigest()
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


if __name__ == '__main__':
    # This file reuses fixture helpers, never the unrelated surfaces suite.
    names = [n for n in GuardTest.__dict__ if n.startswith('test_')]
    suite = unittest.TestSuite(GuardTest(n) for n in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
