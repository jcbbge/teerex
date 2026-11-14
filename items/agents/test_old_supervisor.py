"""Retained-release supervisor compatibility on a disposable Rex server."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import unittest
import uuid
from unittest.mock import patch
import test_agents as fixtures

NEW = fixtures.BIN
OLD = os.environ.get('TEEREX_OLD_BIN', str(Path.home() / '.local/opt/teerex-managed/versions/v0.1.0-alpha.6.main.2961d7a/teerex'))


@unittest.skipUnless(Path(OLD).is_file(), 'retained release required: TEEREX_OLD_BIN')
class OldSupervisorTest(unittest.TestCase):
    # Reuse the disposable-server fixture without inheriting its unrelated tests.
    setUpClass = classmethod(fixtures.AgentsTest.setUpClass.__func__)
    stop_server = classmethod(fixtures.AgentsTest.stop_server.__func__)
    rpc = classmethod(fixtures.AgentsTest.rpc.__func__)
    setUp = fixtures.AgentsTest.setUp
    run_cli = fixtures.AgentsTest.run_cli
    launch = fixtures.AgentsTest.launch
    record = fixtures.AgentsTest.record
    register_starter_identity = fixtures.AgentsTest.register_starter_identity

    def starter_messages(self):
        values = fixtures.events(self.starter_log)
        return [v if isinstance(v, str) else v['payload'] for v in values
                if isinstance(v, str) or v['event'] == 'input']

    def capture(self, block):
        p = subprocess.run([NEW, 'observe', '--socket', str(self.socket),
            '--session', self.session, '--block', block, '--tail'],
            env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)['capture']['content']

    @unittest.skipUnless(os.environ.get('TEEREX_LIVE_CLAUDE'), 'explicit live Claude proof')
    def test_live_claude_two_turns(self):
        real_home = str(Path.home())
        self.env['HOME'] = real_home
        self.env.pop('REX_SERVER', None)
        release = self.work / 'live-install/versions/old'
        release.mkdir(parents=True)
        old = release / 'teerex'
        shutil.copy2(OLD, old)
        current = release.parent.parent / 'current'
        current.symlink_to(release, target_is_directory=True)
        prompt = Path(__file__).resolve().parents[1] / 'send/prompt_fixture.py'
        self.starter_log = self.work / 'live-starter.jsonl'
        made = subprocess.run([NEW, 'surfaces', 'open', '--socket', str(self.socket),
            '--session', self.session, '--layout', 'tab', '--label', 'live proof starter',
            '--', fixtures.sys.executable, str(prompt), str(self.starter_log), 'suggestion'],
            env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        self.starter = json.loads(made.stdout)['actual']['block_id']
        self.settings['defaults']['starter_block'] = self.starter
        fixtures.wait_for(lambda: self.starter_log.exists())
        def starter_input():
            return next((line for line in reversed(self.capture(self.starter).splitlines())
                         if line.lstrip().startswith('❯')), None)
        fixtures.wait_for(lambda: starter_input() is not None)
        starter_before = starter_input()
        self.register_starter_identity()
        self.env.update(AGENT_NAME='lead', AGENT_SESSION=self.session, AGENT_PANE=self.starter,
                        REX_SESSION=self.session, REX_BLOCK=self.starter)
        claude = os.environ['TEEREX_LIVE_CLAUDE']
        wrapper = self.work / 'claude-home'
        wrapper.write_text('#!/bin/sh\nexport HOME=' + shlex.quote(real_home) + '\nexec ' + shlex.quote(claude) + ' "$@"\n')
        wrapper.chmod(0o700)
        self.settings['defaults']['cwd'] = str(Path(__file__).resolve().parents[2])
        normal = json.loads((Path(real_home) / '.config/teerex/profiles.json').read_text())['profiles']['claude']
        normal['project_trust_json'] = str(Path(real_home) / '.claude.json')
        probe_id = str(uuid.uuid4())
        self.settings['profiles']['probe'] = dict(normal, argv=[str(wrapper), '--session-id', probe_id, '--system-prompt',
            'You are a disposable compatibility probe. Acknowledge the supplied protocol command. '
            'Then follow the test brief exactly using Bash. Do not delegate or send anything '
            'except the requested ACK and scratch commands.'], contract_interval_s=600)
        task = 'Compatibility turn one'
        self.brief.write_text('Disposable test. The brief has now arrived: finish any protocol-wait steps and clear Waiting first. Run exactly these commands using Bash: '
            + str(current / 'teerex') + ' scratch todo ' + repr(task) + '; '
            + str(current / 'teerex') + ' scratch now ' + repr(task) + '; '
            + str(current / 'teerex') + ' scratch done --proof "compatibility probe". '
            'Then end your turn with exactly OLD CLAUDE TURN ONE. Do no other work.')
        self.config.write_text(json.dumps(self.settings))
        print('LIVE ROOT', self.work, self.socket, flush=True)
        with patch.object(fixtures, 'BIN', str(old)):
            p, launched = self.run_cli('launch', '--config', str(self.config), '--profile', 'probe',
                '--brief-file', str(self.brief), '--ack-timeout-ms', '60000', timeout=80)
        state = self.record(launched['launch_id'])
        if p.returncode:
            print('LIVE CLAUDE: protocol ACK not received; inspect the owned test pane before cleanup', flush=True)
        pad = Path(state['scratchpad'])
        def cleanup_live():
            closed = subprocess.run([NEW, 'surfaces', 'close', '--socket', str(self.socket),
                '--session', self.session, '--pane', state['target']['block_id']],
                env=self.env, capture_output=True, text=True, timeout=10)
            self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)
            for suffix in ('', '.events', '.lock', '.delivery.lock', '.turn.json'):
                Path(str(pad) + suffix).unlink(missing_ok=True)
            if pad.parent.exists() and not any(pad.parent.iterdir()):
                pad.parent.rmdir()
            projects = Path(real_home) / '.claude/projects'
            # The UUID belongs only to the Claude process this test launched.
            for path in projects.glob('*/' + probe_id + '.jsonl'):
                path.unlink()
                side = path.with_suffix('')
                if side.is_dir():
                    shutil.rmtree(side)
            print('LIVE CLEANUP: owned worker absent; scratch and session files removed', flush=True)
        self.addCleanup(cleanup_live)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        # Swap only the private installation. The old interpreter remains alive.
        current.unlink()
        new_release = release.parent / 'new'
        new_release.mkdir()
        (new_release / 'teerex').symlink_to(NEW)
        current.symlink_to(new_release, target_is_directory=True)
        fixtures.wait_for(lambda: any('OLD CLAUDE TURN ONE' in m and 'DONE probe:' in m
                                     for m in self.starter_messages()), timeout=180)
        print('LIVE CLAUDE: first old-supervisor turn DONE arrived', flush=True)
        message = ('Run ' + str(current / 'teerex') + ' scratch todo "Compatibility turn two"; '
            + str(current / 'teerex') + ' scratch now "Compatibility turn two"; '
            + str(current / 'teerex') + ' scratch done --proof "second compatibility probe". '
            'Then end your turn with exactly OLD CLAUDE TURN TWO. Do no other work.')
        sent = subprocess.run([NEW, 'send', '--socket', str(self.socket), '--session', self.session,
            '--block', state['target']['block_id'], '--from', 'lead', '--message-file', '-'],
            input=message, env=self.env, capture_output=True, text=True, timeout=45)
        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
        fixtures.wait_for(lambda: any('OLD CLAUDE TURN TWO' in m and 'DONE probe:' in m
                                     for m in self.starter_messages()), timeout=180)
        messages = self.starter_messages()
        self.assertTrue(any('STEP probe' in m for m in messages))
        self.assertFalse(any('send refused:' in m for m in messages))
        self.assertEqual(starter_input(), starter_before)
        worker_capture = self.capture(state['target']['block_id'])
        self.assertNotIn('send refused:', worker_capture)
        # Measure actual idle input lines across a retained-supervisor UNANSWERED send.
        def input_line():
            lines = self.capture(state['target']['block_id']).splitlines()
            return next((line for line in reversed(lines) if line.lstrip().startswith('❯')), None)
        fixtures.wait_for(lambda: input_line() is not None)
        worker_before = input_line()
        with (self.registry / 'agents.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = self.record(state['launch_id'])
            record['contract']['awaiting_starter']['at'] = 0
            record['contract']['starter_reminded_at'] = 0
            (self.registry / ('agents-' + state['launch_id'] + '.json')).write_text(json.dumps(record))
        fixtures.wait_for(lambda: any('UNANSWERED probe' in m for m in self.starter_messages()))
        self.assertEqual(input_line(), worker_before)
        self.assertEqual(starter_input(), starter_before)
        print('LIVE CLAUDE: two turns, STEP/DONE/UNANSWERED arrived; both input lines byte-identical', flush=True)

    def test_old_supervisor_turns(self):
        release = self.work / 'install/versions/old'
        release.mkdir(parents=True)
        old = release / 'teerex'
        shutil.copy2(OLD, old)
        current = release.parent.parent / 'current'
        current.symlink_to(release, target_is_directory=True)
        self.register_starter_identity()
        self.env.update(AGENT_NAME='lead', AGENT_SESSION=self.session, AGENT_PANE=self.starter,
                        REX_SESSION=self.session, REX_BLOCK=self.starter)
        self.settings['profiles']['probe']['contract_interval_s'] = 600
        with patch.object(fixtures, 'BIN', str(old)):
            p, launched = self.launch(behavior='quiet', contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        state = self.record(launched['launch_id'])
        # The retained interpreter has old source; every subprocess resolves current.
        current.unlink()
        new_release = release.parent / 'new'
        new_release.mkdir()
        (new_release / 'teerex').symlink_to(NEW)
        current.symlink_to(new_release, target_is_directory=True)

        actor = dict(self.env, AGENT_NAME='probe', AGENT_SESSION=self.session,
                     AGENT_PANE=state['target']['block_id'], REX_BLOCK=state['target']['block_id'],
                     AGENT_REGISTRY=str(self.registry), AGENT_SCRATCHPAD=state['scratchpad'])
        for turn in range(2):
            for args in (('todo', 'old-code complete ' + str(turn)),
                         ('now', 'old-code complete ' + str(turn)), ('done',)):
                step = subprocess.run([NEW, 'scratch', *args], env=actor,
                                      capture_output=True, text=True, timeout=10)
                self.assertEqual(step.returncode, 0, step.stdout + step.stderr)
            fixtures.wait_for(lambda: any('finished: old-code complete ' + str(turn) in m for m in self.starter_messages()))
            event = json.dumps(dict(hook_event_name='Stop', last_assistant_message='old-code turn ' + str(turn)))
            callback = [str(old), 'agents', 'stop', '--registry', str(self.registry),
                        '--launch-id', state['launch_id'], '--event-file', '-']
            p = subprocess.run([str(old), 'agents', 'hook', '--harness', 'claude',
                                '--command-json', json.dumps(callback), '--event-file', '-'],
                               input=event, env=actor, capture_output=True, text=True, timeout=30)
            print('OLD STOP', turn, 'exit', p.returncode, 'stderr', p.stderr, flush=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        fixtures.wait_for(lambda: sum('DONE probe:' in m for m in self.starter_messages()) >= 2)
        self.assertFalse(any('send refused:' in m for m in self.starter_messages()))
        # Make the real retained loop's unanswered clock due, without waiting minutes.
        with (self.registry / 'agents.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = self.record(state['launch_id'])
            record['contract']['awaiting_starter']['at'] = 0
            record['contract']['starter_reminded_at'] = 0
            record['contract']['starter_lapses'] = 0
            (self.registry / ('agents-' + state['launch_id'] + '.json')).write_text(json.dumps(record))
        fixtures.wait_for(lambda: any('UNANSWERED probe' in m for m in self.starter_messages()))
        for args in (('todo', 'lapse probe'), ('now', 'lapse probe')):
            p = subprocess.run([NEW, 'scratch', *args], env=actor, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        fixtures.wait_for(lambda: any('started: lapse probe' in m for m in self.starter_messages()))
        with (self.registry / 'agents.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = self.record(state['launch_id'])
            record['contract'].update(last_contact_at=0, last_lapse_at=0,
                last_lapse_check_at=0, lapses=0, awaiting_starter=None, interval_s=1)
            (self.registry / ('agents-' + state['launch_id'] + '.json')).write_text(json.dumps(record))
        try:
            fixtures.wait_for(lambda: any('LAPSE probe' in m for m in self.starter_messages()))
        except AssertionError:
            print('LAPSE CONTRACT', self.record(state['launch_id']).get('contract'), flush=True)
            diagnostic = subprocess.run([NEW, 'observe', '--state', '--socket', str(self.socket),
                '--session', self.session, '--block', state['target']['block_id']],
                env=actor, capture_output=True, text=True)
            print('LAPSE OBSERVATION', diagnostic.stdout[-4000:], diagnostic.stderr, flush=True)
            raise
        fixtures.wait_for(lambda: any(e['event'] == 'input' and 'tell your starter now' in e['payload']
                                     for e in fixtures.events(self.worker_log)))
        self.assertFalse(any('send refused:' in m for m in self.starter_messages()))
        print('OLD SUPERVISOR: STEP, two old hooks/DONE, UNANSWERED, LAPSE and scratch nudge arrived', flush=True)


if __name__ == '__main__':
    unittest.main()
