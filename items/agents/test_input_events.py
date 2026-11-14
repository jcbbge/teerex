"""Isolated input replacement and supervisor regressions; no Rex endpoint is used."""
import contextlib
import importlib.util
import io
import os
import sys
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/acceptance'))
from test_environment import isolated_environment

def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    if name == 'agents':
        exec((Path(__file__).parents[2] / 'src/scoped_channel.py').read_text(), result.__dict__)
    spec.loader.exec_module(result)
    return result


inputs = module('input_events')
agents = module('agents')
SID = 'session:00000000-0000-0000-0000-000000000001'
BID = 'block:00000000-0000-0000-0000-000000000002'


class InputEventsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, dict(isolated_environment(), HOME=self.temp.name,
                                             REX_SESSION=SID, REX_BLOCK=BID), clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.target = (self.temp.name + '/unused.sock', SID, BID)

    def test_atomic_replacement_race(self):
        inputs.agent_input_write(*self.target, 1)
        stop = threading.Event()
        errors = []
        def writer():
            try:
                while not stop.is_set():
                    inputs.agent_input_write(*self.target, time.time_ns())
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=writer)
        thread.start()
        reads = 0
        end = time.monotonic() + 2
        try:
            while reads < 20000 or time.monotonic() < end:
                event = inputs.agent_input_read(*self.target)
                self.assertTrue(event is None or (type(event['at_ns']) is int and event['at_ns'] > 0))
                reads += 1
        finally:
            stop.set()
            thread.join()
        self.assertEqual(errors, [])
        print('atomic replacement: %d reads, 0 refusals' % reads)

    def test_retired_inode_reopens_current_event(self):
        inputs.agent_input_write(*self.target, 1)
        original = os.fstat
        calls = []
        def replace(fd):
            if not calls:
                calls.append(fd)
                inputs.agent_input_write(*self.target, 2)
            return original(fd)
        with patch.object(inputs.os, 'fstat', side_effect=replace):
            self.assertEqual(inputs.agent_input_read(*self.target)['at_ns'], 2)

    def test_private_event_checks_remain_enforced(self):
        inputs.agent_input_write(*self.target, 1)
        path = inputs.agent_input_path(*self.target)
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private_agent_input_event_required'):
            inputs.agent_input_read(*self.target)
        path.chmod(0o600)
        os.link(path, path.with_suffix('.link'))
        with self.assertRaisesRegex(ValueError, 'private_agent_input_event_required'):
            inputs.agent_input_read(*self.target)

    def test_supervisor_survives_bad_input_and_loop_error(self):
        inputs.agent_input_write(*self.target, 1)
        inputs.agent_input_path(*self.target).chmod(0o644)
        root = Path(self.temp.name) / 'registry'
        root.mkdir(mode=0o700)
        launch = 'a' * 32
        protocol = Path(self.temp.name) / 'protocol'
        protocol.write_text('protocol')
        protocol.chmod(0o600)
        state = dict(schema_version=1, launch_id=launch, socket=self.target[0], target=dict(session_id=SID, block_id=BID),
                     tracked=True, protocol_file=str(protocol), immediate_child_term=None, name='fake', starter=None,
                     report_to=None, scratchpad=str(Path(self.temp.name) / 'scratch'), argv=['fake'], cwd=self.temp.name,
                     hook_events=False)
        with agents.Registry(str(root)) as registry:
            registry.save(state, new=True)
        child = types.SimpleNamespace(returncode=0)
        polls = iter([None, None, None, 0])
        child.poll = lambda: next(polls)
        options = types.SimpleNamespace(registry=str(root), launch_id=launch)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(agents, 'agent_input_read', inputs.agent_input_read, create=True))
            stack.enter_context(patch.object(agents, 'scratch_read', side_effect=RuntimeError('loop failed'), create=True))
            stack.enter_context(patch.object(agents.subprocess, 'Popen', return_value=child))
            stack.enter_context(patch.object(agents.signal, 'signal'))
            stack.enter_context(patch.object(agents, 'program_status'))
            stack.enter_context(patch.object(agents, 'come_forward'))
            stack.enter_context(patch.object(agents, 'notify', return_value=(1, {'failure': 'notice'})))
            out, err = io.StringIO(), io.StringIO()
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            self.assertEqual(agents.supervise_child(options), (0, None))
        recorded = agents.load(str(root), launch)
        self.assertEqual(recorded['last_input_read_error']['reason'], 'private_agent_input_event_required')
        self.assertGreater(recorded['last_input_read_error']['at'], 0)
        self.assertEqual(recorded['last_supervisor_loop_error']['reason'], 'loop failed')
        self.assertEqual(recorded['immediate_child_term'], {'Exited': 0})
        record_path = root / ('agents-' + launch + '.json')
        before = record_path.stat().st_ino
        agents.supervisor_error(options, 'last_input_read_error', ValueError('later'))
        self.assertEqual(record_path.stat().st_ino, before)
        self.assertEqual(agents.load(str(root), launch)['last_input_read_error'], recorded['last_input_read_error'])
        self.assertEqual((out.getvalue(), err.getvalue()), ('', ''))

    def test_supervise_refusal_is_silent(self):
        options = types.SimpleNamespace(operation='supervise', registry=self.temp.name, launch_id='a' * 32)
        with patch.object(agents, 'parser') as parser, patch.object(agents, 'supervise', side_effect=agents.Refusal('refused')), patch.object(agents.signal, 'signal'):
            parser.return_value.parse_args.return_value = options
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(agents.main(), 1)
            self.assertEqual((out.getvalue(), err.getvalue()), ('', ''))


if __name__ == '__main__':
    unittest.main()
