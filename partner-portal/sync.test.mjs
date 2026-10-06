import assert from 'node:assert/strict';
import test from 'node:test';
import { signSync, verifySync, validatePublish, validateOffer } from './sync.mjs';

test('signed local handoff rejects changed body, expired time, or wrong path', () => {
  const secret = 'correct horse battery staple plus another 32 chars';
  const now = 1_780_000_000_000;
  const ts = String(now / 1000);
  const signature = signSync(secret, ts, 'POST', '/api/ops/publish', '{"id":"gpm"}');
  const request = new Request('https://example.org/api/ops/publish', { method: 'POST',
    headers: { 'x-tpf-timestamp': ts, 'x-tpf-signature': signature } });
  assert(verifySync(request, '{"id":"gpm"}', secret, now));
  assert(!verifySync(request, '{"id":"omc"}', secret, now));
  assert(!verifySync(request, '{"id":"gpm"}', secret, now + 301_000));
  assert(!verifySync(new Request('https://example.org/api/ops/events', { method: 'POST',
    headers: request.headers }), '{"id":"gpm"}', secret, now));
});

test('draft handoff does not require a planted pool', () => {
  const colors = { background: '#183030', panel: '#314949', accent: '#A8D8FF', text: '#F5FBF4', secondary: '#275941' };
  const payload = validatePublish({ revision: 'a'.repeat(64), profile: { schema: 'tpf_partner_v1',
    id: 'gpm', name: 'Global Pi Market', section_title: 'GPM', status: 'draft', colors } });
  assert.equal(payload.setup, null);
  assert.throws(() => validatePublish({ revision: 'a'.repeat(64), profile: { schema: 'tpf_partner_v1',
    id: 'gpm', name: 'Global Pi Market', section_title: 'GPM', status: 'draft', colors },
    connections: [{ requestId: '1'.repeat(36), poolId: 'pool-1' }] }), /connections/);
});

test('logo handoff validates content and rejects mismatched MIME', () => {
  const colors = { background: '#183030', panel: '#314949', accent: '#A8D8FF', text: '#F5FBF4', secondary: '#275941' };
  const payload = { revision: 'a'.repeat(64), profile: { schema: 'tpf_partner_v1', id: 'gpm',
    name: 'Global Pi Market', section_title: 'GPM', status: 'draft', colors },
    logo: { contentType: 'image/png', data: Buffer.from('89504e470d0a1a0a', 'hex').toString('base64') } };
  assert.equal(validatePublish(payload).logo.hash.length, 64);
  payload.logo.contentType = 'image/jpeg';
  assert.throws(() => validatePublish(payload), /Logo format/);
});

test('saved offer exposes final Pi price without internal cost', () => {
  const publicOffer = validateOffer({ partnerId: 'gpm', requestId: '11111111-1111-4111-8111-111111111111',
    revision: 'a'.repeat(64), offer: { schema: 'tpf_partner_offer_v1', id: 'b'.repeat(32),
      name: 'GPM offer', status: 'ready', search: { basis: 'co2' }, choices: [{
        key: '1:2', project: 'Forest', species: 'Tree', trees: 10, co2_kg: 1000,
        partner_price_pi: 100, planting_cost_eur: 7, pricing: { internal: 25 }
      }] } });
  assert.equal(publicOffer.choices[0].pricePi, 100);
  assert(!JSON.stringify(publicOffer).includes('planting_cost'));
  assert(!JSON.stringify(publicOffer).includes('internal'));
});
