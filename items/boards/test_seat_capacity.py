import os
from pathlib import Path
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]

class SeatCapacityTest(unittest.TestCase):
    def test_ask_ledger_grows_with_open_rows_and_drops_resolved(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('seat_status_capacity', ROOT / 'items/boards/seat_status.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='ask-capacity-') as root, patch.dict(os.environ, TEEREX_ASK_STATE_DIR=root):
            os.chmod(root, 0o700)
            with module.ledger('/tmp/disposable-capacity.sock', True) as rows:
                rows.extend(dict(id=str(n), expires=n, detail='x' * 1024) for n in range(513))
            with module.ledger('/tmp/disposable-capacity.sock') as rows:
                self.assertEqual(len(rows), 513)
            with module.ledger('/tmp/disposable-capacity.sock', True) as rows:
                rows[0]['resolved'] = True
            with module.ledger('/tmp/disposable-capacity.sock') as rows:
                self.assertEqual(len(rows), 512)
                self.assertNotIn('0', [r['id'] for r in rows])
