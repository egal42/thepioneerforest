import { getDatabase } from '@netlify/database';

const json = (data, status = 200) => new Response(JSON.stringify(data), { status,
  headers: { 'content-type': 'application/json; charset=utf-8',
    'cache-control': 'public, max-age=30' } });

export default async function handler(request) {
  if (request.method !== 'GET') return json({ error: 'Method not allowed' }, 405);
  const parts = new URL(request.url).pathname.split('/').filter(Boolean);
  const partnerId = parts[2];
  const recordId = parts[3] === 'records' ? parts[4] : null;
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '')
      || (recordId && !/^[a-zA-Z0-9_-]{1,100}$/.test(recordId))) return json({ error: 'Not found' }, 404);
  try {
    const db = getDatabase();
    const profiles = await db.sql`SELECT id, name, page_title, tagline, introduction, colors, logo_url
      FROM partner_profiles WHERE id = ${partnerId} AND status = 'active'`;
    if (!profiles.length) return json({ error: 'Not found' }, 404);
    if (parts[3] === 'branding') return json({ profile: profiles[0] });
    const pools = await db.sql`SELECT p.id, p.name, p.basis, p.total_units, p.planted_trees,
      p.planted_co2_kg, p.project, p.species, p.proof_urls,
      COALESCE(SUM(s.units),0)::text AS shared_units, COUNT(s.id)::text AS share_count
      FROM partner_pools p LEFT JOIN partner_shares s ON s.pool_id = p.id
      WHERE p.partner_id = ${partnerId} GROUP BY p.id ORDER BY p.created_at DESC`;
    if (recordId) {
      const records = await db.sql`SELECT s.id, s.pool_id, s.pioneer_name, s.units,
        s.reason, s.created_at, p.name AS pool_name, p.basis, p.proof_urls
        FROM partner_shares s JOIN partner_pools p ON p.id = s.pool_id
        WHERE s.id = ${recordId} AND s.partner_id = ${partnerId} AND p.partner_id = ${partnerId}`;
      return records.length ? json({ profile: profiles[0], record: records[0] })
        : json({ error: 'Not found' }, 404);
    }
    const records = await db.sql`SELECT s.id, s.pool_id, s.pioneer_name, s.units,
      s.reason, s.created_at, p.name AS pool_name, p.basis
      FROM partner_shares s JOIN partner_pools p ON p.id = s.pool_id
      WHERE s.partner_id = ${partnerId} AND p.partner_id = ${partnerId}
      ORDER BY s.created_at DESC LIMIT 200`;
    return json({ profile: profiles[0], pools, records });
  } catch (error) {
    console.error('public partner error', error);
    return json({ error: 'Server error' }, 500);
  }
}

export const config = { path: ['/api/public/:partner', '/api/public/:partner/branding', '/api/public/:partner/records/:record'] };
