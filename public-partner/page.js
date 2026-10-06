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
const number = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
const poolId = parts[2] === 'pool' ? parts[3] : null;
const recordsOnly = parts[2] === 'records' && !recordId;
const poolName = pool => partnerId === 'omc' && (pool.pool_id || pool.id) === 'pool_006' ? 'OMC Welcome Pool' : (pool.name || pool.pool_name);
const units = (value, basis) => `${number(value)} ${basis === 'trees' ? 'trees' : 'kg CO₂'}`;
async function shareCard(profile, record) {
  const { drawShareCard } = await import('/public-partner/card.js');
  const panel = card(); panel.classList.add('share-panel');
  text(panel, 'h2', 'Share this reward');
  text(panel, 'p', 'Choose a card, download it, or copy the reward text and public link.');
  const tree = document.createElement('button'); tree.textContent = 'Tree'; tree.className = 'template-btn';
  const planet = document.createElement('button'); planet.textContent = 'Planet'; planet.className = 'template-btn';
  const download = document.createElement('button'); download.textContent = 'Download share card';
  const canvas = document.createElement('canvas'); canvas.style.cssText = 'display:block;width:min(100%,520px);margin:20px 0;border-radius:14px';
  const copy = document.createElement('button'); copy.textContent = 'Copy post text';
  const copyLink = document.createElement('button'); copyLink.textContent = 'Copy public record link';
  const templates = document.createElement('div'); templates.className = 'action-row'; templates.append(tree,planet);
  const actions = document.createElement('div'); actions.className = 'action-row'; actions.append(download,copy,copyLink);
  panel.append(templates,canvas,actions);
  let template = record.basis === 'trees' ? 'tree' : 'planet';
  async function render() { tree.classList.toggle('on',template === 'tree'); planet.classList.toggle('on',template === 'planet'); await drawShareCard(canvas, profile, record, template); }
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
async function load() {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '')) throw new Error('Partner page not found');
  const path = `/api/public/${partnerId}` + (recordId ? `/records/${encodeURIComponent(recordId)}` : '');
  const response = await fetch(path);
  if (!response.ok) throw new Error('This partner page is not published yet.');
  const data = await response.json();
  applyPartnerTheme(data.profile.colors, partnerId);
  document.body.className = recordId ? 'public-record' : poolId ? 'pool-overview' : recordsOnly ? 'public-records' : 'public-overview';
  document.getElementById(recordsOnly || recordId ? 'records-nav' : 'pool-nav').classList.add('active');
  document.title = `${data.profile.page_title} · The Pioneer Forest`;
  document.getElementById('header-name').textContent = data.profile.name;
  document.getElementById('footer').textContent = `${data.profile.name} × The Pioneer Forest · Partner Pool`;
  const nav = document.getElementById('public-nav'); nav.hidden = false;
  const header = document.querySelector('body > header'); header.classList.add('public-header');
  header.insertBefore(nav, header.querySelector('.tpf-brand'));
  document.getElementById('pool-nav').href = `/p/${partnerId}/`;
  document.getElementById('records-nav').href = `/p/${partnerId}/records/`;
  status.remove();
  const hero = document.createElement('div'); hero.className = 'hero'; hero.hidden = Boolean(recordId || poolId || recordsOnly); content.append(hero);
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
    link(content, '← Back to partner pools', `/p/${partnerId}/`).className = 'pool-back';
    const record = data.record;
    text(content,'span','Public reward record','eyebrow');
    text(content,'h2',`${units(record.units,record.basis)} shared with ${record.pioneer_name}`);
    const details = document.createElement('div'); details.className = 'record-detail public-record-grid'; content.append(details);
    const panel = document.createElement('article'); panel.className = 'panel'; details.append(panel);
    record.pool_name = poolName(record);
    text(panel,'h3','Record details'); panel.classList.add('record-card');
    detailList(panel,[['Partner',data.profile.name],['Pioneer',record.pioneer_name],['Shared',units(record.units,record.basis)],['Pool',record.pool_name],['Date',new Date(record.created_at).toLocaleString()],['Reason',record.reason || '—'],['Record ID',record.id]]);
    const recordActions = document.createElement('div'); recordActions.className='proof-actions'; panel.append(recordActions);
    link(recordActions,'View pool & records →',`/p/${partnerId}/pool/${encodeURIComponent(record.pool_id)}#${encodeURIComponent(record.id)}`).className='button-link';
    for (const url of record.proof_urls || []) link(recordActions,'View planting proof',url).className='button-link';
    await shareCard(data.profile, record);
    details.prepend(content.lastElementChild);
    return;
  }
  text(hero, 'p', partnerId === 'omc' && data.pools.some(p => p.id === 'pool_006') && String(data.profile.introduction || '').includes('when the first partner pool is ready') ? 'The OMC Forest Journey connects OMC with The Pioneer Forest. Explore verified planting, available CO₂ rewards and public sharing records below.' : data.profile.introduction, 'intro');
  for (const record of data.records) record.pool_name = poolName(record);
  if (poolId || recordsOnly) {
    link(content, '← Back to partner pools', `/p/${partnerId}/`).className = 'pool-back';
    if (poolId) {
      const pool = data.pools.find(p => p.id === poolId);
      if (!pool) throw new Error('Pool not found');
      renderPoolDetail(pool, data.profile);
      const history = document.createElement('section'); history.className = 'pool-history'; content.append(history);
      text(history, 'h2', 'Pool sharing history');
      const records = data.records.filter(r => r.pool_id === poolId);
      text(history,'p',`${units(pool.shared_units,pool.basis)} shared across ${records.length} records.`);
      renderRecords(records,history);
    } else { text(content,'span','All rewards','eyebrow'); text(content, 'h2', `${data.profile.name} share records`); text(content,'p','Find a reward and see which pool it came from.'); renderRecordsTable(data.records); }
    if (location.hash) document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView({block:'center'});
    return;
  }
  const totalTrees = data.pools.reduce((n, p) => n + Number(p.planted_trees), 0);
  const totalCo2 = data.pools.reduce((n, p) => n + Number(p.planted_co2_kg), 0);
  text(content, 'h2', `${data.profile.name} pools at a glance`, 'impact-title');
  text(content, 'p', 'Totals across active and completed pools.', 'metrics-note');
  const metrics = document.createElement('div'); metrics.className = 'metrics'; content.append(metrics);
  for (const [value, label] of [[`🌳 ${number(totalTrees)}`,'Total trees'],[`🌐 ${number(totalCo2)} kg`,'Total CO₂'],[`🎁 ${data.pools.reduce((n,p) => n + Number(p.share_count || 0),0)}`,'Community shares'],[data.pools.length,'Pools']]) {
    const box = document.createElement('div'); box.className = 'panel metric'; metrics.append(box);
    text(box,'strong',value); text(box,'small',label);
  }
  text(content, 'p', 'Explore the pools', 'section-label');
  text(content, 'h2', `${data.profile.name}'s active pools`);
  text(content, 'p', 'Choose a pool to see its balance, rewards, and backing.');
  const grid = document.createElement('div'); grid.className = 'grid'; content.append(grid);
  for (const pool of data.pools.filter(p => Number(p.total_units) > Number(p.shared_units))) renderPool(pool, false, grid);
  if (!data.pools.some(p => Number(p.total_units) > Number(p.shared_units))) text(grid,'p','No active pools.');
  const completed = data.pools.filter(p => Number(p.total_units) <= Number(p.shared_units));
  if (completed.length) {
    text(content,'h2','Completed pools');
    const completedGrid = document.createElement('div'); completedGrid.className = 'grid'; content.append(completedGrid);
    for (const pool of completed) renderPool(pool,false,completedGrid);
  }
  text(content, 'p', 'Recent rewards', 'section-label');
  const recordsHeading = text(content, 'h2', `${data.profile.name} community rewards`); recordsHeading.id = 'records';
  text(content, 'p', 'Every reward has its own public record.');
  renderRecords(data.records.slice(0,6));
  link(content,'View all records →',`/p/${partnerId}/records/`).className = 'button-link';
  const explanation = document.createElement('section'); explanation.className = 'explain-grid'; content.append(explanation);
  const explainText = document.createElement('article'); explainText.className = 'panel'; explanation.append(explainText);
  text(explainText,'h2','One pool. One record.');
  text(explainText,'p','Every share is recorded against one pool and reduces its available balance. The same units cannot be shared twice.');
  text(explainText,'p','When a pool reaches zero, it moves to completed pools. Its balance and history remain visible.');
  const steps = document.createElement('div'); explanation.append(steps);
  for (const [n,title,note] of [[1,'Verified planting','Every pool is backed by planting proof.'],[2,'Shared with Pioneers','Each reward belongs to one dedicated pool.'],[3,'Public records','Balances and sharing history stay visible.']]) {
    const step = document.createElement('div'); step.className = 'step'; steps.append(step); text(step,'b',n); const words = document.createElement('div'); step.append(words); text(words,'strong',title); text(words,'small',note);
  }
}
function detailList(parent, entries) {
  const dl = document.createElement('dl'); dl.className = 'detail-list'; parent.append(dl);
  for (const [label,value] of entries) { const row = document.createElement('div'); dl.append(row); text(row,'dt',label); text(row,'dd',value); }
  return dl;
}
function renderPoolDetail(pool, profile) {
  const available = Number(pool.total_units)-Number(pool.shared_units);
  const title = document.createElement('section'); title.className = 'pool-title'; content.append(title);
  text(title,'span',`${profile.name} · Public pool record`,'eyebrow');
  text(title,'h2',`${pool.basis === 'trees' ? '🌳' : '🌍'} ${poolName(pool)}`);
  text(title,'p','See the rewards, remaining balance, and public records for this pool.');
  text(title,'span',available > 0 ? '● Available' : '✓ Completed',available > 0 ? 'badge' : 'badge done');
  const stats = document.createElement('div'); stats.className = 'pool-stats'; content.append(stats);
  for (const [label,value] of [['Total pool',pool.total_units],['Shared',pool.shared_units],['Remaining in pool',available]]) {
    const box = document.createElement('div'); box.className = 'panel'; stats.append(box); text(box,'strong',units(value,pool.basis)); text(box,'span',label);
  }
  const progress = card(); progress.classList.add('progress-panel');
  const top = document.createElement('div'); top.className = 'progress-top'; progress.append(top);
  const percent = Number(pool.total_units) ? Math.min(100,100*Number(pool.shared_units)/Number(pool.total_units)) : 0;
  text(top,'b',`${pool.basis === 'trees' ? 'Trees' : 'CO₂'} shared so far`); text(top,'span',`${Math.round(percent)}% shared`);
  const bar = document.createElement('div'); bar.className='bar'; bar.setAttribute('role','img'); bar.setAttribute('aria-label',`${Math.round(percent)}% shared`); progress.append(bar);
  const used = document.createElement('span'); used.style.width=`${percent}%`; bar.append(used);
  const info = document.createElement('div'); info.className='pool-info'; content.append(info);
  const backing = document.createElement('section'); backing.className='panel'; info.append(backing); text(backing,'h2','Pool backing');
  detailList(backing,[['Trees planted',number(pool.planted_trees)],['CO₂ backing',units(pool.planted_co2_kg,'co2')],['Project',pool.project],['Species',pool.species]]);
  const proof = document.createElement('div'); proof.className='proof-actions'; backing.append(proof);
  for (const url of pool.proof_urls || []) link(proof,'View planting proof',url).className='button-link';
  const about = document.createElement('section'); about.className='panel'; info.append(about); text(about,'h2','About this pool');
  detailList(about,[['Partner',profile.name],['Pool',poolName(pool)],['Shared as',pool.basis === 'trees' ? 'Trees' : 'CO₂'],['Status',available > 0 ? 'Available' : 'Completed']]);
  text(about,'p',`Pool ID: ${pool.id}`,'muted'); text(about,'p','A share reduces the balance once. Completed pools and records remain visible.','notice');
}
function renderRecordsTable(records) {
  if (!records.length) { text(content,'p','No shares recorded yet.','empty'); return; }
  const wrap=document.createElement('div'); wrap.className='tablewrap'; content.append(wrap);
  const table=document.createElement('table'); wrap.append(table); const head=document.createElement('thead'); table.append(head); const headings=document.createElement('tr'); head.append(headings);
  for (const label of ['Date','Pioneer','Pool','Shared','Record']) { const th=text(headings,'th',label); th.scope='col'; }
  const body=document.createElement('tbody'); table.append(body);
  for (const record of records) {
    const row=document.createElement('tr'); row.id=record.id; body.append(row);
    for (const value of [new Date(record.created_at).toLocaleDateString(),record.pioneer_name,record.pool_name,units(record.units,record.basis)]) text(row,'td',value);
    const action=document.createElement('td'); row.append(action); link(action,'View record',`/p/${partnerId}/records/${encodeURIComponent(record.id)}`);
  }
}
function renderPool(pool, detailed = false, parent = content) {
  const panel = document.createElement('article'); panel.className = 'panel pool-card'; parent.append(panel);
  const available = Number(pool.total_units)-Number(pool.shared_units);
  const heading = document.createElement('div'); heading.className='card-heading'; panel.append(heading);
  const identity = document.createElement('div'); heading.append(identity); text(identity,'span',`${document.getElementById('header-name').textContent} · ${pool.basis === 'trees' ? '🌳 Tree pool' : '🌍 CO₂ pool'}`,'eyebrow');
  text(heading, 'span', available > 0 ? '● Available' : '✓ Completed', available > 0 ? 'badge' : 'badge done');
  text(identity, detailed ? 'h2' : 'h3', poolName(pool));
  const numbers = document.createElement('div'); numbers.className = 'pool-numbers'; panel.append(numbers);
  for (const [label,value] of [['Pool total',pool.total_units],['Shared',pool.shared_units],['Available',available]]) {
    const box = document.createElement('div'); numbers.append(box); text(box,'small',label); text(box,'strong',units(value,pool.basis));
  }
  const bar = document.createElement('div'); bar.className = 'bar'; panel.append(bar);
  bar.setAttribute('role','img'); bar.setAttribute('aria-label',`${Math.round(100*Number(pool.shared_units)/Number(pool.total_units))}% shared`);
  const used = document.createElement('span'); used.style.width = `${Math.min(100,100*Number(pool.shared_units)/Number(pool.total_units))}%`; bar.append(used);
  const backing = document.createElement('div'); backing.className = 'pool-details'; panel.append(backing);
  text(backing,'p',`Shared as: ${pool.basis === 'trees' ? 'Whole trees' : 'CO₂'}`);
  text(backing,'p',`${number(pool.planted_trees)} trees · ${units(pool.planted_co2_kg,'co2')} planted`);
  text(backing,'p',`${pool.project} · ${pool.species}`);
  if (detailed) text(panel,'p',`Pool ID: ${pool.id}`,'muted');
  const actions = document.createElement('div'); actions.className = 'proof-actions'; panel.append(actions);
  if (!detailed) link(actions,'Pool & records →',`/p/${partnerId}/pool/${encodeURIComponent(pool.id)}`).className = 'button-link primary';
  for (const url of pool.proof_urls || []) link(actions,'View planting proof',url).className = 'button-link';
}
function renderRecords(records,parent = content) {
  const list = document.createElement('div'); list.className='panel reward-list'; parent.append(list);
  if (!records.length) text(list,'p','No shares recorded yet.','empty');
  for (const record of records) {
    const panel = document.createElement('article'); panel.className='reward-row reward-record'; list.append(panel); panel.id = record.id;
    text(panel,'strong',`${units(record.units,record.basis)} shared with ${record.pioneer_name}`);
    text(panel,'p',record.reason ? `For: ${record.reason}` : 'Community reward');
    const details = document.createElement('details'); panel.append(details); text(details,'summary','Record details');
    text(details,'p',`Date: ${new Date(record.created_at).toLocaleString()}`);
    text(details,'p',`Record ID: ${record.id}`); text(details,'p',`From: ${record.pool_name}`);
    const actions = document.createElement('div'); actions.className = 'proof-actions'; details.append(actions);
    link(actions,'View pool record',`/p/${partnerId}/pool/${encodeURIComponent(record.pool_id)}`).className = 'button-link';
    link(panel,'View record & share card →',`/p/${partnerId}/records/${encodeURIComponent(record.id)}`).className = 'button-link';
  }

}
load().catch(error => { status.textContent = error.message; if (!status.isConnected) content.prepend(status); });
