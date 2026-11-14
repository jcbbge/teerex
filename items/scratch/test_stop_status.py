"""Allowed Claude stops replace only the root status, preserving real questions."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

status = load('teerex_seat_status', 'items/boards/seat_status.py')
scratch = load('scratch', 'items/scratch/scratch.py')
agents = types.ModuleType('stop_test_agents')
exec(compile((ROOT / 'src/scoped_channel.py').read_text(), 'scoped_channel.py', 'exec'), agents.__dict__)
agents.SCRATCH_REMINDER = scratch.SCRATCH_REMINDER
exec(compile((ROOT / 'items/agents/agents.py').read_text(), 'agents.py', 'exec'), agents.__dict__)

class StopStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, TEEREX_ASK_STATE_DIR=self.tmp.name,
                              REX_SERVER='/tmp/rex.sock', REX_SESSION='session:test', REX_BLOCK='block:test')
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_question_origin_uses_shared_caller_precedence(self):
        for environment, expected in [
            (dict(LC_REX_SESSION='ssh', LC_REX_BLOCK='ssh-pane'), ('ssh', 'ssh-pane')),
            (dict(REX_SESSION='rex', REX_BLOCK='rex-pane', LC_REX_SESSION='ssh', LC_REX_BLOCK='ssh-pane'), ('rex', 'rex-pane')),
            (dict(AGENT_SESSION='agent', AGENT_PANE='agent-pane', REX_SESSION='rex', REX_BLOCK='rex-pane'), ('agent', 'agent-pane')),
        ]:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(status.origin(), dict(zip(('session', 'block'), expected)))

    def test_idle_root(self):
        with patch.object(status, 'write_status', return_value='written') as write:
            status.claude_stopped('')
        self.assertEqual(write.call_args.args[1], '\x1b]7501;state=idle\x1b\\')

    def test_waiting_root(self):
        with patch.object(status, 'write_status', return_value='written') as write:
            status.claude_stopped('Waiting for the review')
        self.assertEqual(write.call_args.args[1], '\x1b]7501;state=blocked:kind=question:msg=V2FpdGluZyBmb3IgdGhlIHJldmlldw==\x1b\\')

    def test_open_ask(self):
        with status.ledger('/tmp/rex.sock', True) as cards:
            cards.append(dict(id='ask/test', seat=dict(session='session:seat', block='block:seat'), asker=status.origin()))
        with patch.object(status, 'native', return_value={'records': [dict(id='ask/test', state='blocked', msg='Approve this?')]}), patch.object(status, 'write_status', return_value='written') as write:
            status.claude_stopped('')
        self.assertIn('state=blocked:kind=question:msg=QXBwcm92ZSB0aGlzPw==', write.call_args.args[1])

    def test_stale_stop_writes_nothing(self):
        with patch.dict(sys.modules, teerex_seat_status=status), patch.object(status, 'claude_stopped') as stopped:
            scratch.claude_stop_status({'hook_event_name': 'Stop'}, {'action': 'block'}, None)
            scratch.claude_stop_status({'hook_event_name': 'UserPromptSubmit'}, {}, None)
        stopped.assert_not_called()

    def test_allowed_stop_uses_scratch_waiting(self):
        with patch.dict(sys.modules, teerex_seat_status=status), patch.object(scratch, 'scratch_read', return_value={'waiting': 'Review pending'}), patch.object(status, 'claude_stopped') as stopped:
            scratch.claude_stop_status({'hook_event_name': 'Stop'}, {'action': 'allow'}, '/tmp/scratch')
        stopped.assert_called_once_with('Review pending')

    def test_managed_hook_only_allowed_claude_stop_writes(self):
        options = types.SimpleNamespace(payload=json.dumps(dict(hook_event_name='Stop')), event_file=None,
                                        harness='claude', command_json=json.dumps(['/usr/bin/python3', '-c', 'pass']))
        for action in ('allow', 'block'):
            result = types.SimpleNamespace(returncode=0, stdout=json.dumps(dict(scratchpad_check=dict(action=action))).encode())
            with patch.object(agents.subprocess, 'run', return_value=result), patch.object(agents, 'claude_stop_status', create=True) as stopped, patch('builtins.print'):
                agents.hook(options)
            self.assertEqual(stopped.call_count, int(action == 'allow'))
        options.harness = 'pi'
        with patch.object(agents.subprocess, 'run', return_value=result), patch.object(agents, 'claude_stop_status', create=True) as stopped:
            agents.hook(options)
        stopped.assert_not_called()

    def test_hook_without_tty_uses_pane_process(self):
        with patch.object(status, 'native', return_value=dict(child=dict(pid=123))), patch.object(status, 'write_status', side_effect=['tty_unavailable', 'written']) as write:
            self.assertEqual(status.claude_stopped(''), 'written')
        self.assertEqual(write.call_args.args[0], 123)

    def test_followup_bootstrap_skips_cli_entrypoint_and_exits(self):
        marker = Path(self.tmp.name) / 'child-ran'
        source = "if __name__ == '__main__': raise AssertionError('CLI entrypoint ran')\n"
        source += "def claude_stop_followup(socket, target, waiting):\n from pathlib import Path\n Path(" + repr(str(marker)) + ").write_text(waiting)\n"
        children = []
        original = subprocess.Popen
        def start(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(status, '__source__', source, create=True), patch.object(status, 'native', return_value=dict(child=dict(pid=123))), patch.object(status, 'status_tty', return_value='/dev/null'), patch.object(status, 'write_status', return_value='written'), patch.object(status.subprocess, 'Popen', side_effect=start):
            status.claude_stopped('Review pending')
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].wait(timeout=5), 0)
        self.assertEqual(marker.read_text(), 'Review pending')

    def test_followup_waits_for_claude_done(self):
        states = [dict(records=[dict(state='idle')]), dict(records=[dict(state='done', app='claude-code')]), dict(child=dict(pid=123))]
        with patch.object(status, 'native', side_effect=states), patch.object(status.time, 'sleep'), patch.object(status, 'write_status', return_value='written') as write:
            status.claude_stop_followup('/tmp/rex.sock', status.origin(), 'Review pending')
        write.assert_called_once_with(123, '\x1b]7501;state=blocked:kind=question:msg=UmV2aWV3IHBlbmRpbmc=\x1b\\')

    def test_followup_does_not_overwrite_new_turn(self):
        with patch.object(status, 'native', return_value=dict(records=[dict(state='working', app='claude-code')])), patch.object(status, 'write_status', return_value='written') as write:
            status.claude_stop_followup('/tmp/rex.sock', status.origin(), '')
        write.assert_not_called()

if __name__ == '__main__':
    unittest.main()
