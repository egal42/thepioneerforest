const content = document.getElementById('content');
const status = document.getElementById('status');
const parts = location.pathname.split('/').filter(Boolean);
const partnerId = parts[1];
const recordId = parts[2] === 'records' ? parts[3] : null;
const text = (parent, tag, value, className) => {
  const node = document.createElement(tag); node.textContent = value;
  if (className) node.className = className;
  parent.append(node); return node;
};
const link = (parent, label, url) => {
  const node = document.createElement('a'); node.textContent = label; node.href = url;
  parent.append(node); return node;
};
const card = () => { const node = document.createElement('article'); node.className = 'panel'; content.append(node); return node; };
const units = (value, basis) => `${value} ${basis === 'trees' ? 'trees' : 'kg CO₂'}`;
async function shareCard(profile, record) {
  const { drawShareCard } = await import('/public-partner/card.js');
  const panel = card();
  text(panel, 'h2', 'Share this reward');
  text(panel, 'p', 'The Tree and Planet cards use the same saved record. Download matches this preview.');
  const tree = document.createElement('button'); tree.textContent = 'Tree';
  const planet = document.createElement('button'); planet.textContent = 'Planet';
  const download = document.createElement('button'); download.textContent = 'Download share card';
  const canvas = document.createElement('canvas'); canvas.style.cssText = 'display:block;width:min(100%,520px);margin:20px 0;border-radius:14px';
  panel.append(tree, planet, canvas, download);
  let template = record.basis === 'trees' ? 'tree' : 'planet';
  async function render() { await drawShareCard(canvas, profile, record, template); }
  tree.addEventListener('click', () => { template = 'tree'; render(); });
  planet.addEventListener('click', () => { template = 'planet'; render(); });
  download.addEventListener('click', () => {
    const a = document.createElement('a'); a.href = canvas.toDataURL('image/png');
    a.download = `${record.id}-${template}.png`; a.click();
  });
  await render();
}
function applyColors(colors) {
  for (const [key, value] of Object.entries(colors || {})) {
    const mapped = key === 'background' ? 'bg' : key;
    if (['bg', 'panel', 'accent', 'text', 'secondary'].includes(mapped) && /^#[a-fA-F0-9]{6}$/.test(value))
      document.documentElement.style.setProperty('--' + mapped, value);
  }
}
async function load() {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '')) throw new Error('Partner page not found');
  const path = `/api/public/${partnerId}` + (recordId ? `/records/${encodeURIComponent(recordId)}` : '');
  const response = await fetch(path);
  if (!response.ok) throw new Error('This partner page is not published yet.');
  const data = await response.json();
  applyColors(data.profile.colors);
  document.title = `${data.profile.page_title} · The Pioneer Forest`;
  status.remove();
  const hero = document.createElement('div'); hero.className = 'hero'; content.append(hero);
  if (data.profile.logo_url?.startsWith(`/api/public/${partnerId}/logo/`)) {
    const image = document.createElement('img'); image.src = data.profile.logo_url;
    image.alt = `${data.profile.name} logo`; image.style.cssText = 'max-width:160px;max-height:160px;object-fit:contain';
    hero.append(image);
  }
  text(hero, 'p', `${data.profile.name} × The Pioneer Forest`);
  text(hero, 'h1', data.profile.page_title);
  text(hero, 'p', data.profile.tagline);
  if (recordId) {
    link(content, '← Back to partner pools', `/p/${partnerId}/`);
    const record = data.record;
    const panel = card();
    text(panel, 'h2', `${units(record.units, record.basis)} shared with ${record.pioneer_name}`);
    text(panel, 'p', `Pool: ${record.pool_name}`);
    text(panel, 'p', `Date: ${new Date(record.created_at).toLocaleString()}`);
    if (record.reason) text(panel, 'p', `For: ${record.reason}`);
    text(panel, 'p', `Record ID: ${record.id}`);
    for (const url of record.proof_urls || []) {
      const p = text(panel, 'p', 'Planting proof: '); p.className = 'proof';
      link(p, url, url);
    }
    await shareCard(data.profile, record);
    return;
  }
  text(hero, 'p', data.profile.introduction);
  const totalTrees = data.pools.reduce((n, p) => n + Number(p.planted_trees), 0);
  const totalCo2 = data.pools.reduce((n, p) => n + Number(p.planted_co2_kg), 0);
  text(content, 'h2', 'Pools at a glance');
  text(content, 'p', `${totalTrees} trees planted · ${totalCo2} kg CO₂ backed · ${data.records.length} recent share records`);
  text(content, 'h2', 'Verified planting pools');
  const grid = document.createElement('div'); grid.className = 'grid'; content.append(grid);
  for (const pool of data.pools) {
    const panel = document.createElement('article'); panel.className = 'panel'; grid.append(panel);
    text(panel, 'h3', pool.name);
    text(panel, 'p', `${units(pool.total_units, pool.basis)} original · ${units(pool.shared_units, pool.basis)} shared · ${units(Number(pool.total_units) - Number(pool.shared_units), pool.basis)} remaining`);
    text(panel, 'p', `${pool.planted_trees} trees · ${pool.planted_co2_kg} kg CO₂ planted`);
    text(panel, 'p', `${pool.project} · ${pool.species}`);
    for (const url of pool.proof_urls || []) {
      const p = document.createElement('p'); panel.append(p); link(p, 'View planting proof', url);
    }
  }
  text(content, 'h2', 'Public share records');
  if (!data.records.length) text(content, 'p', 'No shares recorded yet.');
  for (const record of data.records) {
    const panel = card();
    text(panel, 'strong', `${units(record.units, record.basis)} shared with ${record.pioneer_name}`);
    text(panel, 'small', `${record.pool_name} · ${new Date(record.created_at).toLocaleString()}`, 'muted');
    link(panel, 'View record →', `/p/${partnerId}/records/${record.id}`);
  }
}
load().catch(error => { status.textContent = error.message; content.replaceChildren(); });
