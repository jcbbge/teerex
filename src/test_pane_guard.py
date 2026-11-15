"""Shared label refusal on disposable Rex servers; no authority records."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_surface_fixture', ROOT / 'items/surfaces/test_surfaces.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class GuardTest(fixtures.SurfacesTest):
    def control(self, op, pane, *args):
        return self.surface(op, '--session', self.session, '--pane', pane, *args)

    def test_seat_tab_labels_refuse_close_and_move(self):
        self.rpc('session.set_block_label', dict(session_id=self.session, block_id=self.anchor, label='seat'))
        other = self.open('tab', label='elsewhere')['actual']['block_id']
        for op, extra in (('close', ()), ('move', ('--anchor', other, '--focus', 'yes'))):
            with self.subTest(op=op):
                result, packet = self.control(op, self.anchor, *extra)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('seat_tab_label_protected', packet['failure_reason'])
                self.assertIn(self.anchor, {b['block_id'] for b in self.rpc('session.list_blocks', dict(session_id=self.session))['blocks']})

    def test_former_companions_in_seat_tab_close(self):
        # Josh, 2026-11-15: only the seat pane and its tab stay protected.
        self.rpc('session.set_block_label', dict(session_id=self.session, block_id=self.anchor, label='seat'))
        for label in ('tasks', 'board', 'alarm'):
            with self.subTest(label=label):
                pane = self.open('tiled', label=label)['actual']['block_id']
                result, packet = self.control('close', pane)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(packet['block_absence_verified'])

    def test_any_creator_and_plain_rex_panes_close(self):
        made = self.open('tab')['actual']['block_id']
        self.env.update(AGENT_SESSION='unrelated', AGENT_PANE='unrelated', AGENT_NAME='other')
        plain = self.rpc('session.new_window', dict(session_id=self.session, focus=False, layout=dict(block=dict(
            flavor='com.superlogical.terminal.shell', label='plain rex', options=dict(command=['/bin/sleep', '60'])))))['block_ids'][0]
        for pane in (made, plain):
            result, packet = self.control('close', pane)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(packet['block_absence_verified'])
        self.assertFalse(list(Path(self.env['XDG_STATE_HOME']).glob('teerex/pane-creators/**/*')))

    def test_ordinary_companion_closes_and_operator_cannot_bypass(self):
        self.rpc('session.set_block_label', dict(session_id=self.session, block_id=self.anchor, label='seat'))
        ordinary = self.open('tiled', label='ordinary')['actual']['block_id']
        result, packet = self.control('close', ordinary)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result, packet = self.control('close', self.anchor, '--operator')
        self.assertEqual(result.returncode, 1)
        self.assertIn('seat_tab_label_protected', packet['failure_reason'])

    def test_board_in_other_tab_closes(self):
        self.rpc('session.set_block_label', dict(session_id=self.session, block_id=self.anchor, label='seat'))
        pane = self.open('tab', label='board')['actual']['block_id']
        result, packet = self.control('close', pane)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(packet['block_absence_verified'])

    def test_session_close_client_kind_decisions(self):
        # Only client.list is simulated; closure and absence use real Rex.
        for kinds in (['app'], ['app', 'app'], ['cli'], ['app', 'cli'], ['agent'], ['other'], ['future'], [None]):
            with self.subTest(kinds=kinds):
                sid = self.rpc('session.create', dict(label='client kinds ' + str(kinds)))['session_id']
                def cleanup(sid=sid):
                    if sid in {v['session_id'] for v in self.rpc('session.list', {})['sessions']}:
                        self.rpc('session.destroy', dict(session_id=sid))
                self.addCleanup(cleanup)
                clients = [dict(client_id='client:fixture-' + str(n), info=dict(kind=kind))
                           if kind else dict(client_id='client:fixture-' + str(n)) for n, kind in enumerate(kinds)]
                script = "local native=rex.call; rex.call=function(m,p) if m=='client.list' then return rex.json.decode(" + json.dumps(json.dumps(dict(clients=clients))) + ") end return native(m,p) end\n"
                script += (ROOT / 'src/pane_guard.lua').read_text()
                script += (ROOT / 'items/surfaces/surfaces.lua').read_text()
                script += '\nreturn surface(rex.args)'
                result = subprocess.run(self.base + ['do', '-e', script, '--args', json.dumps(dict(
                    operation='session-close', session_id=sid)), '--json'], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                packet = json.loads(result.stdout)
                apps = all(kind == 'app' for kind in kinds)
                self.assertEqual(packet['outcome'], 'session_closed_and_absent' if apps else 'refused')
                if not apps:
                    self.assertEqual(packet['failure_reason'], 'session_has_attached_clients')

    def test_shared_guard_blocks_aggregate_close_and_detach(self):
        self.rpc('session.set_block_label', dict(session_id=self.session, block_id=self.anchor, label='seat'))
        view = self.view()
        window = next(w for w in view['windows'] if any(b['block_id'] == self.anchor for l in w['layers'] for b in l['blocks']))
        layer = next(l for l in window['layers'] if any(b['block_id'] == self.anchor for b in l['blocks']))
        for method, extra in (('session.destroy', {}), ('session.close_window', dict(window_id=window['window_id'])),
                              ('session.close_layer', dict(layer_id=layer['layer_id'])),
                              ('session.detach_block', dict(block_id=self.anchor))):
            script = (ROOT / 'src/pane_guard.lua').read_text() + '\nreturn rex.call(rex.args.method,rex.args.params)'
            result = subprocess.run(self.base + ['do', '-e', script, '--args', json.dumps(dict(method=method,
                params=dict(session_id=self.session, **extra))), '--json'], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('seat_tab_label_protected', result.stderr)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(GuardTest(name) for name in GuardTest.__dict__ if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
