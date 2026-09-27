import unittest
from test_reset_info import snapshot


class TokenSummaryTests(unittest.TestCase):
    def test_unknown_model_is_visible_and_total_marked_partial(self):
        values = {'tokens': 1000, 'input': 900, 'cached': 0, 'output': 100}
        windows = {key: {'codex-auto-review': values} for key, _ in snapshot.TOKEN_WINDOWS}
        result = snapshot.summarize_tokens({'codex': windows})
        row = result['windows'][0]['providers']['codex']
        self.assertEqual(row['tokens'], '1.0K')
        self.assertTrue(row['cost'].endswith('+'))
        self.assertEqual(row['models'], [{'name': 'codex-auto-review', 'cost': 'Price unknown'}])
        self.assertEqual(row['note'], '1.0K tokens lack cost data')

    def test_known_model_has_complete_total(self):
        values = {'tokens': 1000, 'input': 900, 'cached': 0, 'output': 100}
        windows = {key: {'gpt-6-sol': values} for key, _ in snapshot.TOKEN_WINDOWS}
        row = snapshot.summarize_tokens({'codex': windows})['windows'][0]['providers']['codex']
        self.assertFalse(row['cost'].endswith('+'))
        self.assertEqual(row['note'], '')
