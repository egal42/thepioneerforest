import { readPartnerWorkspace } from '../../partner-portal/workspace.mjs';
import { getDatabase } from '@netlify/database';
import { getStore } from '@netlify/blobs';
import { randomBytes } from 'node:crypto';
import { verifySync, validatePublish, validateOffer } from '../../partner-portal/sync.mjs';
import { connectSelectedPool } from '../../partner-portal/fulfillment.mjs';
import { tokenHash } from '../../partner-portal/auth.mjs';

const reply = (data, status = 200) => new Response(JSON.stringify(data), { status,
  headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });

export default async function handler(request) {
  const url = new URL(request.url);
  const action = url.pathname.split('/').at(-1);
  const body = request.method === 'POST' ? await request.text() : '';
  if (body.length > 3_000_000) return reply({ error: 'Payload too large' }, 413);
  if (!verifySync(request, body, process.env.TPF_OPS_SYNC_SECRET)) return reply({ error: 'Unauthorized' }, 401);

  try {
    const db = getDatabase();
    if (action === 'workspace' && request.method === 'GET') {
      const partnerId = url.searchParams.get('partnerId');
      if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '')) return reply({error:'Invalid partner'},400);
      const data = await readPartnerWorkspace(db, partnerId);
      if (!data.profile) return reply({error:'Partner not found'},404);
      return reply({...data, readOnly:true, retrievedAt:new Date().toISOString()});
    }
    if (action === 'invite' && request.method === 'POST') {
      let partnerId;
      try { partnerId = JSON.parse(body).partnerId; } catch { return reply({ error: 'Invalid request' }, 400); }
      if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '')) return reply({ error: 'Invalid partner' }, 400);
      const token = randomBytes(32).toString('hex');
      const client = await db.pool.connect();
      try {
        await client.query('BEGIN');
        const profile = await client.query('SELECT id FROM partner_profiles WHERE id=$1 FOR UPDATE', [partnerId]);
        if (!profile.rows.length) {
          await client.query('ROLLBACK');
          return reply({ error: 'Publish the partner first' }, 404);
        }
        await client.query('DELETE FROM partner_invitations WHERE partner_id=$1 AND used_at IS NULL', [partnerId]);
        await client.query(`INSERT INTO partner_invitations (token_hash, partner_id, expires_at)
          VALUES ($1,$2,now() + interval '7 days')`, [tokenHash(token), partnerId]);
        await client.query('COMMIT');
        return reply({ invitationUrl: `${url.origin}/partner/?invite=${token}` });
      } catch (error) { await client.query('ROLLBACK'); throw error; }
      finally { client.release(); }
    }
    if (action === 'events' && request.method === 'GET') {
      const after = url.searchParams.get('after') || '0';
      if (!/^\d{1,16}$/.test(after)) return reply({ error: 'Invalid cursor' }, 400);
      const rows = await db.sql`SELECT e.id, e.partner_id, e.event_type, e.entity_id, e.created_at,
        r.requested_pi, r.basis AS request_basis, r.message, r.status AS request_status,
        s.pool_id, s.pioneer_name, s.units, s.reason,
        o.request_id AS offer_request_id, o.selected_key, c.price_pi AS selected_price_pi,
        r2.basis AS selected_basis, c.trees AS selected_trees,
        c.co2_kg AS selected_co2_kg
        FROM portal_events e
        LEFT JOIN pool_requests r ON e.event_type = 'request.created' AND r.id = e.entity_id
        LEFT JOIN partner_shares s ON e.event_type = 'share.created' AND s.id = e.entity_id
        LEFT JOIN pool_offers o ON e.event_type = 'offer.selected' AND o.id = e.entity_id
        LEFT JOIN pool_requests r2 ON r2.id = o.request_id
        LEFT JOIN offer_choices c ON c.offer_id = o.id AND c.choice_key = o.selected_key
        WHERE e.id > ${after} ORDER BY e.id LIMIT 100`;
      return reply({ events: rows, next: rows.length ? rows.at(-1).id : after });
    }
    if (action === 'offer' && request.method === 'POST') {
      let offer;
      try { offer = validateOffer(JSON.parse(body)); }
      catch { return reply({ error: 'Invalid saved offer' }, 400); }
      const client = await db.pool.connect();
      try {
        await client.query('BEGIN');
        const existing = await client.query('SELECT id, local_revision FROM pool_offers WHERE request_id=$1 FOR UPDATE', [offer.requestId]);
        if (existing.rows.length) {
          if (existing.rows[0].id !== offer.id || existing.rows[0].local_revision !== offer.revision)
            throw new Error('An offer is already attached to this request');
          await client.query('COMMIT');
          return reply({ offerId: offer.id, repeated: true });
        }
        const requestRows = await client.query('SELECT partner_id, basis, status FROM pool_requests WHERE id=$1 FOR UPDATE', [offer.requestId]);
        const requested = requestRows.rows[0];
        if (!requested || requested.partner_id !== offer.partnerId || requested.basis !== offer.basis
            || requested.status !== 'new') throw new Error('Request cannot receive this offer');
        await client.query(`INSERT INTO pool_offers (id, request_id, partner_id, title, local_revision)
          VALUES ($1,$2,$3,$4,$5)`, [offer.id, offer.requestId, offer.partnerId, offer.title, offer.revision]);
        for (const choice of offer.choices) await client.query(`INSERT INTO offer_choices
          (offer_id, choice_key, project, species, common_name, project_note, trees, co2_kg, price_pi)
          VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`, [offer.id, choice.key, choice.project, choice.species,
            choice.commonName, choice.projectNote, choice.trees, choice.co2Kg, choice.pricePi]);
        await client.query(`UPDATE pool_requests SET status='offered', updated_at=now() WHERE id=$1`, [offer.requestId]);
        await client.query('COMMIT');
        return reply({ offerId: offer.id, repeated: false });
      } catch (error) {
        await client.query('ROLLBACK');
        console.error('Offer handoff rejected', error);
        return reply({ error: 'Offer could not be sent; online request was kept' }, 409);
      } finally { client.release(); }
    }
    if (action !== 'publish' || request.method !== 'POST') return reply({ error: 'Not found' }, 404);

    let payload;
    try { payload = validatePublish(JSON.parse(body)); }
    catch { return reply({ error: 'Invalid verified partner data' }, 400); }
    const { profile, setup, revision, logo, connections } = payload;
    if (connections.length && profile.status !== 'active') {
      return reply({ error: 'A connected request needs an active verified page' }, 409);
    }
    let logoUrl = null;
    if (logo) {
      try {
        await getStore('partner-logos').set(`${profile.partnerId}/${logo.hash}`,
          new Blob([logo.bytes], { type: logo.contentType }));
        logoUrl = `/api/public/${profile.partnerId}/logo/${logo.hash}`;
      } catch (error) {
        console.error('Logo storage failed', error);
        return reply({ error: 'Logo could not be stored; nothing was published' }, 503);
      }
    }
    const client = await db.pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(`INSERT INTO partner_profiles
        (id, name, page_title, tagline, introduction, colors, logo_url, status, local_revision)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)
        ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, page_title=EXCLUDED.page_title,
        tagline=EXCLUDED.tagline, introduction=EXCLUDED.introduction, colors=EXCLUDED.colors,
        logo_url=EXCLUDED.logo_url, status=EXCLUDED.status,
        local_revision=EXCLUDED.local_revision, updated_at=now()`,
      [profile.partnerId, profile.name, profile.pageTitle, profile.tagline,
        profile.introduction, JSON.stringify(profile.colors), logoUrl, profile.status, revision]);

      for (const pool of setup?.pools || []) {
        const total = pool.basis === 'trees' ? pool.plantedTrees : pool.plantedCo2Kg;
        if (!Number.isFinite(total) || total <= 0) throw new Error('Pool has no verified units');
        const old = await client.query('SELECT partner_id, basis FROM partner_pools WHERE id=$1 FOR UPDATE', [pool.id]);
        if (old.rows.length && (old.rows[0].partner_id !== profile.partnerId || old.rows[0].basis !== pool.basis)) {
          throw new Error('Pool ownership or sharing basis changed');
        }
        const shares = await client.query('SELECT COALESCE(SUM(units),0)::text AS used FROM partner_shares WHERE pool_id=$1', [pool.id]);
        if (Number(shares.rows[0].used) > total) throw new Error('Verified amount is below shared amount');
        await client.query(`INSERT INTO partner_pools
          (id, partner_id, name, basis, total_units, planted_trees, planted_co2_kg,
           project, species, proof_urls, local_revision)
          VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11)
          ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, total_units=EXCLUDED.total_units,
          planted_trees=EXCLUDED.planted_trees, planted_co2_kg=EXCLUDED.planted_co2_kg,
          project=EXCLUDED.project, species=EXCLUDED.species, proof_urls=EXCLUDED.proof_urls,
          local_revision=EXCLUDED.local_revision`,
        [pool.id, profile.partnerId, pool.name, pool.basis, total, pool.plantedTrees,
          pool.plantedCo2Kg, pool.project, pool.species, JSON.stringify(pool.proofUrls), revision]);
      }
      for (const connection of connections) {
        await connectSelectedPool(client, profile.partnerId, connection);
      }
      let invitation = null;
      const account = await client.query('SELECT partner_id FROM partner_accounts WHERE partner_id=$1', [profile.partnerId]);
      if (!account.rows.length) {
        invitation = randomBytes(32).toString('hex');
        await client.query(`DELETE FROM partner_invitations WHERE partner_id=$1 AND used_at IS NULL`, [profile.partnerId]);
        await client.query(`INSERT INTO partner_invitations (token_hash, partner_id, expires_at)
          VALUES ($1,$2,now() + interval '7 days')`, [tokenHash(invitation), profile.partnerId]);
      }
      await client.query('COMMIT');
      return reply({ partnerId: profile.partnerId, revision, publishedPools: setup?.pools.length || 0,
        invitationUrl: invitation ? `${new URL(request.url).origin}/partner/?invite=${invitation}` : null });
    } catch (error) {
      await client.query('ROLLBACK');
      console.error('Partner publish rejected', error);
      return reply({ error: 'Publish rejected; existing online data was kept' }, 409);
    } finally { client.release(); }
  } catch (error) {
    console.error('ops-api error', error);
    return reply({ error: 'Server error' }, 500);
  }
}

export const config = { path: '/api/ops/:action' };
