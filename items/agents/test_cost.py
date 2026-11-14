"""Isolated harness accounting and once-only warning checks; no paid harnesses."""
import json
import os
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

NS = {'__name__': 'cost_test'}
ROOT = Path(__file__).resolve().parents[2]
for source in ('items/agents/cost.py', 'src/scoped_channel.py', 'items/agents/agents.py'):
    exec(compile((ROOT / source).read_text(), source, 'exec'), NS)


class CostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'transcript.jsonl'

    def write(self, records):
        self.path.write_text(''.join(json.dumps(r) + '\n' for r in records))

    def test_claude_stream_dedup_cache_and_estimate(self):
        records = []
        for output in (3, 8):
            records.append(dict(type='assistant', timestamp='2026-11-14T00:01:00Z', message=dict(
                id='same', role='assistant', model='test', usage=dict(input_tokens=10, cache_read_input_tokens=20,
                cache_creation_input_tokens=5, output_tokens=output))))
        self.write(records)
        rates = {'test': dict(input=1, output=2, cache_read=3, cache_write=4)}
        row = NS['cost_usage'](self.path, 'claude', rates=rates)
        self.assertEqual((row['tokens_in'], row['tokens_out'], row['turn_tokens']), (35, 8, 43))
        self.assertAlmostEqual(row['dollars'], .000106)
        self.assertEqual(row['dollar_source'], 'estimate_profile_rates')
        self.assertIsNone(NS['cost_usage'](self.path, 'claude')['dollars'])

    def test_codex_dual_formats_cumulative_no_double_count(self):
        records = []
        for usage in (dict(input_tokens=100, cached_input_tokens=40, output_tokens=10),
                      dict(input_tokens=150, cached_input_tokens=60, output_tokens=20)):
            records.extend([dict(type='token_usage_record', payload=dict(thread_token_usage=usage)),
                            dict(type='event_msg', payload=dict(type='token_count', info=dict(total_token_usage=usage)))])
        self.write(records)
        row = NS['cost_usage'](self.path, 'codex')
        self.assertEqual((row['tokens_in'], row['tokens_out'], row['cache_read_tokens']), (150, 20, 60))
        self.assertIsNone(row['dollars'])

    def test_pi_recorded_dollars(self):
        self.write([dict(type='message', id='m', message=dict(role='assistant', usage=dict(
            input=12, output=3, cacheRead=5, cacheWrite=2, cost=dict(total=.125))))])
        row = NS['cost_usage'](self.path, 'pi')
        self.assertEqual((row['tokens_in'], row['tokens_out'], row['dollars']), (19, 3, .125))

    def test_exact_match_after_codex_instruction_user_and_partial_line(self):
        launch = 'a' * 32
        self.write([dict(type='response_item', payload=dict(role='user', content='AGENTS instructions')),
                    dict(type='response_item', payload=dict(role='user', content='Messaging protocol (not a task brief): --launch-id ' + launch))])
        with self.path.open('a') as f:
            f.write('{unfinished')
        with patch.dict(NS, cost_paths=lambda h: [self.path]):
            matches, errors = NS['cost_matches']([dict(launch_id=launch, harness='codex', created_at=0)])
        self.assertEqual(matches[launch], [str(self.path)])
        self.assertEqual(errors, [])

    def test_threshold_claims_once_before_send(self):
        state = dict(launch_id='a' * 32, name='test', starter={'block_id': 'test'})
        sent = []
        def update(root, launch, change):
            change(state)
        row = dict(threshold=dict(turn_seconds=.001, turn_tokens=100), current_turn_seconds=1,
                   turn_tokens=2, turn_active=True)
        with patch.dict(NS, update=update, now=lambda: 1000,
                        send=lambda *args: (sent.append(args) or (0, {})), transport_ack=lambda *args: True):
            NS['cost_flag']('root', state, row)
            NS['cost_flag']('root', state, row)
        self.assertEqual(len(sent), 1)
        self.assertEqual(state['cost_flag']['outcome'], 'acknowledged')

    def test_idle_does_not_warn_and_invalid_settings_rejected(self):
        NS['cost_flag']('root', dict(starter=True), dict(threshold=dict(turn_seconds=1, turn_tokens=1),
                        current_turn_seconds=0, turn_tokens=100, turn_active=False))
        with self.assertRaises(NS['Refusal']):
            NS['cost_settings']({'cost': {'turn_seconds': float('nan')}})

    def test_rivet_read_only_and_displayed_precision(self):
        class Result:
            returncode = 0
            stdout = 'call one · 4s · $0.125\ncall two · 1s · $0.250\n'
        calls = []
        with patch.object(NS['subprocess'], 'run', lambda argv, **kwargs: (calls.append(argv) or Result())):
            row = NS['cost_rivet']('fixture')
        self.assertEqual(calls, [['rv', 'show', 'fixture']])
        self.assertEqual(row['dollars'], .375)


@unittest.skipUnless(os.environ.get('REX_BIN') and os.environ.get('TEEREX_BIN'), 'live test needs explicit disposable Rex and teerex')
class CostLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / 'items/agents'))
        import test_agents
        cls.fixture_module = test_agents
        cls.rpc = classmethod(test_agents.AgentsTest.rpc.__func__)
        cls.stop_server = classmethod(test_agents.AgentsTest.stop_server.__func__)
        cls.run_cli = test_agents.AgentsTest.run_cli
        cls.record = test_agents.AgentsTest.record
        cls.launch = test_agents.AgentsTest.launch
        test_agents.AgentsTest.setUpClass.__func__(cls)

    def setUp(self):
        self.fixture_module.AgentsTest.setUp(self)

    def test_tiny_threshold_warns_starter_once_and_cost_lists_agent(self):
        self.settings['profiles']['probe']['cost'] = dict(turn_seconds=.000001)
        launched, packet = self.launch()
        self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
        launch = packet['launch_id']
        self.fixture_module.wait_for(lambda: (self.record(launch).get('cost_flag') or {}).get('outcome') == 'acknowledged')
        before = self.record(launch)['cost_flag']
        p, result = self.run_cli('cost', '--registry', str(self.registry), '--json')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(result['agents'][0]['launch_id'], launch)
        self.assertGreater(result['agents'][0]['wall_seconds'], 0)
        self.assertEqual(result['agents'][0]['flag']['outcome'], 'acknowledged')
        inputs = [e.get('payload', '') for e in self.fixture_module.events(self.starter_log) if e.get('event') == 'input']
        self.assertEqual(sum('COST ' in p for p in inputs), 1)
        self.assertEqual(self.record(launch)['cost_flag'], before)
        print('Tiny threshold: starter acknowledged one COST notice; agent remains running.', flush=True)


if __name__ == '__main__':
    unittest.main()
