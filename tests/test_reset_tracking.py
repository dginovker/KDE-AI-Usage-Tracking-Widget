import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_reset_info import snapshot


class ResetTrackingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'resets.json'
        patcher = patch.object(snapshot, 'RESET_HISTORY', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def observe(self, at, used, reset, account='account-a'):
        return snapshot.track_codex_reset(account, {'used': used, 'reset': reset}, at)

    def events(self, account='account-a'):
        return json.loads(self.path.read_text())[account]['events']

    def test_early_reset_records_interval_and_evidence_once(self):
        self.observe(1000, 62, 5000)
        result = self.observe(1600, 2, 600000)
        self.assertIn('(early)', result)
        event = self.events()[0]
        self.assertEqual((event['after'], event['by']), (1000, 1600))
        self.assertEqual((event['used_before'], event['used_after']), (62, 2))
        self.observe(2200, 3, 600000)
        self.assertEqual(len(self.events()), 1)

    def test_scheduled_boundary_in_gap_is_not_called_early(self):
        self.observe(1000, 62, 1500)
        self.observe(1600, 2, 600000)
        self.assertEqual(self.events()[0]['kind'], 'scheduled window')

    def test_account_changes_do_not_create_resets(self):
        self.observe(1000, 62, 5000)
        self.observe(1600, 2, 600000, account='account-b')
        self.assertEqual(self.events(), [])
        self.assertEqual(self.events('account-b'), [])

    def test_usage_correction_and_boundary_only_change_do_not_count(self):
        self.observe(1000, 62, 5000)
        self.observe(1600, 60, 5000)
        self.observe(2200, 60, 600000)
        self.assertEqual(self.events(), [])

    def test_old_observation_does_not_replace_baseline(self):
        self.observe(1600, 62, 5000)
        self.observe(1000, 2, 600000)
        self.assertEqual(json.loads(self.path.read_text())['account-a']['previous']['at'], 1600)
        self.assertEqual(self.events(), [])

    def test_corrupt_history_is_reported_and_preserved(self):
        self.path.write_text('broken')
        with self.assertRaises(ValueError):
            self.observe(1000, 62, 5000)
        self.assertEqual(self.path.read_text(), 'broken')


if __name__ == '__main__':
    unittest.main()
