import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from test_reset_info import snapshot


class PiTokenUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pi = self.root / 'pi'
        self.codex = self.root / 'codex'
        self.claude = self.root / 'claude'
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'PI_CODING_AGENT_DIR': str(self.pi), 'PI_CODING_AGENT_SESSION_DIR': str(self.pi / 'sessions'), 'CODEX_HOME': str(self.codex), 'CLAUDE_HOME': str(self.claude)}).start()
        patch.object(snapshot, 'CACHE', self.root / 'cache').start()
        self.stamp = int(time.time() * 1000)

    def write_lines(self, path, entries):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(entry) + '\n' for entry in entries))
        return path

    def usage(self, **overrides):
        return {'input': 900, 'output': 100, 'cacheRead': 2000, 'cacheWrite': 0, 'totalTokens': 3000, 'cost': {'total': 0.0032}, **overrides}

    def message(self, provider='openai', model='gpt-6.1-sol', **overrides):
        return {'type': 'message', 'id': 'entry1', 'timestamp': self.stamp, 'message': {'role': 'assistant', 'provider': provider, 'model': model, 'timestamp': self.stamp, 'usage': self.usage(), 'responseId': 'response1', **overrides}}

    def session(self, name='main', entries=None):
        return self.write_lines(self.pi / 'sessions' / f'{name}.jsonl', [{'type': 'session', 'id': name}, *(entries or [self.message()])])

    def scan(self, providers=('codex', 'claude')):
        return snapshot.scan_token_usage(providers)

    def row(self, result, provider='codex'):
        return snapshot.summarize_tokens({provider: result[provider]})['windows'][3]['providers'][provider]

    def test_reads_pi_cost_for_model_missing_from_widget_price_table(self):
        self.session(entries=[self.message(model='unpriced-pi-model')])
        row = self.row(self.scan())
        self.assertEqual(row['tokens'], '3.0K')
        self.assertEqual(row['cost'], '<$0.01')
        self.assertEqual(row['error'], '')

    def test_copied_forks_and_artifact_transcripts_do_not_duplicate_usage(self):
        self.session()
        self.session('fork')
        self.write_lines(self.pi / 'sessions' / 'subagent-artifacts' / 'transcript.jsonl', [self.message()])
        data = self.scan()
        self.assertEqual(data['codex']['24h']['gpt-6.1-sol']['tokens'], 3000)
        self.assertEqual(data['codex']['24h']['gpt-6.1-sol']['cost'], 0.0032)
        cached = self.scan()
        self.assertEqual(data['codex'], cached['codex'])
        self.assertEqual(cached['scan'][0]['parsed'], 0)

    def test_cache_warming_and_compaction_usage_are_counted(self):
        entries = [
            {'type': 'model_change', 'id': 'select', 'provider': 'openai', 'modelId': 'gpt-6.1-sol'},
            self.message(),
            {'type': 'compaction', 'id': 'compact', 'timestamp': self.stamp, 'usage': self.usage()},
            {'type': 'usage', 'id': 'warm', 'kind': 'cache_warm', 'timestamp': self.stamp, 'provider': 'anthropic', 'model': 'claude-opus-5-5', 'usage': self.usage()},
        ]
        self.session(entries=entries)
        data = self.scan()
        self.assertEqual(data['codex']['24h']['gpt-6.1-sol']['tokens'], 6000)
        self.assertEqual(data['claude']['24h']['claude-opus-5-5']['tokens'], 3000)

    def test_pi_and_native_usage_for_same_model_are_added_without_double_pricing(self):
        self.session(entries=[self.message(model='gpt-6-sol')])
        self.write_lines(self.codex / 'sessions' / 'native.jsonl', [
            {'type': 'turn_context', 'payload': {'model': 'gpt-6-sol'}},
            {'type': 'event_msg', 'timestamp': self.stamp, 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': 2900, 'cached_input_tokens': 2000, 'output_tokens': 100, 'total_tokens': 3000}}}},
        ])
        data = self.scan()
        values = data['codex']['24h']['gpt-6-sol']
        self.assertEqual(values['tokens'], 6000)
        self.assertAlmostEqual(snapshot.model_cost('codex', 'gpt-6-sol', values), 0.0064)
        self.assertEqual(self.row(data)['error'], '')

    def test_known_pi_cost_and_unpriced_native_model_report_only_native_missing_tokens(self):
        values = {'tokens': 6000, 'reported_tokens': 3000, 'cost': 0.0032, 'input': 2900, 'cached': 2000, 'output': 100}
        windows = {key: {'unpriced-native-model': values} for key, _ in snapshot.TOKEN_WINDOWS}
        row = self.row({'codex': windows})
        self.assertEqual(row['cost'], '<$0.01+ (partial)')
        self.assertEqual(row['note'], '3.0K tokens lack cost data')

    def test_claude_native_and_pi_import_share_response_id(self):
        usage = self.usage(input=1, output=100, cacheRead=1000, cacheWrite=100, totalTokens=1201, cost={'total': 0.01})
        self.session(entries=[self.message('anthropic', 'claude-opus-5-5', usage=usage, responseId='msg_native')])
        self.write_lines(self.claude / 'projects' / 'native.jsonl', [{'type': 'assistant', 'timestamp': self.stamp, 'message': {'id': 'msg_native', 'model': 'claude-opus-5-5', 'usage': {'input_tokens': 1, 'output_tokens': 100, 'cache_read_input_tokens': 1000, 'cache_creation_input_tokens': 100}}}])
        data = self.scan()
        self.assertEqual(data['claude']['24h']['claude-opus-5-5']['tokens'], 1201)
        self.assertEqual(self.row(data, 'claude')['cost'], '$0.01')

    def test_imported_zero_cost_claude_messages_use_complete_native_breakdown(self):
        usage = self.usage(cost={'total': 0}, cacheWrite=100, cacheWrite1h=60, totalTokens=3100)
        path = self.session(entries=[self.message('anthropic', 'claude-opus-5-5', usage=usage)])
        values = next(snapshot.pi_events(path, 'claude'))[3]
        self.assertEqual((values['write5'], values['write1h']), (40, 60))
        self.assertAlmostEqual(snapshot.model_cost('claude', 'claude-opus-5-5', values), 0.00668)

    def test_codex_import_registry_excludes_replayed_claude_and_invalidates_cached_file(self):
        imported_id = '01234567-89ab-cdef-0123-456789abcdef'
        path = self.codex / 'sessions' / f'rollout-2026-10-07T12-01-24-{imported_id}.jsonl'
        self.write_lines(path, [
            {'type': 'session_meta', 'payload': {'id': imported_id, 'model': 'gpt-6-sol', 'originator': 'Codex Desktop'}},
            {'type': 'event_msg', 'timestamp': self.stamp, 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'total_tokens': 4244785, 'input_tokens': 0, 'output_tokens': 0, 'cached_input_tokens': 0}}}},
        ])
        self.assertEqual(self.row(self.scan())['tokens'], '4.2M')
        snapshot.save(self.codex / 'external_agent_session_imports.json', {'records': [{'imported_thread_id': imported_id, 'source_path': '/claude/original.jsonl'}]})
        self.session()
        data = self.scan()
        self.assertNotIn('gpt-6-sol', data['codex']['24h'])
        self.assertEqual(self.row(data)['tokens'], '3.0K')
        self.assertEqual(self.row(data)['error'], '')

    def test_malformed_import_registry_fails_instead_of_silently_counting_imports(self):
        self.codex.mkdir()
        (self.codex / 'external_agent_session_imports.json').write_text('{broken')
        with self.assertRaises(json.JSONDecodeError): snapshot.codex_sources()
