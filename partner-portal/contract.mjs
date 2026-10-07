// Validates the existing Operations Center public export before any import.
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const POOL_ID = /^[a-zA-Z0-9_-]+$/;
const HEX = /^#[0-9a-fA-F]{6}$/;
const COLOR_KEYS = ['background', 'panel', 'accent', 'text', 'secondary'];

export function validateSetup(data) {
  if (!data || data.schema !== 'tpf_partner_public_setup_v1' || !ID.test(data.partner_id || '')) {
    throw new Error('Invalid partner setup export');
  }
  if (data.live_records !== 'ONLINE_LEDGER_ONLY' || !Array.isArray(data.pools) || !data.pools.length) {
    throw new Error('A verified planted pool is required');
  }
  if (!COLOR_KEYS.every(key => HEX.test(data.colors?.[key] || ''))) {
    throw new Error('Invalid partner colours');
  }
  for (const pool of data.pools) {
    if (!POOL_ID.test(pool.id || '') || !['trees', 'co2'].includes(pool.basis)
      || !Number.isInteger(pool.planted_trees) || pool.planted_trees < 0
      || !Number.isFinite(pool.planted_co2_kg) || pool.planted_co2_kg < 0
      || !Array.isArray(pool.proof_urls) || !pool.proof_urls.length
      || !pool.proof_urls.every(url => typeof url === 'string' && /^https:\/\/(?:www\.)?tree-nation\.com\//.test(url))) {
      throw new Error('Invalid verified pool');
    }
  }
  return {
    partnerId: data.partner_id,
    name: String(data.name || ''),
    pageTitle: String(data.page_title || ''),
    tagline: String(data.tagline || ''),
    introduction: String(data.introduction || ''),
    colors: Object.fromEntries(COLOR_KEYS.map(key => [key, data.colors[key]])),
    pools: data.pools.map(pool => ({
      id: pool.id, name: String(pool.name || pool.id), basis: pool.basis,
      plantedTrees: pool.planted_trees, plantedCo2Kg: pool.planted_co2_kg,
      project: String(pool.project || ''), species: String(pool.species || ''),
      proofUrls: pool.proof_urls
    }))
  };
}

// Admin's pre-planting profile permits requests before a verified pool exists.
// Only the Admin's verified public export may add pools later.
export function validateDraftProfile(data) {
  if (!data || data.schema !== 'tpf_partner_v1' || !ID.test(data.id || '')
      || !['draft', 'active'].includes(data.status)
      || !COLOR_KEYS.every(key => HEX.test(data.colors?.[key] || ''))) {
    throw new Error('Invalid partner profile');
  }
  if (data.login_id != null && (!ID.test(data.login_id) || data.login_id.length > 80)) {
    throw new Error('Invalid login ID');
  }
  const name = String(data.name || '').trim();
  const pageTitle = String(data.section_title || '').trim();
  if (!name || name.length > 120 || !pageTitle || pageTitle.length > 120) {
    throw new Error('Invalid partner title');
  }
  return {
    partnerId: data.id, loginId: data.login_id || null, name, pageTitle,
    tagline: String(data.tagline || '').slice(0, 500),
    introduction: String(data.intro || '').slice(0, 5000),
    colors: Object.fromEntries(COLOR_KEYS.map(key => [key, data.colors[key]])),
    status: data.status
  };
}
