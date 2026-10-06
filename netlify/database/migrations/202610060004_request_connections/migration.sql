-- A selected offer is fulfilled only by one verified, published partner pool.
CREATE TABLE pool_request_connections (
  request_id text PRIMARY KEY REFERENCES pool_requests(id),
  partner_id text NOT NULL REFERENCES partner_profiles(id),
  pool_id text NOT NULL UNIQUE,
  offer_id text NOT NULL,
  choice_key text NOT NULL,
  connected_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (pool_id, partner_id) REFERENCES partner_pools(id, partner_id),
  FOREIGN KEY (offer_id, choice_key) REFERENCES offer_choices(offer_id, choice_key)
);
