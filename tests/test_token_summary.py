import json
from pathlib import Path
import shutil
import subprocess
import unittest
from test_reset_info import snapshot


class TokenSummaryTests(unittest.TestCase):
    def summarize(self, provider, models, key='24h'):
        windows = {window: models for window, _ in snapshot.TOKEN_WINDOWS}
        result = snapshot.summarize_tokens({provider: windows})
        return next(row['providers'][provider] for row in result['windows'] if row['key'] == key)

    def test_unknown_model_is_unavailable_and_reports_pricing_error(self):
        values = {'tokens': 1000, 'input': 900, 'cached': 0, 'output': 100}
        row = self.summarize('codex', {'codex-auto-review': values})
        self.assertEqual(row['tokens'], '1.0K')
        self.assertEqual(row['cost'], 'Unavailable')
        self.assertEqual(row['models'], [{'name': 'codex-auto-review', 'cost': 'Price unknown'}])
        self.assertEqual(row['note'], '1.0K tokens lack cost data')
        self.assertEqual(row['error'], 'Codex API equivalent (24h): codex-auto-review: pricing missing')

    def test_known_model_has_complete_total(self):
        values = {'tokens': 1000000, 'input': 900000, 'cached': 100000, 'output': 100000}
        row = self.summarize('codex', {'gpt-6-sol': values})
        self.assertEqual(row['cost'], '$2.62')
        self.assertEqual(row['note'], '')
        self.assertEqual(row['error'], '')

    def test_native_gpt61_sol_uses_published_rates(self):
        # https://developers.openai.com/api/docs/models/gpt-6.1-sol
        values = {'tokens': 979532, 'input': 974160, 'cached': 882816, 'output': 5372}
        self.assertAlmostEqual(snapshot.model_cost('codex', 'gpt-6.1-sol', values), 0.3246896)
        row = self.summarize('codex', {'gpt-6.1-sol': values})
        self.assertEqual(row['cost'], '$0.32')
        self.assertEqual(row['error'], '')

    def test_codex_total_only_counters_are_not_free(self):
        values = {'tokens': 4244785, 'input': 0, 'cached': 0, 'output': 0}
        for key, _ in snapshot.TOKEN_WINDOWS:
            with self.subTest(window=key):
                row = self.summarize('codex', {'gpt-6-sol': values}, key)
                self.assertEqual(row['tokens'], '4.2M')
                self.assertEqual(row['cost'], 'Unavailable')
                self.assertEqual(row['models'], [{'name': 'gpt-6-sol', 'cost': 'Unavailable'}])
                self.assertIn(f'Codex API equivalent ({key})', row['error'])
                self.assertIn('gpt-6-sol: input/output/cache breakdown missing for 4.2M tokens', row['error'])

    def test_cached_aggregate_with_missing_breakdowns_is_partial(self):
        values = {'tokens': 2000000, 'input': 900000, 'cached': 100000, 'output': 100000}
        row = self.summarize('codex', {'gpt-6-sol': values})
        self.assertEqual(row['cost'], '$2.62+ (partial)')
        self.assertEqual(row['models'][0]['cost'], '$2.62+ (partial)')
        self.assertEqual(row['note'], '1.0M tokens lack cost data')
        self.assertIn('breakdown missing for 1.0M tokens', row['error'])

    def test_known_and_unknown_models_show_only_a_partial_subtotal(self):
        values = {'tokens': 1000000, 'input': 900000, 'cached': 100000, 'output': 100000}
        row = self.summarize('codex', {'gpt-6-sol': values, 'unpriced-model': values})
        self.assertEqual(row['cost'], '$2.62+ (partial)')
        self.assertIn('unpriced-model: pricing missing', row['error'])

    def test_claude_cents_are_not_rounded_to_zero(self):
        values = {'input': 28, 'write5': 0, 'write1h': 6150, 'read': 23552, 'output': 601, 'write_unknown': 0, 'tokens': 30331}
        row = self.summarize('claude', {'claude-haiku-4-5-20251001': values})
        self.assertEqual(row['cost'], '$0.02')
        self.assertEqual(row['error'], '')

    def test_subcent_cost_and_empty_usage_are_distinct(self):
        values = {'tokens': 1000, 'input': 900, 'cached': 0, 'output': 100}
        self.assertEqual(self.summarize('codex', {'gpt-6-sol': values})['cost'], '<$0.01')
        self.assertEqual(self.summarize('codex', {})['cost'], '$0.00')
        self.assertEqual(self.summarize('codex', {})['error'], '')

    def test_zero_token_unknown_model_does_not_raise_pricing_error(self):
        row = self.summarize('claude', {'<synthetic>': {'tokens': 0}})
        self.assertEqual(row['error'], '')
        self.assertEqual(row['models'], [])

    def test_reported_grok_cost_can_be_partial(self):
        row = self.summarize('grok', {'grok-4.5': {'tokens': 2000, 'cost': 0.12, 'uncosted': 1000}})
        self.assertEqual(row['cost'], '$0.12+ (partial)')
        self.assertIn('cost data missing for 1.0K tokens', row['error'])

    def test_bottom_right_errors_follow_selected_window(self):
        self.assertIsNotNone(shutil.which('node'), 'Node is required to test the widget JavaScript')
        source = (Path(__file__).parents[1] / 'plasmoid/contents/ui/main.qml').read_text()
        errors = source[source.index('    function errors() {'):source.index('    function providerList(')]
        cost = source[source.index('    function cost(name) {'):source.rindex('\n}')]
        missing = {'tokens': 4244785, 'input': 0, 'cached': 0, 'output': 0}
        good = {'tokens': 1000000, 'input': 900000, 'cached': 100000, 'output': 100000}
        windows = {key: {'gpt-6-sol': missing if key == '24h' else good} for key, _ in snapshot.TOKEN_WINDOWS}
        data = snapshot.summarize_tokens({'codex': windows})
        script = f'''
const assert = require('node:assert/strict');
const snapshot = {{tokens: {json.dumps(data)}, errors: ['Quota lookup failed']}};
const providers = ['codex'];
let apiWindow = '24h';
const lastError = '', agentsError = '';
{errors}
{cost}
assert.ok(errors().startsWith('Quota lookup failed'));
assert.ok(errors().includes('Codex API equivalent (24h): gpt-6-sol: input/output/cache breakdown missing'));
apiWindow = '7d';
assert.equal(errors(), 'Quota lookup failed');
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
