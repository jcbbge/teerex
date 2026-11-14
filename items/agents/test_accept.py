"""Offline acceptance checks using disposable registries and boards only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/acceptance'))
from test_environment import isolated_environment
import pane_authority

BIN = str(Path(os.environ.get('TEEREX_BIN', 'zig-out/bin/teerex')).resolve())


class ReportAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='accept-report-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / 'agents'
        self.registry.mkdir(mode=0o700)
        self.boards = self.root / 'boards'
        self.boards.mkdir(mode=0o700)
        self.starter = self.address('1')
        self.worker = self.address('2')
        self.env = {k: v for k, v in isolated_environment().items()
                    if not k.startswith(('AGENT_', 'LC_AGENT_', 'TEEREX_OPERATOR', 'LC_TEEREX_OPERATOR'))}
        self.env.update(XDG_STATE_HOME=str(self.root), TEEREX_BOARDS_STORE=str(self.boards),
                        AGENT_REGISTRY=str(self.registry))
        self.actor(self.starter)
        self.path = self.record('a' * 32)

    def address(self, digit):
        suffix = digit * 8 + '-' + '-'.join([digit * 4] * 3) + '-' + digit * 12
        return dict(host='test', server='unix://' + str(self.root / 'unused.sock'),
                    session_id='session:' + suffix, block_id='block:' + suffix)

    def actor(self, address):
        self.env.update(REX_SESSION=address['session_id'], REX_BLOCK=address['block_id'],
                        LC_REX_SESSION=address['session_id'], LC_REX_BLOCK=address['block_id'])

    def record(self, launch_id, archived=False, kind='done', retired=True, starter=None):
        directory = self.registry
        if archived:
            directory = directory / 'archive' / launch_id
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            directory.parent.chmod(0o700)
        path = directory / ('retired.json' if archived and retired else 'agents-' + launch_id + '.json')
        state = dict(schema_version=1, launch_id=launch_id, name='worker', socket=str(self.root / 'unused.sock'),
                     target=self.worker, starter=starter or self.starter, report_to=starter or self.starter,
                     contract=dict(awaiting_starter=dict(kind=kind, at=10), starter_lapses=2, starter_reminded_at=20),
                     timeline=[dict(at=10, event='Stop', text='done')],
                     immediate_child_term={'Exited': 0} if archived else None)
        path.write_text(json.dumps(state))
        path.chmod(0o600)
        return path

    def run_accept(self, *args, operator=False):
        command = [BIN, 'agents', 'accept', '--registry', str(self.registry), *args]
        runner = pane_authority.operator if operator else subprocess.run
        result = runner(command, env=self.env, capture_output=True, text=True, timeout=10)
        return result.returncode, json.loads(result.stdout)

    def test_live_and_archived_done_and_flag(self):
        for archived, retired, kind in ((False, True, 'done'), (True, True, 'done'),
                                        (True, False, 'flag'), (True, True, 'flag')):
            with self.subTest(archived=archived, retired=retired, kind=kind):
                launch_id = ('a' if not archived else 'b' if retired else 'c') * 32
                path = self.record(launch_id, archived=archived, retired=retired, kind=kind)
                code, packet = self.run_accept('--launch-id', launch_id, '--note', 'Reviewed β')
                self.assertEqual(code, 0, packet)
                state = json.loads(path.read_text())
                self.assertIsNone(state['contract']['awaiting_starter'])
                self.assertEqual(state['contract']['starter_lapses'], 0)
                self.assertNotIn('starter_reminded_at', state['contract'])
                event = state['timeline'][-1]
                self.assertEqual(event['event'], 'report_accepted')
                self.assertEqual(event['accepted_by']['block_id'], self.starter['block_id'])
                self.assertEqual(event['note'], 'Reviewed β')
                self.assertEqual(event['report']['kind'], kind)
                timeline = subprocess.run([BIN, 'agents', 'timeline', '--registry', str(self.registry), '--json'],
                                          env=self.env, capture_output=True, text=True, timeout=10)
                self.assertEqual(timeline.returncode, 0, timeline.stderr)
                self.assertTrue(any(e['event'] == 'report_accepted' and e['launch_id'] == launch_id
                                    for e in json.loads(timeline.stdout)['events']))
                before = path.read_bytes()
                code, packet = self.run_accept('--launch-id', launch_id)
                self.assertEqual(code, 1)
                self.assertEqual(packet['failure_reason'], 'no_pending_report')
                self.assertEqual(path.read_bytes(), before)

    def test_stranger_refused_without_write(self):
        self.actor(self.address('3'))
        before = self.path.read_bytes()
        code, packet = self.run_accept('--launch-id', 'a' * 32)
        self.assertEqual(code, 1)
        self.assertIn('requires_starter', packet['failure_reason'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_report_to_and_registered_seat(self):
        for seat in (False, True):
            self.record('a' * 32)
            caller = self.address('3')
            self.actor(caller)
            if seat:
                (self.boards / 'state.json').write_text(json.dumps(dict(seats=[dict(target=caller)])))
            else:
                state = json.loads(self.path.read_text())
                state['report_to'] = caller
                self.path.write_text(json.dumps(state))
            code, packet = self.run_accept('--launch-id', 'a' * 32)
            self.assertEqual(code, 0, packet)

    def test_operator_path(self):
        self.actor(self.address('3'))
        code, packet = self.run_accept('--launch-id', 'a' * 32, operator=True)
        self.assertEqual(code, 0, packet)
        self.assertTrue(packet['acceptance']['accepted_by']['operator'])

    def test_name_is_scoped_and_ambiguous_archives_refuse(self):
        self.record('b' * 32, starter=self.address('3'))
        code, packet = self.run_accept('--name', 'worker')
        self.assertEqual(code, 0, packet)
        self.record('a' * 32)
        self.record('c' * 32, archived=True)
        code, packet = self.run_accept('--name', 'worker')
        self.assertEqual(code, 1)
        self.assertEqual(packet['failure_reason'], 'agent_name_ambiguous')

    def test_archived_symlink_refused(self):
        directory = self.registry / 'archive'
        directory.symlink_to(self.root)
        code, packet = self.run_accept('--launch-id', 'a' * 32)
        self.assertEqual(code, 1)
        self.assertIsNotNone(json.loads(self.path.read_text())['contract']['awaiting_starter'])


if __name__ == '__main__':
    unittest.main()
