"""Retained-release supervisor compatibility on a disposable Rex server."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
import test_agents as fixtures

NEW = fixtures.BIN
OLD = os.environ.get('TEEREX_OLD_BIN', str(Path.home() / '.local/opt/teerex-managed/versions/v0.1.0-alpha.6.main.2961d7a/teerex'))


class OldSupervisorTest(fixtures.AgentsTest):
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
            p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        state = self.record(launched['launch_id'])
        # The retained interpreter has old source; every subprocess resolves current.
        current.unlink()
        new_release = release.parent / 'new'
        new_release.mkdir()
        (new_release / 'teerex').symlink_to(NEW)
        current.symlink_to(new_release, target_is_directory=True)
        self.scratch_contract(state, done=['old-code complete'])
        actor = dict(self.env, AGENT_NAME='probe', AGENT_SESSION=self.session,
                     AGENT_PANE=state['target']['block_id'], REX_BLOCK=state['target']['block_id'],
                     AGENT_REGISTRY=str(self.registry), AGENT_SCRATCHPAD=state['scratchpad'])
        for turn in range(2):
            self.scratch_contract(state, done=['old-code complete ' + str(turn)])
            event = json.dumps(dict(hook_event_name='Stop', last_assistant_message='old-code turn ' + str(turn), scratch_harness='claude'))
            p = subprocess.run([str(old), 'agents', 'stop', '--registry', str(self.registry),
                                '--launch-id', state['launch_id'], '--event-file', '-'],
                               input=event, env=actor, capture_output=True, text=True, timeout=30)
            print('OLD STOP', turn, 'exit', p.returncode, 'stderr', p.stderr, flush=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        fixtures.wait_for(lambda: sum('DONE probe:' in m for m in self.starter_messages()) >= 2)
        self.assertFalse(any('send refused:' in m for m in self.starter_messages()))
        print('OLD SUPERVISOR: two turn reports arrived', flush=True)


if __name__ == '__main__':
    unittest.main()
