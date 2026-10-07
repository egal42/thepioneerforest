-- Preserve the two OMC events when promoting the existing preview ledger.
-- Netlify's row-copy tool cannot insert GENERATED ALWAYS identity values.
-- Only add events when their underlying records exist; never overwrite history.
INSERT INTO portal_events (id, partner_id, event_type, entity_id, created_at)
OVERRIDING SYSTEM VALUE
SELECT 1, partner_id, 'request.created', id, created_at
FROM pool_requests
WHERE id = '20a1721a-bf13-4067-9c36-b3cb50bfcfce' AND partner_id = 'omc'
ON CONFLICT (event_type, entity_id) DO NOTHING;

INSERT INTO portal_events (id, partner_id, event_type, entity_id, created_at)
OVERRIDING SYSTEM VALUE
SELECT 2, partner_id, 'share.created', id, created_at
FROM partner_shares
WHERE id = 'd436e4af-1393-4e5d-8e04-ef4d9e81ac58' AND partner_id = 'omc'
ON CONFLICT (event_type, entity_id) DO NOTHING;

-- Explicit identity imports must advance the sequence before another event.
SELECT setval(pg_get_serial_sequence('portal_events', 'id'),
  GREATEST((SELECT last_value FROM portal_events_id_seq),
           COALESCE((SELECT MAX(id) FROM portal_events), 1)),
  (SELECT is_called FROM portal_events_id_seq) OR EXISTS (SELECT 1 FROM portal_events));
