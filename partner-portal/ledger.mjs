// Database operations shared by the future portal endpoints.
// The pool lock serializes shares so two simultaneous requests cannot overspend it.
import { randomUUID } from 'node:crypto';
export class LedgerError extends Error {
  constructor(message, status = 400) { super(message); this.status = status; }
}

export async function recordShare(pool, input, partnerId, client) {
  const amount = Number(input.units);
  const name = String(input.pioneerName || '').trim();
  const key = String(input.idempotencyKey || '');
  if (!Number.isSafeInteger(amount * 1000) || amount <= 0 || amount > 1e9
      || !name || name.length > 80 || !/^[a-f0-9-]{36}$/.test(key)) {
    throw new LedgerError('Invalid share');
  }
  const reason = String(input.reason || '').trim();
  if (reason.length > 500) throw new LedgerError('Reason is too long');

  await client.query('BEGIN');
  try {
    const { rows: pools } = await client.query(
      'SELECT id, partner_id, basis, total_units FROM partner_pools WHERE id = $1 AND partner_id = $2 FOR UPDATE',
      [pool, partnerId]
    );
    if (!pools.length) throw new LedgerError('Pool not found', 404);
    if (pools[0].basis === 'trees' && !Number.isInteger(amount)) {
      throw new LedgerError('Tree shares must use whole trees');
    }
    const { rows: duplicates } = await client.query(
      'SELECT * FROM partner_shares WHERE partner_id = $1 AND idempotency_key = $2',
      [partnerId, key]
    );
    if (duplicates.length) {
      if (duplicates[0].pool_id !== pool || Number(duplicates[0].units) !== amount
          || duplicates[0].pioneer_name !== name || duplicates[0].reason !== reason) {
        throw new LedgerError('Idempotency key was already used for another share', 409);
      }
      await client.query('COMMIT');
      return { share: duplicates[0], repeated: true };
    }
    const { rows: totals } = await client.query(
      'SELECT COALESCE(SUM(units), 0)::text AS shared FROM partner_shares WHERE pool_id = $1', [pool]
    );
    // PostgreSQL NUMERIC values arrive as strings. Convert to thousandths to avoid
    // a floating-point comparison around the last available unit.
    const milli = value => Math.round(Number(value) * 1000);
    if (milli(totals[0].shared) + milli(amount) > milli(pools[0].total_units)) {
      throw new LedgerError('This share exceeds the available balance', 409);
    }
    const id = randomUUID();
    const { rows: shares } = await client.query(
      `INSERT INTO partner_shares (id, pool_id, partner_id, pioneer_name, units, reason, idempotency_key)
       VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *`,
      [id, pool, partnerId, name, amount, reason, key]
    );
    await client.query(
      `INSERT INTO portal_events (partner_id, event_type, entity_id)
       VALUES ($1, 'share.created', $2)`, [partnerId, id]
    );
    await client.query('COMMIT');
    return { share: shares[0], repeated: false };
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  }
}
