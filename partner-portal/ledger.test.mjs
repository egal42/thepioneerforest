import assert from 'node:assert/strict';
import test from 'node:test';
import { recordShare } from './ledger.mjs';

const input = () => ({ units: 42, pioneerName: 'pioneer', reason: 'Forest',
  idempotencyKey: '11111111-1111-4111-8111-111111111111' });

function fakeClient({ total = '100', shared = '0', duplicate = null, own = true, basis = 'co2' } = {}) {
  const calls = [];
  return { calls, async query(sql, args = []) {
    calls.push({ sql, args });
    if (sql.includes('FROM partner_pools')) return { rows: own ? [{ total_units: total, basis }] : [] };
    if (sql.includes('FROM partner_shares WHERE partner_id')) return { rows: duplicate ? [duplicate] : [] };
    if (sql.includes('SUM(units)')) return { rows: [{ shared }] };
    if (sql.includes('RETURNING *')) return { rows: [{ pool_id: args[1], units: args[4] }] };
    return { rows: [] };
  } };
}

test('locks the partner pool, writes a share and event, then commits', async () => {
  const db = fakeClient();
  const result = await recordShare('pool_002', input(), 'gpm', db);
  assert.equal(result.share.units, 42);
  assert.match(db.calls[1].sql, /partner_id = \$2 FOR UPDATE/);
  assert(db.calls.some(call => call.sql.includes('share.created')));
  assert.equal(db.calls.at(-1).sql, 'COMMIT');
});

test('prevents overdraw and rolls back without creating a share', async () => {
  const db = fakeClient({ total: '100', shared: '60' });
  await assert.rejects(recordShare('pool_002', input(), 'gpm', db), { status: 409 });
  assert.equal(db.calls.at(-1).sql, 'ROLLBACK');
  assert(!db.calls.some(call => call.sql.includes('INSERT INTO partner_shares')));
});

test('keeps another partner out of a pool', async () => {
  const db = fakeClient({ own: false });
  await assert.rejects(recordShare('pool_002', input(), 'other', db), { status: 404 });
  assert.equal(db.calls.at(-1).sql, 'ROLLBACK');
});

test('rejects fractional tree shares', async () => {
  const db = fakeClient({ basis: 'trees' });
  const fractional = input(); fractional.units = 0.5;
  await assert.rejects(recordShare('pool_002', fractional, 'gpm', db), /whole trees/);
  assert.equal(db.calls.at(-1).sql, 'ROLLBACK');
});

test('retries return the original share and cannot change its details', async () => {
  const existing = { pool_id: 'pool_002', units: '42.000', pioneer_name: 'pioneer', reason: 'Forest' };
  const db = fakeClient({ duplicate: existing });
  assert.equal((await recordShare('pool_002', input(), 'gpm', db)).repeated, true);
  assert(!db.calls.some(call => call.sql.includes('INSERT INTO partner_shares')));
  const changed = input(); changed.units = 43;
  await assert.rejects(recordShare('pool_002', changed, 'gpm', fakeClient({ duplicate: existing })), { status: 409 });
});
