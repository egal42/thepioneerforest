import assert from 'node:assert/strict';
import test from 'node:test';
import { validateSetup, validateDraftProfile } from './contract.mjs';

const valid = () => ({
  schema: 'tpf_partner_public_setup_v1', partner_id: 'gpm', name: 'Global Pi Market',
  page_title: 'GPM', live_records: 'ONLINE_LEDGER_ONLY',
  colors: { background: '#183030', panel: '#314949', accent: '#A8D8FF', text: '#F5FBF4', secondary: '#275941' },
  pools: [{ id: 'pool_002', basis: 'co2', planted_trees: 10, planted_co2_kg: 1000,
    proof_urls: ['https://tree-nation.com/trees/view/123'] }]
});

test('accepts the current Admin export format', () => {
  const setup = validateSetup(valid());
  assert.equal(setup.partnerId, 'gpm');
  assert.equal(setup.pools[0].id, 'pool_002');
  assert.equal(setup.pools[0].plantedCo2Kg, 1000);
});

test('rejects a preview without proof or with mismatched schema', () => {
  const noProof = valid(); noProof.pools[0].proof_urls = [];
  assert.throws(() => validateSetup(noProof));
  const wrong = valid(); wrong.schema = 'tpf_partner_v1';
  assert.throws(() => validateSetup(wrong));
});

test('accepts a draft partner before planting without publishing a pool', () => {
  const profile = validateDraftProfile({ schema: 'tpf_partner_v1', id: 'gpm', status: 'draft',
    name: 'Global Pi Market', section_title: 'GPM', colors: valid().colors });
  assert.equal(profile.partnerId, 'gpm');
  assert.equal(profile.status, 'draft');
  assert.equal(profile.pools, undefined);
});
