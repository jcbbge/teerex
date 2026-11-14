"""Authority checks against disposable Rex and throwaway authority stores only."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_surface_fixture', ROOT / 'items/surfaces/test_surfaces.py')
_fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_fixtures)


class GuardTest(_fixtures.SurfacesTest):
    def setUp(self):
        super().setUp()
        self.store = self.work / 'boards'
        self.store.mkdir(mode=0o700)
        self.env['TEEREX_BOARDS_STORE'] = str(self.store)
        self.env['TEEREX_CLUTCH_DIR'] = str(self.work / 'clutch')
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


if __name__ == '__main__':
    # This file reuses fixture helpers, never the unrelated surfaces suite.
    names = [n for n in GuardTest.__dict__ if n.startswith('test_')]
    suite = unittest.TestSuite(GuardTest(n) for n in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
