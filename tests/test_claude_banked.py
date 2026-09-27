import datetime as dt
import unittest
from unittest.mock import patch
from test_reset_info import snapshot


class ClaudeBankedTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 28, tzinfo=dt.timezone.utc)

    def balance(self, grants):
        with patch.object(snapshot, 'now', return_value=self.now):
            return snapshot.claude_banked({'cedar_ember': {'grants': grants}})

    def test_count_and_soonest_expiry(self):
        value = self.balance([{'resets_left': 1, 'ends_at': '2026-10-22T16:00:00Z'}, {'resets_left': 2, 'ends_at': None}])
        self.assertTrue(value.startswith('3 | expires '))

    def test_spent_and_expired_grants_excluded(self):
        self.assertEqual(self.balance([{'resets_left': 0}, {'resets_left': 1, 'ends_at': '2026-09-20T16:00:00Z'}]), '0')

    def test_absent_is_not_zero(self):
        self.assertEqual(snapshot.claude_banked({}), 'unavailable')
        self.assertEqual(self.balance([]), '0')

    def test_malformed_grants_report_errors(self):
        for grant in ({'resets_left': -1}, {'resets_left': '1'}, {'resets_left': 1, 'ends_at': 'bad'}):
            with self.assertRaises(RuntimeError): self.balance([grant])

    def test_each_refresh_uses_current_account_credentials(self):
        base = {'five_hour': {}, 'seven_day': {}, 'limits': []}
        responses = [{**base, 'cedar_ember': {'grants': [{'resets_left': 1}]}}, {**base, 'cedar_ember': {'grants': []}}]
        with patch.object(snapshot, 'claude_token', side_effect=['first-account-token', 'second-account-token']), patch.object(snapshot, 'http', side_effect=responses) as http, patch.object(snapshot, 'load', return_value={}):
            self.assertEqual(snapshot.claude()['banked'], '1')
            self.assertEqual(snapshot.claude()['banked'], '0')
        for call, token in zip(http.call_args_list, ['first-account-token', 'second-account-token']):
            self.assertTrue(call.args[0].endswith('/api/oauth/usage?cedar_ember=1'))
            self.assertEqual(call.args[1]['Authorization'], 'Bearer ' + token)
