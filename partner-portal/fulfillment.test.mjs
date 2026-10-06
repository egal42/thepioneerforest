import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { PGlite } from '@electric-sql/pglite';
import { connectSelectedPool } from './fulfillment.mjs';

test('a selected offer connects once to a verified pool with enough units', async () => {
  const db = new PGlite();
  try {
    for (const migration of [
      '202610060001_partner_portal_foundation', '202610060002_invitations',
      '202610060003_offers', '202610060004_request_connections'
    ]) {
      await db.exec(readFileSync(new URL(`../netlify/database/migrations/${migration}/migration.sql`,
        import.meta.url), 'utf8'));
    }
    const colors = JSON.stringify({ background: '#183030' });
    await db.query(`INSERT INTO partner_profiles (id,name,page_title,colors,local_revision)
      VALUES ('gpm','GPM','GPM',$1,'revision'), ('omc','OMC','OMC',$1,'revision')`, [colors]);
    const requestId = '11111111-1111-4111-8111-111111111111';
    const otherRequest = '22222222-2222-4222-8222-222222222222';
    const offerId = 'a'.repeat(32);
    const otherOffer = 'b'.repeat(32);
    await db.query(`INSERT INTO pool_requests (id,partner_id,requested_pi,basis,status)
      VALUES ($1,'gpm',100,'co2','selected'), ($2,'omc',100,'co2','selected')`,
    [requestId, otherRequest]);
    await db.query(`INSERT INTO pool_offers (id,request_id,partner_id,title,status,local_revision)
      VALUES ($1,$2,'gpm','GPM offer','offered','revision'),
      ($3,$4,'omc','OMC offer','offered','revision')`,
    [offerId, requestId, otherOffer, otherRequest]);
    await db.query(`INSERT INTO offer_choices
      (offer_id,choice_key,project,species,trees,co2_kg,price_pi)
      VALUES ($1,'choice-1','Forest','Tree',10,1000,100),
      ($2,'choice-1','Forest','Tree',10,1000,100)`, [offerId, otherOffer]);
    await db.query(`UPDATE pool_offers SET status='selected', selected_key='choice-1'
      WHERE id IN ($1,$2)`, [offerId, otherOffer]);
    await db.query(`INSERT INTO partner_pools
      (id,partner_id,name,basis,total_units,planted_trees,planted_co2_kg,proof_urls,local_revision)
      VALUES ('pool_low','gpm','Too small','co2',999,10,999,'[]','revision'),
      ('pool_full','gpm','Verified','co2',1000,10,1000,'[]','revision')`);
    const link = { requestId, offerId, choiceKey: 'choice-1', poolId: 'pool_full' };
    await assert.rejects(connectSelectedPool(db, 'gpm', { ...link, poolId: 'pool_low' }),
      /does not match/);
    await assert.rejects(connectSelectedPool(db, 'omc', link), /does not match/);
    await assert.rejects(connectSelectedPool(db, 'gpm', { ...link, choiceKey: 'wrong' }),
      /does not match/);
    await connectSelectedPool(db, 'gpm', link);
    await connectSelectedPool(db, 'gpm', link);
    const linked = await db.query('SELECT request_id, pool_id FROM pool_request_connections');
    assert.deepEqual(linked.rows, [{ request_id: requestId, pool_id: 'pool_full' }]);
    const status = await db.query('SELECT status FROM pool_requests WHERE id=$1', [requestId]);
    assert.equal(status.rows[0].status, 'connected');
    await assert.rejects(connectSelectedPool(db, 'omc', {
      requestId: otherRequest, offerId: otherOffer, choiceKey: 'choice-1', poolId: 'pool_full'
    }), /does not match/);
  } finally { await db.close(); }
});
