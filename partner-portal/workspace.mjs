// One projection for the signed Admin view and authenticated partner workspace.
export async function readPartnerWorkspace(db, partnerId) {
      const profiles = await db.sql`SELECT id, name, page_title, colors, logo_url, status FROM partner_profiles
        WHERE id = ${partnerId}`;
      const pools = await db.sql`SELECT p.id, p.name, p.basis, p.total_units, p.planted_trees, p.planted_co2_kg, p.project, p.species, p.proof_urls,
        COALESCE(SUM(s.units), 0)::text AS shared_units, COUNT(s.id)::text AS share_count
        FROM partner_pools p LEFT JOIN partner_shares s ON s.pool_id = p.id
        WHERE p.partner_id = ${partnerId} GROUP BY p.id ORDER BY p.created_at DESC`;
      const requests = await db.sql`SELECT r.id, r.requested_pi, r.basis, r.message,
        r.status, r.created_at, r.payment_reference, r.payment_checked_at, c.pool_id
        FROM pool_requests r LEFT JOIN pool_request_connections c ON c.request_id = r.id
        WHERE r.partner_id = ${partnerId} ORDER BY r.created_at DESC LIMIT 100`;
      const offers = await db.sql`SELECT id, request_id, title, status, selected_key
        FROM pool_offers WHERE partner_id = ${partnerId} ORDER BY created_at DESC LIMIT 100`;
      const choices = await db.sql`SELECT c.offer_id, c.choice_key, c.project, c.species,
        c.common_name, c.project_note, c.trees, c.co2_kg, c.price_pi
        FROM offer_choices c JOIN pool_offers o ON o.id = c.offer_id
        WHERE o.partner_id = ${partnerId} ORDER BY c.offer_id, c.price_pi`;
      const shares = await db.sql`SELECT s.id, s.pioneer_name, s.units, s.reason, s.created_at, s.pool_id, p.name AS pool_name, p.basis
        FROM partner_shares s JOIN partner_pools p ON p.id = s.pool_id
        WHERE s.partner_id = ${partnerId} AND p.partner_id = ${partnerId}
        ORDER BY s.created_at DESC LIMIT 100`;
      return { profile: profiles[0], pools, requests, offers, choices, shares };
}
