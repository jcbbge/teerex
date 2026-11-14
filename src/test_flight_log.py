import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('flight_log', Path(__file__).with_name('flight_log.py'))
log = importlib.util.module_from_spec(spec)
spec.loader.exec_module(log)

class FlightLogTests(unittest.TestCase):
    def test_evidence_merge_archive_steps_and_since(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / '.local/state'
            agents = root / 'teerex-agents'
            agents.mkdir(parents=True)
            pad = root / 'pad.md'
            pad.write_text('Updated: 2026-11-14T03:00:00Z\n## Done\n- [x] install — proof: live command\n')
            base = dict(name='worker', created_at=log.timestamp('2026-11-14T02:00Z'), scratchpad=str(pad), contract=dict(declared='blocked', now='fix install'))
            (agents / 'agents-1.json').write_text(json.dumps(dict(base, token='DO NOT EXPORT', argv=['SECRET'])))
            (agents / 'agents-1-contract-1.txt').write_text('STEP worker 1/2 finished: build\nprivate report body')
            archived = agents / 'archive/old'
            archived.mkdir(parents=True)
            (archived / 'agents-old.json').write_text(json.dumps(dict(name='older', created_at=log.timestamp('2026-11-13T02:00Z'))))
            record = root / 'teerex-records/records/decision'
            record.mkdir(parents=True)
            (record / 'record.json').write_text(json.dumps(dict(kind='decision', id='d1', state='open', question='Ship?', written_at='2026-11-14T01:00Z')))
            data = log.collect(tmp)
            rows = log.merged({'host': data}, log.timestamp('2026-11-14T00:00Z'))
            self.assertTrue(any(r['kind'] == 'step recorded' for r in rows))
            self.assertFalse(any(r['who'] == 'older' for r in rows))
            self.assertEqual(len(data['decisions']), 1)
            self.assertIn('worker: fix install', data['stalled'])
            report = log.brief({'host': data}, 0)
            self.assertIn('proof: live command', report)
            self.assertNotIn('SECRET', json.dumps(data))
            self.assertNotIn('DO NOT EXPORT', json.dumps(data))
            self.assertNotIn('private report body', json.dumps(data))

    def test_offline_page_escapes_and_controls(self):
        row = dict(at=1, host='host', who='<script>alert(1)</script>', kind='launch', text='</td><img src=https://evil>', source='path')
        page = log.page([row], {})
        self.assertNotIn('<script>', page)
        self.assertNotIn('<img', page)
        self.assertIn("default-src 'none'", page)
        self.assertEqual(log.clean('\x1bhello\n\x7f'), 'hello')

    def test_invalid_timestamp_and_symlink(self):
        with self.assertRaises(ValueError):
            log.timestamp('yesterday')
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'
            target.write_text('private')
            link = Path(tmp) / 'link'
            link.symlink_to(target)
            with self.assertRaises(OSError):
                log.read(link)

if __name__ == '__main__':
    unittest.main()
