"""Refusal actions through the public CLI; temporary state, no live mutations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BIN = str(Path(os.environ.get('TEEREX_BIN', 'zig-out/bin/teerex')).resolve())
SESSION = 'session:11111111-1111-1111-1111-111111111111'
BLOCK = 'block:22222222-2222-2222-2222-222222222222'


class RefusalNextTest(unittest.TestCase):
    def test_no_hint_without_a_terminal(self):
        # Hooks and supervisors inherit agent panes; a hint there paints the harness input row.
        p = subprocess.run([BIN, 'send', '--bogus'], env=self.env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=15)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('next: ', p.stderr)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='teerex-refusal-next-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, HOME=str(self.root), REX_SESSION=SESSION, REX_BLOCK=BLOCK,
                        TEEREX_CALL_LOG_DIR=str(self.root / 'calls'))

    def run_at_terminal(self, *args):
        # Hints are for a person at a terminal: stdin and stderr are a pty here.
        master, slave = os.openpty()
        try:
            p = subprocess.run([BIN, *map(str, args)], env=self.env, stdin=slave, stdout=subprocess.PIPE,
                               stderr=slave, text=True, timeout=15)
            os.close(slave); slave = None
            chunks = []
            while True:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
            p.stderr = b''.join(chunks).decode(errors='replace').replace('\r\n', '\n')
            return p
        finally:
            if slave is not None:
                os.close(slave)
            os.close(master)

    def refusal(self, *args, expected=None):
        p = self.run_at_terminal(*args)
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        lines = [line for line in p.stderr.splitlines() if line.startswith('next: ')]
        self.assertTrue(lines, p.stdout + p.stderr)
        self.assertTrue(all(len(line) > len('next: ') for line in lines))
        for line in lines:
            action = line.removeprefix('next: ')
            if action.startswith('teerex ') and action.endswith(' --help'):
                help_result = subprocess.run([BIN, *action.split()[1:]], env=self.env,
                                             capture_output=True, text=True, timeout=15)
                self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
        for word in ('receipt', 'OSC', 'brief_submitted'):
            self.assertTrue(all(word not in line for line in lines), lines)
        if expected:
            self.assertIn(expected, '\n'.join(lines))
        return p

    def test_send(self):
        self.refusal('send', '--not-an-option', expected='teerex send --help')
        (self.root / 'message').write_text('hello')
        # A disconnected endpoint must advise checking delivery, never a blind retry.
        p = self.refusal('send', '--socket', self.root / 'absent.sock', '--session', SESSION,
                        '--block', BLOCK, '--from', 'fixture', '--message-file', self.root / 'message', '--timeout-ms', '100',
                        expected='before sending again')
        self.assertFalse(json.loads(p.stdout)['retry_safe'])

    def test_agents_launch(self):
        self.refusal('agents', 'launch', '--config', self.root / 'absent.json', '--profile', 'fixture',
                     expected='Ask your starter')
        self.refusal('agents', 'launch', expected='teerex agents launch --help')

    def test_agents_ack(self):
        self.refusal('agents', 'ack', '--registry', self.root / 'agents', '--launch-id', 'a' * 32,
                     '--token', 'b' * 64, '--session', SESSION, '--block', BLOCK,
                     expected='Ask your starter')
        self.refusal('agents', 'ack', expected='teerex agents ack --help')

    def test_agents_stop(self):
        self.refusal('agents', 'stop', '--registry', self.root / 'agents', '--launch-id', 'a' * 32,
                     '--event-file', self.root / 'absent.json', expected='Ask your starter')
        self.refusal('agents', 'stop', expected='teerex agents stop --help')

    def test_agents_prune(self):
        self.refusal('agents', 'prune', '--registry', 'relative', expected='Use an absolute path')
        self.refusal('agents', 'prune', expected='teerex agents prune --help')

    def test_scratch(self):
        self.refusal('scratch', 'show', expected='teerex scratch init')
        self.refusal('scratch', 'path', '--session', 'bad', expected='rex whoami --json')
        self.refusal('scratch', 'now', expected='teerex scratch now --help')
        self.refusal('scratch', 'palette', expected='teerex scratch palette --help')
        self.refusal('scratch', 'palette', '--file', 'relative', '--socket', '/absent.sock', expected='teerex scratch palette --help')

    def test_surfaces(self):
        self.refusal('surfaces', 'open', '--not-an-option', expected='teerex surfaces --help')
        self.refusal('surfaces', 'resolve', '--socket', self.root / 'absent.sock',
                     '--session', SESSION, '--pane', BLOCK, '--timeout-ms', '100', expected='before changing it again')

        self.refusal('surfaces', 'palette', 'install', expected='teerex surfaces palette install --help')
        self.refusal('surfaces', 'palette', 'install', '--init', self.root / 'absent.lua',
                     '--file', self.root / 'action.lua', '--socket', '/absent.sock', '--plan', self.root / 'plan.json',
                     expected='before planning the palette installation again')
        for operation in ('agents', 'hosts', 'focus'):
            self.refusal('surfaces', 'palette', operation, expected='teerex surfaces palette ' + operation + ' --help')

    def test_waiting(self):
        self.refusal('waiting', 'list', '--config', self.root / 'absent.json', expected='teerex doctor --all')
        self.refusal('waiting', '--not-an-option', expected='teerex waiting --help')

    def test_ask(self):
        self.refusal('ask', expected='teerex ask --help')
        self.refusal('ask', '--store', self.root / 'boards', '--host', 'fixture', '--socket', '/absent.sock',
                     '--session', SESSION, '--block', BLOCK, '--from', 'fixture', '--teerex', BIN,
                     '--card-file', self.root / 'absent.json', expected='before sending again')

    def test_board(self):
        self.refusal('board', '--not-an-option', expected='teerex board --help')
        self.refusal('board', '--replay', self.root / 'absent.jsonl', '--json', expected='teerex board --help')

        self.refusal('board', 'feed', '--not-an-option', expected='teerex board feed --help')
        self.refusal('board', 'feed', '--config', 'relative', '--once', expected='teerex board feed --help')

    def test_boards(self):
        self.refusal('boards', 'state', 'inspect', '--store', 'relative', expected='teerex boards --help')
        self.refusal('boards', 'inbox', '--not-an-option', expected='teerex boards inbox --help')

    def test_doctor(self):
        self.refusal('doctor', '--not-an-option', expected='teerex doctor --help')
        self.refusal('doctor', '--socket', self.root / 'absent.sock', '--timeout-ms', '100', expected='server socket')
        self.refusal('doctor', '--all', '--config', self.root / 'absent.json', expected='teerex doctor --all --help')

    def test_named_host_routing_refusal(self):
        for command in ('send', 'agents', 'scratch', 'surfaces', 'waiting', 'ask', 'board', 'doctor'):
            with self.subTest(command=command):
                self.refusal('--config', self.root / 'absent.json', '--host', 'fixture', command,
                             expected='Check the selected host and configuration file')

    def test_help_and_success_do_not_print_next(self):
        for command in ('send', 'agents', 'scratch', 'surfaces', 'waiting', 'ask', 'board', 'boards', 'doctor'):
            with self.subTest(command=command):
                p = subprocess.run([BIN, command, '--help'], env=self.env, capture_output=True, text=True, timeout=15)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertNotIn('next: ', p.stderr)
        p = subprocess.run([BIN, 'scratch', 'path'], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn('next: ', p.stderr)


if __name__ == '__main__':
    unittest.main()
