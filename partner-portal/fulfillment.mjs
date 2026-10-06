// Called inside the same transaction that publishes the verified pool.
export async function connectSelectedPool(client, partnerId, connection) {
  const selected = await client.query(`SELECT r.partner_id, r.basis, r.status, r.payment_reference,
    o.id AS offer_id, o.status AS offer_status, o.selected_key,
    c.trees, c.co2_kg, p.basis AS pool_basis, p.total_units
    FROM pool_requests r JOIN pool_offers o ON o.request_id=r.id
    JOIN offer_choices c ON c.offer_id=o.id AND c.choice_key=o.selected_key
    JOIN partner_pools p ON p.id=$2 AND p.partner_id=r.partner_id
    WHERE r.id=$1 FOR UPDATE OF r, o, p`, [connection.requestId, connection.poolId]);
  const row = selected.rows[0];
  const promised = row?.basis === 'trees' ? Number(row.trees) : Number(row?.co2_kg);
  if (!row || row.partner_id !== partnerId || row.basis !== row.pool_basis
      || row.offer_id !== connection.offerId || row.selected_key !== connection.choiceKey
      || row.offer_status !== 'selected' || !['planting_pending', 'connected'].includes(row.status) || (row.status === 'planting_pending' && !row.payment_reference)
      || Number(row.total_units) < promised) {
    throw new Error('Verified pool does not match the selected offer');
  }
  const existing = await client.query(`SELECT request_id, partner_id, pool_id, offer_id, choice_key
    FROM pool_request_connections WHERE request_id=$1 OR pool_id=$2 FOR UPDATE`,
  [connection.requestId, connection.poolId]);
  if (existing.rows.length) {
    if (existing.rows.length !== 1 || existing.rows[0].request_id !== connection.requestId
        || existing.rows[0].partner_id !== partnerId
        || existing.rows[0].pool_id !== connection.poolId
        || existing.rows[0].offer_id !== connection.offerId
        || existing.rows[0].choice_key !== connection.choiceKey) {
      throw new Error('Pool or request is already connected elsewhere');
    }
  } else {
    if (row.status === 'connected') throw new Error('Connected request is missing its saved connection');
    await client.query(`INSERT INTO pool_request_connections
      (request_id, partner_id, pool_id, offer_id, choice_key) VALUES ($1,$2,$3,$4,$5)`,
    [connection.requestId, partnerId, connection.poolId,
      connection.offerId, connection.choiceKey]);
  }
  await client.query(`UPDATE pool_requests SET status='connected', updated_at=now()
    WHERE id=$1 AND status <> 'connected'`, [connection.requestId]);
}
