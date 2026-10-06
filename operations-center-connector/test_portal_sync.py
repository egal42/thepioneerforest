import json
import tempfile
import unittest
from pathlib import Path

from portal_sync import build_payload, pull_events, send_offer


class SyncTests(unittest.TestCase):
    def test_draft_partner_has_no_pool_or_private_notes(self):
        partner = {"schema": "tpf_partner_v1", "id": "gpm", "name": "Global Pi Market",
                   "section_title": "GPM", "status": "draft", "colors": {},
                   "internal_notes": "private"}
        payload = build_payload(partner, [], Path('.'), None)
        self.assertIsNone(payload["setup"])
        self.assertNotIn("internal_notes", json.dumps(payload))

    def test_partner_logo_is_carried_without_internal_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'gpm.png').write_bytes(bytes.fromhex('89504e470d0a1a0a'))
            partner = {"schema": "tpf_partner_v1", "id": "gpm", "name": "GPM",
                "section_title": "GPM", "status": "draft", "colors": {}, "logo_file": "gpm.png"}
            payload = build_payload(partner, [], Path(directory), None)
            self.assertEqual(payload['logo']['contentType'], 'image/png')
            self.assertTrue(payload['logo']['data'])

    def test_events_are_saved_before_cursor_moves(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return b'{"events":[{"id":1,"event_type":"request.created"}],"next":1}'
        with tempfile.TemporaryDirectory() as directory:
            count, cursor = pull_events("https://example.org", "x" * 32,
                                        directory, opener=lambda *a, **kw: Reply())
            self.assertEqual((count, cursor), (1, 1))
            self.assertTrue((Path(directory) / "0000000000000001.json").exists())
            self.assertEqual((Path(directory) / "cursor.txt").read_text(), "1")

    def test_offer_handoff_excludes_internal_costs(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return b'{"offerId":"abc"}'
        seen = []
        def opener(request, timeout):
            seen.append(request.data.decode())
            return Reply()
        offer = {"schema": "tpf_partner_offer_v1", "id": "a" * 32,
                 "status": "ready", "name": "GPM pool", "search": {"basis": "co2"},
                 "pricing_settings": {"tpf_addition_percent": 25},
                 "choices": [{"key": "1:2", "project": "Forest", "species": "Tree", "trees": 10,
                              "co2_kg": 1000, "partner_price_pi": 100,
                              "planting_cost_eur": 7, "pricing": {"secret": "internal"}}]}
        send_offer("https://example.org", "x" * 32, "gpm", "1" * 36, offer, opener)
        self.assertIn('partner_price_pi', seen[0])
        self.assertNotIn('planting_cost_eur', seen[0])
        self.assertNotIn('pricing_settings', seen[0])


if __name__ == "__main__": unittest.main()
