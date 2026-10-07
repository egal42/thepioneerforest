CREATE TABLE pool_offers (
  id text PRIMARY KEY,
  request_id text NOT NULL UNIQUE REFERENCES pool_requests(id),
  partner_id text NOT NULL REFERENCES partner_profiles(id),
  title text NOT NULL,
  status text NOT NULL DEFAULT 'offered' CHECK (status IN ('offered', 'selected', 'withdrawn')),
  selected_key text,
  local_revision text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  selected_at timestamptz,
  UNIQUE (id, partner_id)
);

CREATE TABLE offer_choices (
  offer_id text NOT NULL REFERENCES pool_offers(id),
  choice_key text NOT NULL,
  project text NOT NULL,
  species text NOT NULL,
  common_name text NOT NULL DEFAULT '',
  project_note text NOT NULL DEFAULT '',
  trees integer NOT NULL CHECK (trees > 0),
  co2_kg numeric(18,3) NOT NULL CHECK (co2_kg > 0),
  price_pi numeric(18,7) NOT NULL CHECK (price_pi > 0),
  PRIMARY KEY (offer_id, choice_key)
);

ALTER TABLE pool_offers ADD CONSTRAINT selected_choice_exists
  FOREIGN KEY (id, selected_key) REFERENCES offer_choices(offer_id, choice_key)
  DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE portal_events DROP CONSTRAINT portal_events_event_type_check;
ALTER TABLE portal_events ADD CONSTRAINT portal_events_event_type_check
  CHECK (event_type IN ('request.created', 'share.created', 'offer.selected'));
