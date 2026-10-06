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
  const panel = card(); panel.classList.add('share-panel');
  text(panel, 'h2', 'Share this reward');
  text(panel, 'p', 'The Tree and Planet cards use the same saved record. Download matches this preview.');
  const tree = document.createElement('button'); tree.textContent = 'Tree';
  const planet = document.createElement('button'); planet.textContent = 'Planet';
  const download = document.createElement('button'); download.textContent = 'Download share card';
  const canvas = document.createElement('canvas'); canvas.style.cssText = 'display:block;width:min(100%,520px);margin:20px 0;border-radius:14px';
  const copy = document.createElement('button'); copy.textContent = 'Copy post text';
  const copyLink = document.createElement('button'); copyLink.textContent = 'Copy public record link';
  panel.append(tree, planet, canvas, download, copy, copyLink);
  let template = record.basis === 'trees' ? 'tree' : 'planet';
  async function render() { await drawShareCard(canvas, profile, record, template); }
  tree.addEventListener('click', () => { template = 'tree'; render(); });
  planet.addEventListener('click', () => { template = 'planet'; render(); });
  download.addEventListener('click', () => {
    const a = document.createElement('a'); a.href = canvas.toDataURL('image/png');
    a.download = `${record.id}-${template}.png`; a.click();
  });
  copy.addEventListener('click', async () => {
    const proof = (record.proof_urls || []).map(url => `Planting proof: ${url}`).join('\n');
    await navigator.clipboard.writeText(`${profile.name} shared ${units(record.units, record.basis)} with ${record.pioneer_name} through The Pioneer Forest.\nPool: ${record.pool_name}${record.reason ? `\nFor: ${record.reason}` : ''}\nPublic record: ${location.href}${proof ? `\n${proof}` : ''}`);
    copy.textContent = 'Copied';
  });
  copyLink.addEventListener('click', async () => {
    await navigator.clipboard.writeText(location.href); copyLink.textContent = 'Copied';
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
  document.getElementById('header-name').textContent = data.profile.name;
  document.getElementById('footer').textContent = `${data.profile.name} × The Pioneer Forest · Partner Pool`;
  const nav = document.getElementById('public-nav'); nav.hidden = false;
  document.getElementById('pool-nav').href = `/p/${partnerId}/`;
  document.getElementById('records-nav').href = `/p/${partnerId}/#records`;
  status.remove();
  const hero = document.createElement('div'); hero.className = 'hero'; content.append(hero);
  if (data.profile.logo_url?.startsWith(`/api/public/${partnerId}/logo/`)) {
    const image = document.createElement('img'); image.src = data.profile.logo_url;
    image.alt = `${data.profile.name} logo`; image.style.cssText = 'max-width:160px;max-height:160px;object-fit:contain';
    hero.append(image);
    const headerLogo = document.getElementById('header-logo'); headerLogo.src = image.src;
    headerLogo.alt = image.alt; headerLogo.hidden = false;
  }
  text(hero, 'p', `${data.profile.name} × The Pioneer Forest`, 'section-label');
  text(hero, 'h1', data.profile.page_title);
  text(hero, 'p', data.profile.tagline);
  if (recordId) {
    link(content, '← Back to partner pools', `/p/${partnerId}/`);
    const record = data.record;
    const details = document.createElement('div'); details.className = 'record-detail'; content.append(details);
    const panel = document.createElement('article'); panel.className = 'panel'; details.append(panel);
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
    details.prepend(content.lastElementChild);
    return;
  }
  text(hero, 'p', data.profile.introduction);
  const totalTrees = data.pools.reduce((n, p) => n + Number(p.planted_trees), 0);
  const totalCo2 = data.pools.reduce((n, p) => n + Number(p.planted_co2_kg), 0);
  text(content, 'h2', `${data.profile.name} pools at a glance`);
  const metrics = document.createElement('div'); metrics.className = 'metrics'; content.append(metrics);
  for (const [number, label] of [[totalTrees,'Total trees'],[`${totalCo2} kg`,'Total CO₂'],[data.records.length,'Community shares'],[data.pools.length,'Pools']]) {
    const box = document.createElement('div'); box.className = 'panel'; metrics.append(box);
    text(box,'strong',number); text(box,'small',label);
  }
  text(content, 'p', 'Explore the pools', 'section-label');
  text(content, 'h2', `${data.profile.name}'s active pools`);
  text(content, 'p', 'Choose a pool to see its balance, rewards, and backing.');
  const grid = document.createElement('div'); grid.className = 'grid'; content.append(grid);
  for (const pool of data.pools) {
    const panel = document.createElement('article'); panel.className = 'panel pool-card'; grid.append(panel);
    text(panel, 'h3', pool.name);
    const numbers = document.createElement('div'); numbers.className = 'pool-numbers'; panel.append(numbers);
    for (const [label,value] of [['Pool total',units(pool.total_units,pool.basis)],['Shared',units(pool.shared_units,pool.basis)],['Available',units(Number(pool.total_units)-Number(pool.shared_units),pool.basis)]]) {
      const box = document.createElement('div'); numbers.append(box); text(box,'small',label); text(box,'strong',value);
    }
    const bar = document.createElement('div'); bar.className = 'bar'; panel.append(bar);
    const used = document.createElement('span'); used.style.width = `${Math.min(100,100*Number(pool.shared_units)/Number(pool.total_units))}%`; bar.append(used);
    text(panel, 'p', `${pool.planted_trees} trees · ${pool.planted_co2_kg} kg CO₂ planted`);
    text(panel, 'p', `${pool.project} · ${pool.species}`);
    for (const url of pool.proof_urls || []) {
      const p = document.createElement('p'); panel.append(p); link(p, 'View planting proof', url);
    }
  }
  text(content, 'p', 'Recent rewards', 'section-label');
  const recordsHeading = text(content, 'h2', `${data.profile.name} community rewards`); recordsHeading.id = 'records';
  text(content, 'p', 'Every reward has its own public record.');
  if (!data.records.length) text(content, 'p', 'No shares recorded yet.');
  for (const record of data.records) {
    const panel = card(); panel.classList.add('record-row');
    text(panel, 'strong', `${units(record.units, record.basis)} shared with ${record.pioneer_name}`);
    text(panel, 'small', `${record.pool_name} · ${new Date(record.created_at).toLocaleString()}`, 'muted');
    link(panel, 'View record →', `/p/${partnerId}/records/${encodeURIComponent(record.id)}`);
  }
}
load().catch(error => { status.textContent = error.message; content.replaceChildren(); });
