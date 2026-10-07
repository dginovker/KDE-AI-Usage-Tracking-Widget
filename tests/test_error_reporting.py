import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from test_reset_info import snapshot


class ErrorReportingTests(unittest.TestCase):
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
