import { readPartnerWorkspace } from '../../partner-portal/workspace.mjs';
import { getDatabase } from '@netlify/database';
import { getStore } from '@netlify/blobs';
import { randomUUID } from 'node:crypto';
import { createSessionToken, hashPassword, sameOrigin, sessionCookie, tokenHash, verifyPassword } from '../../partner-portal/auth.mjs';
import { LedgerError, recordShare } from '../../partner-portal/ledger.mjs';

const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store', ...headers }
});
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MAX_BODY = 4096;

async function bodyOf(request) {
  if (Number(request.headers.get('content-length') || 0) > MAX_BODY) throw new LedgerError('Request too large', 413);
  const body = await request.text();
  if (body.length > MAX_BODY) throw new LedgerError('Request too large', 413);
  try { return JSON.parse(body); } catch { throw new LedgerError('Invalid JSON'); }
}

async function currentPartner(request, db) {
  const cookie = request.headers.get('cookie')?.match(/(?:^|;\s*)tpf_partner_session=([a-f0-9]{64})(?:;|$)/);
  if (!cookie) return null;
  const rows = await db.sql`
    SELECT s.partner_id FROM partner_sessions s JOIN partner_accounts a
    ON a.partner_id = s.partner_id WHERE s.token_hash = ${tokenHash(cookie[1])}
    AND s.expires_at > now() AND a.disabled_at IS NULL`;
  return rows[0]?.partner_id || null;
}

export default async function handler(request) {
  const url = new URL(request.url);
  const action = url.pathname.split('/').at(-1);
  if (request.method !== 'GET' && request.method !== 'POST') return json({ error: 'Method not allowed' }, 405);
  if (request.method === 'POST' && !sameOrigin(request)) return json({ error: 'Origin not allowed' }, 403);

  try {
    const db = getDatabase();
    if (action === 'recover') return json({ error: 'Contact The Pioneer Forest through your usual contact channel.' }, 410);
    if (action === 'claim'  && request.method === 'POST') {
      const body = await bodyOf(request);
      if (!/^[a-f0-9]{64}$/.test(body.token || '')) return json({ error: 'Invalid invitation' }, 400);
      let passwordHash;
      try { passwordHash = await hashPassword(body.password); }
      catch (error) { return json({ error: error.message }, 400); }
      const client = await db.pool.connect();
      try {
        await client.query('BEGIN');
        const invitation = await client.query(`SELECT partner_id FROM partner_invitations
          WHERE token_hash=$1 AND used_at IS NULL AND expires_at > now() FOR UPDATE`, [tokenHash(body.token)]);
        if (!invitation.rows.length) {
          await client.query('ROLLBACK');
          return json({ error: 'Invitation expired or already used' }, 400);
        }
        const partnerId = invitation.rows[0].partner_id;
        await client.query(`INSERT INTO partner_accounts (partner_id, password_hash)
          VALUES ($1,$2) ON CONFLICT (partner_id) DO UPDATE SET password_hash=EXCLUDED.password_hash,
          password_changed_at=now(), disabled_at=NULL`, [partnerId, passwordHash]);
        await client.query('DELETE FROM partner_sessions WHERE partner_id=$1', [partnerId]);
        await client.query('UPDATE partner_invitations SET used_at=now() WHERE partner_id=$1 AND used_at IS NULL', [partnerId]);
        await client.query('COMMIT');
        return json({ partnerId });
      } catch (error) { await client.query('ROLLBACK'); throw error; }
      finally { client.release(); }
    }
    if (action === 'login' && request.method === 'POST') {
      const body = await bodyOf(request);
      if (!ID.test(body.partnerId || '') || typeof body.password !== 'string') {
        return json({ error: 'Invalid sign in' }, 401);
      }
      const accounts = await db.sql`
        SELECT password_hash FROM partner_accounts WHERE partner_id = ${body.partnerId}
        AND disabled_at IS NULL`;
      if (!accounts.length || !await verifyPassword(body.password, accounts[0].password_hash)) {
        return json({ error: 'Invalid sign in' }, 401);
      }
      const token = createSessionToken();
      await db.sql`INSERT INTO partner_sessions (token_hash, partner_id, expires_at)
        VALUES (${tokenHash(token)}, ${body.partnerId}, now() + interval '7 days')`;
      return json({ partnerId: body.partnerId }, 200, { 'set-cookie': sessionCookie(token) });
    }

    const partnerId = await currentPartner(request, db);
    if (!partnerId) return json({ error: 'Sign in required' }, 401);

    if (action === 'logo' && request.method === 'GET') {
      const rows = await db.sql`SELECT logo_url FROM partner_profiles WHERE id = ${partnerId}`;
      const hash = rows[0]?.logo_url?.match(new RegExp(`^/api/public/${partnerId}/logo/([a-f0-9]{64})$`))?.[1];
      if (!hash) return json({ error: 'Logo not found' }, 404);
      const blob = await getStore('partner-logos').get(`${partnerId}/${hash}`, { type: 'blob' });
      if (!blob) return json({ error: 'Logo not found' }, 404);
      return new Response(blob, { headers: { 'content-type': blob.type,
        'cache-control': 'private, no-store', 'x-content-type-options': 'nosniff' } });
    }

    if (action === 'logout' && request.method === 'POST') {
      const cookie = request.headers.get('cookie')?.match(/(?:^|;\s*)tpf_partner_session=([a-f0-9]{64})(?:;|$)/);
      if (cookie) await db.sql`DELETE FROM partner_sessions WHERE token_hash = ${tokenHash(cookie[1])}`;
      return json({ ok: true }, 200, { 'set-cookie': sessionCookie('', 0) });
    }
    if (action === 'me' && request.method === 'GET') {
      return json(await readPartnerWorkspace(db, partnerId));
    }
    if (action === 'request' && request.method === 'POST') {
      const body = await bodyOf(request);
      const pi = Number(body.pi);
      const basis = body.basis;
      const message = String(body.message || '').trim();
      if (!Number.isFinite(pi) || pi <= 0 || pi > 1e6 || !['trees', 'co2'].includes(basis)
          || message.length > 1000) throw new LedgerError('Invalid pool request');
      const id = randomUUID();
      const client = await db.pool.connect();
      try {
        await client.query('BEGIN');
        await client.query(`INSERT INTO pool_requests (id, partner_id, requested_pi, basis, message)
          VALUES ($1,$2,$3,$4,$5)`, [id, partnerId, pi, basis, message]);
        await client.query(`INSERT INTO portal_events (partner_id, event_type, entity_id)
          VALUES ($1,'request.created',$2)`, [partnerId, id]);
        await client.query('COMMIT');
      } catch (error) { await client.query('ROLLBACK'); throw error; }
      finally { client.release(); }
      return json({ id, status: 'new' }, 201);
    }
    if (action === 'share' && request.method === 'POST') {
      const body = await bodyOf(request);
      const profiles = await db.sql`SELECT status FROM partner_profiles WHERE id = ${partnerId}`;
      if (profiles[0]?.status !== 'active') return json({ error: 'Public pool page is not active yet' }, 409);
      const client = await db.pool.connect();
      try {
        const result = await recordShare(body.poolId, body, partnerId, client);
        return json(result, result.repeated ? 200 : 201);
      } finally { client.release(); }
    }
    if (action === 'choose' && request.method === 'POST') {
      const body = await bodyOf(request);
      const client = await db.pool.connect();
      try {
        await client.query('BEGIN');
        const result = await client.query(`SELECT id, request_id, status, selected_key
          FROM pool_offers WHERE id=$1 AND partner_id=$2 FOR UPDATE`, [body.offerId, partnerId]);
        const offer = result.rows[0];
        if (!offer) throw new LedgerError('Offer not found', 404);
        if (offer.status === 'selected' && offer.selected_key === body.choiceKey) {
          await client.query('COMMIT');
          return json({ status: 'selected', repeated: true });
        }
        if (offer.status !== 'offered') throw new LedgerError('Offer is no longer available', 409);
        const choice = await client.query(`SELECT choice_key FROM offer_choices
          WHERE offer_id=$1 AND choice_key=$2`, [offer.id, body.choiceKey]);
        if (!choice.rows.length) throw new LedgerError('Choose an option from this offer');
        await client.query(`UPDATE pool_offers SET status='selected', selected_key=$2,
          selected_at=now() WHERE id=$1`, [offer.id, body.choiceKey]);
        await client.query(`UPDATE pool_requests SET status='payment_pending', updated_at=now()
          WHERE id=$1`, [offer.request_id]);
        await client.query(`INSERT INTO portal_events (partner_id,event_type,entity_id)
          VALUES ($1,'offer.selected',$2)`, [partnerId, offer.id]);
        await client.query('COMMIT');
        return json({ status: 'selected', repeated: false });
      } catch (error) {
        await client.query('ROLLBACK');
        if (error instanceof LedgerError) return json({ error: error.message }, error.status);
        throw error;
      } finally { client.release(); }
    }
    return json({ error: 'Not found' }, 404);
  } catch (error) {
    if (error instanceof LedgerError) return json({ error: error.message }, error.status);
    console.error('partner-api error', error);
    return json({ error: 'Server error' }, 500);
  }
}

export const config = { path: '/api/partner/:action', rateLimit: {
  windowLimit: 40, windowSize: 60, aggregateBy: ['ip', 'domain']
} };
