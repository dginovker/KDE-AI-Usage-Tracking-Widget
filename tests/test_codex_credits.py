import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from test_reset_info import snapshot

FAKE_APP_SERVER = '''#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request: continue
    with open(sys.argv[0] + ".log", "a") as log: log.write(line)
    brief = (request.get("params") or {}).get("excludeResetCreditDetails")
    details = None if brief else [{"status": "available", "expiresAt": 4102444800}]
    result = {} if request["method"] == "initialize" else {"rateLimits": {}, "rateLimitResetCredits": {"availableCount": 2, "credits": details}}
    print(json.dumps({"id": request["id"], "result": result}), flush=True)
'''


class CodexCreditTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.binary = Path(directory.name) / 'codex'
        self.binary.write_text(FAKE_APP_SERVER)
        os.chmod(self.binary, 0o755)

    def lookup(self, known):
        result, issue = snapshot.codex_attempt(str(self.binary), time.monotonic() + 5, known)
        self.assertIsNone(issue)
        reads = [json.loads(line) for line in Path(str(self.binary) + '.log').read_text().splitlines()][1:]
        return result['rateLimitResetCredits'], [read.get('params') for read in reads]

    def test_unchanged_count_reuses_known_expiries(self):
        known = {'availableCount': 2, 'credits': [{'status': 'available', 'expiresAt': 4000000000}]}
        credits, reads = self.lookup(known)
        self.assertEqual(credits, known)
        self.assertEqual(reads, [{'excludeResetCreditDetails': True}])

    def test_changed_or_unknown_count_refetches_details(self):
        for known in ({'availableCount': 1, 'credits': []}, None):
            Path(str(self.binary) + '.log').unlink(missing_ok=True)
            credits, reads = self.lookup(known)
            self.assertEqual(credits['credits'], [{'status': 'available', 'expiresAt': 4102444800}])
            self.assertEqual(reads, [{'excludeResetCreditDetails': True}, None])


if __name__ == '__main__':
    unittest.main()
