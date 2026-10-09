import io
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from test_reset_info import snapshot


class ErrorReportingTests(unittest.TestCase):
    def test_more_than_three_ongoing_errors_are_capped(self):
        selected = ['claude', 'codex', 'kimi', 'grok', 'agy']
        data = {name: {'error': f'Oct 7 15:57 - {name}: lookup failed'} for name in selected}
        rates = {name: (1, 1) for name in selected}
        with tempfile.TemporaryDirectory() as directory, patch.object(snapshot, 'ERROR_CACHE', Path(directory) / 'errors.json'):
            result = snapshot.error_history(data, selected, rates)
            self.assertEqual(result, [data[name]['error'] + ' (1 of 1 lookups failed in 24h)' for name in selected[-3:]])
            self.assertEqual(len(snapshot.load(snapshot.ERROR_CACHE)['items']), 5)

    def test_widget_caps_combined_usage_agent_and_pricing_errors(self):
        self.assertIsNotNone(shutil.which('node'), 'Node is required to test the widget JavaScript')
        source = (Path(__file__).parents[1] / 'plasmoid/contents/ui/main.qml').read_text()
        function = source[source.index('    function errors() {'):source.index('    function providerList(')]
        script = f'''
const assert = require('node:assert/strict');
const snapshot = {{errors: ['Old Codex timeout', 'Claude DNS failure', 'Grok DNS failure']}};
const providers = ['codex'];
let lastError = '', agentsError = 'Agent counts unavailable';
let pricingError = 'Codex pricing missing';
function cost(name) {{ return {{error: pricingError}}; }}
const Qt = {{formatTime: () => '22:00'}};
{function}
assert.deepEqual(errors().split('\\n'), ['Grok DNS failure', pricingError, agentsError]);
lastError = 'No data';
assert.deepEqual(errors().split('\\n'), ['22:00 - Widget: No data', pricingError, agentsError]);
lastError = agentsError = pricingError = '';
assert.deepEqual(errors().split('\\n'), snapshot.errors);
snapshot.errors = [];
assert.equal(errors(), '');
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

    def test_widget_keeps_counts_with_missing_presence_error(self):
        source = (Path(__file__).parents[1] / 'plasmoid/contents/ui/main.qml').read_text()
        handler = source.split('id: agentsExecutable;', 1)[1].split('onNewData: function(sourceName, data) {', 1)[1].split('\n    Timer {', 1)[0]
        handler = handler.rsplit('\n    }', 1)[0]
        script = '''
const assert = require('node:assert/strict');
const root = {agentsSource: 'test'};
function disconnectSource() {}
function receive(sourceName, data) {
''' + handler + '''
receive('test', {stdout: JSON.stringify({working: 8, idle: 12, error: 'Missing PID 30'}), 'exit code': 0});
assert.equal(root.agents.working, 8);
assert.equal(root.agents.idle, 12);
assert.equal(root.agentsError, 'Missing PID 30');
root.agentsSource = 'test';
receive('test', {stdout: JSON.stringify({working: 9, idle: 11}), 'exit code': 0});
assert.equal(root.agentsError, '');
root.agentsSource = 'test';
receive('test', {stdout: JSON.stringify({error: 'Dashboard unavailable'}), 'exit code': 0});
assert.equal(root.agents, null);
assert.match(root.agentsError, /Dashboard unavailable/);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

    def test_http_status_is_visible(self):
        for status in (429, 500, 503):
            with HTTPError('https://example.com', status, 'error', {}, None) as error:
                message = snapshot.failure('Claude', error)
            self.assertIn(str(status), message)
        with HTTPError('https://example.com', 429, 'error', {}, None) as error:
            self.assertIn('rate limited', snapshot.failure('Claude', error))

    def test_ongoing_error_survives_history_expiry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(snapshot, 'ERROR_CACHE', Path(directory) / 'errors.json'):
            old = 'Sep 25 10:00 - Claude: rate limited (429)'
            snapshot.save(snapshot.ERROR_CACHE, {'items': [['claude', old, time.time() - 90000]], 'active': {'claude': snapshot.error_signature(old)}})
            current = 'Sep 26 13:35 - Claude: rate limited (429)'
            self.assertEqual(snapshot.error_history({'claude': {'error': current}}, ['claude'], {'claude': (1, 2)}), [current + ' (1 of 2 lookups failed in 24h)'])

    def test_current_errors_follow_history_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(snapshot, 'ERROR_CACHE', Path(directory) / 'errors.json'):
            old = 'Sep 26 10:00 - Claude: forbidden (403)'
            snapshot.error_history({'claude': {'error': old}}, ['claude'], {'claude': (1, 1)})
            current = 'Sep 26 13:35 - Claude: rate limited (429)'
            self.assertEqual(snapshot.error_history({'claude': {'error': current}}, ['claude'], {'claude': (1, 2)}), [old, current + ' (1 of 2 lookups failed in 24h)'])
            self.assertEqual(snapshot.error_history({'claude': {'error': current}}, ['claude'], {'claude': (1, 2)}), [old, current + ' (1 of 2 lookups failed in 24h)'])

    def test_http_error_body_detail_is_visible(self):
        body = io.BytesIO(b'{"title":"Error 1010: Access denied","error_name":"browser_signature_banned"}')
        with HTTPError('https://example.com', 403, 'Forbidden', {}, body) as error:
            self.assertEqual(snapshot.failure_reason(error), 'forbidden (403): browser_signature_banned')

    def test_lookup_log_counts_failures_per_provider(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(snapshot, 'LOOKUP_LOG', Path(directory) / 'lookups.jsonl'):
            snapshot.log_lookups({'claude': {'error': 'x'}, 'codex': {'available': True}}, ['claude', 'codex'])
            rates = snapshot.log_lookups({'claude': {'available': True}, 'codex': {'available': True}}, ['claude', 'codex'])
            self.assertEqual(rates, {'claude': (1, 2), 'codex': (0, 2)})
            self.assertEqual(len(snapshot.LOOKUP_LOG.read_text().splitlines()), 4)


if __name__ == '__main__':
    unittest.main()
