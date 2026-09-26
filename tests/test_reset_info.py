import datetime as dt
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('snapshot', Path(__file__).resolve().parents[1] / 'plasmoid/contents/code/widget_snapshot.py')
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class ResetInfoTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 26, 3, tzinfo=dt.timezone.utc)
        self.forecast = {'updated_at': self.now.isoformat(), 'official_signal': {
            'at': (self.now - dt.timedelta(hours=1)).isoformat(), 'url': 'https://example.com/announcement'}}

    def result(self, history=None):
        def http(url, *args):
            if url.endswith('forecast'):
                if isinstance(self.forecast, Exception):
                    raise self.forecast
                return self.forecast
            return {'events': []} if history is None else history
        with patch.object(snapshot, 'http', side_effect=http), patch.object(snapshot, 'now', return_value=self.now):
            return snapshot.reset_info()

    def test_announced_without_deadline(self):
        data = self.result()
        self.assertGreater(data['alert_until'], self.now.timestamp())
        self.assertIn('timing unconfirmed', data['next'])
        self.assertEqual(data['announcement_url'], 'https://example.com/announcement')

    def test_probabilities_never_alert(self):
        self.forecast.update(official_signal=None, probabilities={'rounded_24h': 95, 'rounded_48h': 99})
        self.assertNotIn('alert_until', self.result())

    def test_stale_and_network_errors_are_visible(self):
        self.forecast['updated_at'] = (self.now - dt.timedelta(hours=3)).isoformat()
        self.assertIn('error', self.result())
        self.forecast = TimeoutError('timed out')
        self.assertIn('timed out', self.result()['error'])

    def test_old_promise_expires(self):
        self.forecast['official_signal']['at'] = (self.now - dt.timedelta(days=2)).isoformat()
        data = self.result()
        self.assertLess(data['alert_until'], self.now.timestamp())
        self.assertIn('completion unverified', data['next'])

    def test_explicit_deadline_and_completion(self):
        deadline = self.now + dt.timedelta(hours=4)
        self.forecast['official_signal']['window'] = {'end_at': deadline.isoformat()}
        self.assertEqual(self.result()['alert_until'], deadline.timestamp())
        self.forecast['last_reset_at'] = self.now.isoformat()
        self.assertEqual(self.result()['alert_until'], 0)

    def test_invalid_history_does_not_hide_announcement(self):
        data = self.result({'events': None})
        self.assertIn('history_error', data)
        self.assertGreater(data['alert_until'], self.now.timestamp())


if __name__ == '__main__':
    unittest.main()
