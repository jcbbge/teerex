"""Attention-only tests, with live disposable terminal coverage via SendTest."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('attention', Path(__file__).with_name('attention.py'))
attention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(attention)


class AttentionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profiles = self.root / 'profiles.json'
        self.registry = self.root / 'agents'
        self.registry.mkdir()
        self.env = patch.dict(os.environ, TEEREX_ATTENTION_DIR=str(self.root / 'counts'))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.context = dict(socket='/test', session='session:test', block='block:test', sender='worker')

    def snapshot(self):
        return attention.attention_snapshot(0, self.profiles, self.registry)

    def test_counts_words_concurrency_and_hourly_share(self):
        self.profiles.write_text(json.dumps(dict(profiles=dict(codex=dict(attention_messages_per_hour=2)))))
        (self.registry / 'agents-test.json').write_text(json.dumps(dict(name='worker', profile='codex')))
        with concurrent.futures.ThreadPoolExecutor() as pool:
            self.assertEqual(list(pool.map(lambda _: attention.attention_record(self.context, 4, True), range(3))), ['written'] * 3)
        snapshot = self.snapshot()
        self.assertEqual((snapshot['messages'], snapshot['words']), (3, 12))
        self.assertEqual(len(snapshot['hours']), 1)
        self.assertEqual(snapshot['senders'][0]['share_per_hour'], 2)
        self.assertTrue(snapshot['senders'][0]['over_share'])
        self.assertEqual(snapshot['senders'][0]['color'], 'amber')
        self.assertNotIn('body', (self.root / 'counts/deliveries.jsonl').read_text())
        self.assertEqual((self.root / 'counts').stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / 'counts/deliveries.jsonl').stat().st_mode & 0o777, 0o600)

    def test_since_and_rolling_hour_are_distinct(self):
        now = int(time.time() * 1000)
        with attention.attention_log(True) as stream:
            for at in (now - 7200000, now - 1000):
                stream.write(json.dumps(dict(at=at, sender='worker', words=5)) + '\n')
        snapshot = self.snapshot()
        self.assertEqual(snapshot['messages'], 2)
        self.assertEqual(snapshot['senders'][0]['messages_last_hour'], 1)
        self.assertEqual(len(snapshot['hours']), 2)
        self.assertEqual(attention.attention_snapshot(now - 2000, self.profiles, self.registry)['messages'], 1)
        for value in ('today', '1h', '30m', '2026-11-14T00:00:00Z'):
            self.assertIsInstance(attention.attention_since(value), int)
        for value in ('bad', '-1h', 'nanh'):
            with self.assertRaises(Exception):
                attention.attention_since(value)

    def test_nonseat_and_insecure_log_never_block_delivery(self):
        with patch.object(attention, 'attention_registered', return_value=False):
            self.assertEqual(attention.attention_record(self.context, 2), 'not_requested')
        self.assertEqual(self.snapshot()['messages'], 0)
        self.assertEqual(attention.attention_record(self.context, 2, True), 'written')
        path = self.root / 'counts/deliveries.jsonl'
        path.chmod(0o644)
        self.assertEqual(attention.attention_record(self.context, 2, True), 'unavailable')
        path.chmod(0o600)
        original = path.read_bytes()
        path.unlink()
        other = self.root / 'other'
        other.write_bytes(original)
        path.symlink_to(other)
        self.assertEqual(attention.attention_record(self.context, 2, True), 'unavailable')
        self.assertEqual(other.read_bytes(), original)

    def test_registered_unlabelled_seat(self):
        store = self.root / 'boards'
        store.mkdir(mode=0o700)
        state = store / 'state.json'
        state.write_text(json.dumps(dict(seats=[dict(target=dict(server='unix:///test', session_id='session:test', block_id='block:test'))])))
        state.chmod(0o600)
        with patch.dict(os.environ, TEEREX_BOARDS_STORE=str(store)):
            self.assertEqual(attention.attention_record(self.context, 3), 'written')
        self.assertEqual(self.snapshot()['messages'], 1)


if __name__ == '__main__':
    unittest.main()
