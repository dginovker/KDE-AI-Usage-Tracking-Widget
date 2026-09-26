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
            self.assertEqual(snapshot.error_history({'claude': {'error': current}}, ['claude']), [current])

    def test_current_errors_precede_history_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(snapshot, 'ERROR_CACHE', Path(directory) / 'errors.json'):
            old = 'Sep 26 10:00 - Claude: forbidden (403)'
            snapshot.error_history({'claude': {'error': old}}, ['claude'])
            current = 'Sep 26 13:35 - Claude: rate limited (429)'
            self.assertEqual(snapshot.error_history({'claude': {'error': current}}, ['claude']), [current, old])
            self.assertEqual(snapshot.error_history({'claude': {'error': current}}, ['claude']), [current, old])


if __name__ == '__main__':
    unittest.main()
