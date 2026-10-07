CREATE TABLE partner_access_requests (
 id uuid PRIMARY KEY, identification text NOT NULL, contact text NOT NULL, note text NOT NULL DEFAULT '',
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','handled')),
 created_at timestamptz NOT NULL DEFAULT now(), handled_at timestamptz
);
CREATE TABLE partner_access_limits (key text PRIMARY KEY, window_start timestamptz NOT NULL DEFAULT now(), count integer NOT NULL);
