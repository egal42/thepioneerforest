-- Online partner ledger. The Operations Center remains the source for verified planting.
CREATE TABLE partner_profiles (
  id text PRIMARY KEY CHECK (id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  name text NOT NULL,
  page_title text NOT NULL,
  tagline text NOT NULL DEFAULT '',
  introduction text NOT NULL DEFAULT '',
  colors jsonb NOT NULL,
  logo_url text,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active')),
  local_revision text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE partner_accounts (
  partner_id text PRIMARY KEY REFERENCES partner_profiles(id),
  password_hash text NOT NULL,
  password_changed_at timestamptz NOT NULL DEFAULT now(),
  disabled_at timestamptz
);

CREATE TABLE partner_sessions (
  token_hash text PRIMARY KEY,
  partner_id text NOT NULL REFERENCES partner_accounts(partner_id),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX partner_sessions_expiry ON partner_sessions(expires_at);

CREATE TABLE pool_requests (
  id text PRIMARY KEY,
  partner_id text NOT NULL REFERENCES partner_profiles(id),
  requested_pi numeric(18,7) NOT NULL CHECK (requested_pi > 0),
  basis text NOT NULL CHECK (basis IN ('trees', 'co2')),
  message text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'offered', 'selected', 'payment_pending', 'planting_pending', 'connected', 'cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pool_requests_partner ON pool_requests(partner_id, created_at DESC);

CREATE TABLE partner_pools (
  id text PRIMARY KEY,
  partner_id text NOT NULL REFERENCES partner_profiles(id),
  name text NOT NULL,
  basis text NOT NULL CHECK (basis IN ('trees', 'co2')),
  total_units numeric(18,3) NOT NULL CHECK (total_units > 0),
  planted_trees integer NOT NULL CHECK (planted_trees >= 0),
  planted_co2_kg numeric(18,3) NOT NULL CHECK (planted_co2_kg >= 0),
  project text NOT NULL DEFAULT '',
  species text NOT NULL DEFAULT '',
  proof_urls jsonb NOT NULL,
  local_revision text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (jsonb_typeof(proof_urls) = 'array'),
  UNIQUE (id, partner_id)
);
CREATE INDEX partner_pools_partner ON partner_pools(partner_id);

-- A share never changes after creation. Sum shares against the locked pool row
-- in one database transaction before inserting another share.
CREATE TABLE partner_shares (
  id text PRIMARY KEY,
  partner_id text NOT NULL REFERENCES partner_profiles(id),
  pool_id text NOT NULL,
  pioneer_name text NOT NULL,
  units numeric(18,3) NOT NULL CHECK (units > 0),
  reason text NOT NULL DEFAULT '',
  idempotency_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (partner_id, idempotency_key),
  FOREIGN KEY (pool_id, partner_id) REFERENCES partner_pools(id, partner_id)
);
CREATE INDEX partner_shares_pool ON partner_shares(pool_id, created_at DESC);
CREATE INDEX partner_shares_partner ON partner_shares(partner_id, created_at DESC);

-- Every local pull acknowledges a durable event ID; retrying the same event is safe.
CREATE TABLE portal_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  partner_id text NOT NULL REFERENCES partner_profiles(id),
  event_type text NOT NULL CHECK (event_type IN ('request.created', 'share.created')),
  entity_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (event_type, entity_id)
);
