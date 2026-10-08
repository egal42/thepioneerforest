import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'partner-id-update' / 'payload' / 'ui'))
spec = importlib.util.spec_from_file_location('website_publication', ROOT / 'website-data-update' / 'payload' / 'ui' / 'website_publication.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WebsitePublicationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'publication.json'
        self.config = {'min_co2_per_pi': 20, 'tpf_addition_percent': 25}
        self.online = {'schema': 'tpf_website_summary_v1', 'minimumCo2KgPerPi': '20', 'impact': None, 'revision': None, 'publishedAt': None}
        self.calls = []
        def signed(origin, secret, method, path, payload=None):
            self.calls.append((method, payload))
            if method == 'GET': return self.online
            return {**payload, 'revision': 'a' * 64, 'publishedAt': '2026-10-08T12:00:00Z'}
        self.patch = patch.object(module, 'signed_request', signed)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def handle(self, form, config=None, environment='mainnet'):
        return module.handle_form(form, self.path, config or self.config, environment, 'https://isolated.invalid', 'test-secret')

    def review(self):
        return self.handle({'action': 'review', 'estimated_co2_kg': '20.125', 'trees': '0', 'as_of': '2026-10-01', 'review_note': 'private note'})

    def test_review_and_publish_whitelist(self):
        self.assertTrue(self.review()['ok'])
        screen = module.screen(self.path, self.config, 'mainnet', 'https://isolated.invalid', 'test-secret')
        self.assertTrue(screen['can_publish'])
        self.assertTrue(self.handle({'action': 'publish', 'confirmed': 'yes', 'draft_revision': screen['review']['revision']})['ok'])
        sent = self.calls[-1][1]
        self.assertEqual(sent['impact']['trees'], '0')
        self.assertEqual(set(sent), {'schema', 'environment', 'minimumCo2KgPerPi', 'impact', 'expectedRevision'})
        self.assertNotIn('private', json.dumps(sent))
        self.assertIn('private note', self.path.read_text())

    def test_settings_change_requires_new_review(self):
        self.review()
        state = module._read(self.path)
        self.assertFalse(self.handle({'action': 'publish', 'confirmed': 'yes', 'draft_revision': state['reviewed_revision']}, config={'min_co2_per_pi': 21})['ok'])
        self.assertFalse(any(method == 'POST' for method, _ in self.calls))

    def test_mainnet_review_and_confirmation_are_required(self):
        self.assertFalse(self.handle({'action': 'publish', 'confirmed': 'yes'})['ok'])
        self.assertFalse(self.handle({'action': 'review'}, environment='sandbox')['ok'])
        self.assertFalse(self.handle({'action': 'review'}, environment='testnet')['ok'])
        self.assertFalse(self.path.exists())

    def test_invalid_draft_is_preserved_but_not_publishable(self):
        self.review()
        self.assertFalse(self.handle({'action': 'review', 'trees': 'wrong'})['ok'])
        state = module._read(self.path)
        self.assertEqual(state['draft']['trees'], 'wrong')
        self.assertIsNone(state['reviewed_revision'])

    def test_existing_totals_cannot_be_cleared_by_empty_form(self):
        self.online = {**self.online, 'impact': {'estimatedCo2Kg': '20', 'trees': '1', 'asOf': '2026-10-01'}, 'revision': 'a' * 64}
        self.assertFalse(self.handle({'action': 'review'})['ok'])
        self.assertFalse(any(method == 'POST' for method, _ in self.calls))

    def test_connection_failure_blocks_publication(self):
        self.review()
        with patch.object(module, 'signed_request', side_effect=module.SyncError('not available')):
            screen = module.screen(self.path, self.config, 'mainnet', 'https://isolated.invalid', 'test-secret')
        self.assertFalse(screen['can_publish'])


if __name__ == '__main__': unittest.main()
