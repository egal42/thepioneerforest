ALTER TABLE partner_profiles ADD COLUMN login_id text;
CREATE TABLE partner_login_ids (
  login_id text PRIMARY KEY,
  partner_id text NOT NULL REFERENCES partner_profiles(id) ON DELETE CASCADE
);
INSERT INTO partner_login_ids (login_id,partner_id) SELECT id,id FROM partner_profiles;
INSERT INTO partner_login_ids (login_id,partner_id)
 SELECT 'gpm',id FROM partner_profiles WHERE id='global-pi-market';
UPDATE partner_profiles SET login_id='gpm' WHERE id='global-pi-market';
