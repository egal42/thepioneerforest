// Admin verification is explicit; receiving partner input never confirms payment.
export async function updateOrder(client, input) {
  const {partnerId, requestId, action} = input;
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '') || !/^[a-f0-9-]{36}$/.test(requestId || '')) throw new Error('Invalid request');
  const result = await client.query(`SELECT r.id,r.status,r.payment_reference,c.price_pi, c.price_pi = $3::numeric AS amount_matches
    FROM pool_requests r LEFT JOIN pool_offers o ON o.request_id=r.id
    LEFT JOIN offer_choices c ON c.offer_id=o.id AND c.choice_key=o.selected_key
    WHERE r.id=$1 AND r.partner_id=$2 FOR UPDATE OF r`,[requestId,partnerId,/^\d+(?:\.\d{1,7})?$/.test(String(input.amountPi)) ? input.amountPi : null]);
  const row=result.rows[0];
  if (!row) throw new Error('Request not found');
  if (action === 'cancel') {
    if (row.status==='cancelled') return {status:'cancelled',repeated:true};
    if (!['new','offered','selected','payment_pending'].includes(row.status) || row.payment_reference) throw new Error('Paid or connected requests cannot be cancelled here');
    await client.query(`UPDATE pool_requests SET status='cancelled',updated_at=now() WHERE id=$1`,[requestId]);
    await client.query(`UPDATE pool_offers SET status='withdrawn' WHERE request_id=$1`,[requestId]);
    return {status:'cancelled'};
  }
  if (action !== 'confirm-payment' || !/^[a-f0-9]{64}$/.test(input.paymentReference || '')
      || input.confirmVerified !== true || !/^\d+(?:\.\d{1,7})?$/.test(String(input.amountPi))
      || row.amount_matches !== true) throw new Error('Verify the transaction and exact selected Pi amount first');
  if (row.payment_reference === input.paymentReference && ['planting_pending','connected'].includes(row.status)) return {status:row.status,repeated:true};
  if (!['selected','payment_pending'].includes(row.status) || row.payment_reference) throw new Error('Payment cannot be recorded for this request');
  await client.query(`UPDATE pool_requests SET status='planting_pending',payment_reference=$2,payment_checked_at=now(),updated_at=now() WHERE id=$1`,[requestId,input.paymentReference]);
  return {status:'planting_pending'};
}
