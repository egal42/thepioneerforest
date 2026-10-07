import { getDatabase } from '@netlify/database';
import { getStore } from '@netlify/blobs';

export default async function handler(request) {
  if (request.method !== 'GET') return new Response('Method not allowed', { status: 405 });
  const parts = new URL(request.url).pathname.split('/').filter(Boolean);
  const partnerId = parts[2], hash = parts[4];
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '') || !/^[a-f0-9]{64}$/.test(hash || ''))
    return new Response('Not found', { status: 404 });
  try {
    const db = getDatabase();
    const rows = await db.sql`SELECT logo_url FROM partner_profiles WHERE id = ${partnerId}
      AND status = 'active'`;
    if (rows[0]?.logo_url !== `/api/public/${partnerId}/logo/${hash}`)
      return new Response('Not found', { status: 404 });
    const blob = await getStore('partner-logos').get(`${partnerId}/${hash}`, { type: 'blob' });
    if (!blob) return new Response('Not found', { status: 404 });
    return new Response(blob, { headers: { 'content-type': blob.type,
      'cache-control': 'public, max-age=86400', 'x-content-type-options': 'nosniff' } });
  } catch (error) {
    console.error('partner logo error', error);
    return new Response('Server error', { status: 500 });
  }
}

export const config = { path: '/api/public/:partner/logo/:hash' };
