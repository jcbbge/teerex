"""seat panes only: private authority, disposable Rex, and actual board processes."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

from test_boards import RexBoardsTest as _Fixture, BIN, isolated_environment


class SeatPanesTest(unittest.TestCase):
    setUpClass = classmethod(_Fixture.setUpClass.__func__)

    def setUp(self):
        self.case = self.root / str(time.monotonic_ns())
        self.case.mkdir(mode=0o700)
        self.store = self.case / 'boards'
        self.store.mkdir(mode=0o700)
        self.tasks = self.case / 'tasks'
        self.tasks.mkdir()
        self.env = {k: v for k, v in isolated_environment().items()
                    if not k.startswith(('AGENT_', 'LC_AGENT_', 'REX_', 'LC_REX_', 'TEEREX_CALLER_', 'TEEREX_OPERATOR'))}
        self.env.update(XDG_STATE_HOME=str(self.case / 'state'), TEEREX_BOARDS_STORE=str(self.store))
        self.sid = self.call('surfaces', 'session', 'ensure', '--socket', str(self.socket), '--label', 'pn-seat-test')['resolved']['session_id']
        self.bid = self.call('surfaces', 'open', '--socket', str(self.socket), '--session', self.sid,
                             '--layout', 'tab', '--label', 'seat', '--', '/bin/sleep', '3600')['created']['block_id']
        self.env.update(AGENT_SESSION=self.sid, AGENT_PANE=self.bid, AGENT_NAME='disposable-seat')
        self.call('seat', 'register', '--store', str(self.store), '--host', 'fixture', '--socket', str(self.socket),
                  '--session', self.sid, '--block', self.bid, '--owner', 'test')
        self.config = self.case / 'hosts.json'
        host = dict(host_id='fixture', transport='local', platform='macos-arm64' if sys.platform == 'darwin' else 'linux-x86_64',
                    home=str(self.case), socket=str(self.socket), rex=self.rex, teerex=BIN, store=str(self.store))
        self.config.write_text(json.dumps(dict(schema_version=1, hosts=dict(fixture=host))))
        # Teardown uses only this private server; server fixture reaps its panes.
        self.addCleanup(lambda: self.rpc('session.destroy', dict(session_id=self.sid)))

    def rpc(self, method, args):
        return json.loads(subprocess.check_output([*self.base, 'api', 'call', method, json.dumps(args)]))

    def call(self, *args, code=0, env=None):
        p = subprocess.run([BIN, '--rex', self.rex, *args], env=env or self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def panes(self, *extra, code=0, tasks=True, env=None):
        args = ['--config', str(self.config), '--host', 'fixture', 'seat', 'panes']
        if tasks:
            args += ['--tasks', str(self.tasks)]
        return self.call(*args, *extra, code=code, env=env)

    def blocks(self):
        return self.rpc('session.list_blocks', dict(session_id=self.sid))['blocks']

    def wait_board(self, bid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            p = self.rpc('com.superlogical.terminal.process', dict(session_id=self.sid, block_id=bid, args={}))
            if p.get('child') and p['child'].get('name', '').startswith('teerex'):
                return p
            time.sleep(.03)
        self.fail('board process did not start: ' + repr(p))

    def assert_layout(self, result):
        for name, bounds in [('tasks', (0.6, 0, 0.4, 0.6)), ('board', (0.6, 0.6, 0.4, 0.4))]:
            receipt = self.call('surfaces', 'inspect', '--socket', str(self.socket), '--session', self.sid,
                                '--pane', result['panes'][name]['block_id'])
            actual = receipt['actual']['rect']
            self.assertEqual(len(actual), 4, receipt)
            for a, b in zip(actual, bounds):
                self.assertAlmostEqual(a, b, places=4, msg=str(receipt))

    def test_lifecycle_layout_keep_exit_and_replace(self):
        first = self.panes()
        self.assertEqual([p['outcome'] for p in first['panes'].values()], ['opened', 'opened'])
        self.assert_layout(first)
        for p in first['panes'].values():
            self.wait_board(p['block_id'])
        second = self.panes()
        self.assertEqual([p['outcome'] for p in second['panes'].values()], ['kept', 'kept'])
        repaired = first
        for name, survivor in [('board', 'tasks'), ('tasks', 'board')]:
            dead = repaired['panes'][name]['block_id']
            process = self.wait_board(dead)
            os.kill(process['child']['pid'], signal.SIGTERM)
            deadline = time.monotonic() + 5
            while self.rpc('com.superlogical.terminal.process', dict(session_id=self.sid, block_id=dead, args={})).get('last_exit') is None:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.03)
            repaired = self.panes()
            self.assertEqual(repaired['panes'][name]['outcome'], 'reopened')
            self.assertEqual(repaired['panes'][survivor]['outcome'], 'kept')
            self.assert_layout(repaired)
            for p in repaired['panes'].values():
                self.wait_board(p['block_id'])
        replaced = self.panes('--replace')
        self.assertEqual([p['outcome'] for p in replaced['panes'].values()], ['reopened', 'reopened'])
        self.assert_layout(replaced)
        self.assertTrue({p['block_id'] for p in repaired['panes'].values()}.isdisjoint(
            {p['block_id'] for p in replaced['panes'].values()}))

    def test_running_wrong_program_replaced_and_operator_allowed(self):
        old = self.call('surfaces', 'open', '--socket', str(self.socket), '--session', self.sid,
                        '--layout', 'tiled', '--anchor', self.bid, '--label', 'board',
                        '--', '/bin/sleep', '3600')['created']['block_id']
        repaired = self.panes(tasks=False)
        self.assertEqual(repaired['panes']['board']['outcome'], 'reopened')
        self.assertNotEqual(repaired['panes']['board']['block_id'], old)
        import pane_authority
        command = [BIN, '--rex', self.rex, '--config', str(self.config), '--host', 'fixture',
                   'seat', 'panes', '--replace']
        # The human terminal is outside the seat and uses the same explicit
        # operator gate as ordinary surfaces commands.
        human = {k: v for k, v in self.env.items() if not k.startswith(('AGENT_', 'LC_AGENT_'))}
        p = pane_authority.terminal([*command, '--operator'], dict(human, TEEREX_OPERATOR='1'), text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        result = json.loads(p.stdout)
        self.assertEqual(result['panes']['board']['outcome'], 'reopened')
        self.assertNotEqual(result['panes']['board']['block_id'], repaired['panes']['board']['block_id'])

    def test_agent_bystander_and_stale_refuse_without_changes(self):
        before = self.blocks()
        for changes in [dict(AGENT_PANE='block:11111111-1111-1111-1111-111111111111'),
                        dict(TEEREX_CALLER_IDENTITY=json.dumps(dict(host='other-host', session_id=self.sid, block_id=self.bid)))]:
            refused = self.panes(code=1, env=dict(self.env, **changes))
            self.assertEqual(refused['failure_reason'], 'caller_is_not_live_registered_seat_or_operator')
            self.assertEqual(before, self.blocks())
        bystander = {k: v for k, v in self.env.items() if not k.startswith(('AGENT_', 'LC_AGENT_', 'REX_', 'LC_REX_'))}
        self.assertEqual(self.panes(code=1, env=bystander)['failure_reason'], 'caller_is_not_live_registered_seat_or_operator')
        self.assertEqual(before, self.blocks())
        state = json.loads((self.store / 'state.json').read_text())
        state['seats'][0]['target']['block_id'] = 'block:11111111-1111-1111-1111-111111111111'
        (self.store / 'state.json').write_text(json.dumps(state))
        self.assertEqual(self.panes(code=1)['failure_reason'], 'no_live_registered_seat')
        self.assertEqual(before, self.blocks())

    def test_missing_tasks_only_board_and_foreign_companion_refused(self):
        only = self.panes(tasks=False)
        self.assertTrue(only['tasks_skipped'])
        self.assertEqual(set(only['panes']), {'board'})
        # A renamed recorded creator simulates an existing companion from another
        # caller; guard must refuse replacing it, preserving that exact block.
        bid = only['panes']['board']['block_id']
        records = list((self.case / 'state/teerex/pane-creators').rglob('*.json'))
        for record in records:
            value = json.loads(record.read_text())
            if value['id'] == bid:
                value['spawner']['block_id'] = 'block:11111111-1111-1111-1111-111111111111'
                value['allowed'] = [value['spawner']]
                record.write_text(json.dumps(value))
        before = self.blocks()
        refused = self.panes('--replace', tasks=False, code=1)
        self.assertEqual(refused['panes']['board']['outcome'], 'refused')
        self.assertEqual(refused['panes']['board']['block_id'], bid)
        self.assertIn('registered_seat_tab_is_operator_only', json.dumps(refused))
        self.assertEqual(before, self.blocks())


if __name__ == '__main__':
    unittest.main()
