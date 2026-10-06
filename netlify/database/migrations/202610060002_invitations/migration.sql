CREATE TABLE partner_invitations (
  token_hash text PRIMARY KEY,
  partner_id text NOT NULL REFERENCES partner_profiles(id),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX partner_invitations_partner ON partner_invitations(partner_id, expires_at);
