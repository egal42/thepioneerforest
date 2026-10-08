import {renderOrders} from './orders.js';
const $ = id => document.getElementById(id);
const message = (text, bad = false) => { $('message').textContent = text; $('message').className = bad ? 'error' : 'success'; };
const adminSnapshot = JSON.parse(document.getElementById('admin-workspace-data').textContent);
async function api(action, body) {
  if (action !== 'me' || body) throw new Error('Read-only Admin view: actions are disabled.');
  return adminSnapshot;
}
function item(container, label) {
  const p = document.createElement('p'); p.textContent = label; container.append(p);
}
async function refresh() {
  if (new URL(location.href).searchParams.has('invite')) {
    $('claim').hidden = false; $('signin').hidden = true; $('workspace').hidden = true;
    return;
  }
  $('claim').hidden = true;
  try {
    const data = await api('me');
    $('signin').hidden = true; $('workspace').hidden = false; $('logout').hidden = true;
    $('workspace-nav').hidden = false;
    $('header-name').textContent = data.profile.name;
    $('footer').hidden = false;
    $('footer').textContent = `${data.profile.name} × The Pioneer Forest · Partner Pool`;
    $('public-link').hidden = data.profile.status !== 'active';
    $('public-link').href = `/p/${data.profile.id}/`;
    if (data.profile.logo_url?.startsWith(`/api/public/${data.profile.id}/logo/`)) {
      $('header-logo').src = adminSnapshot.portalOrigin + data.profile.logo_url;
      $('header-logo').alt = `${data.profile.name} logo`;
      $('header-logo').hidden = false;
    } else $('header-logo').hidden = true;
    applyPartnerTheme(data.profile.colors, data.profile.id);
    const number = value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
    const amountText = (value, basis) => `${number(value)} ${basis === 'trees' ? 'trees' : 'kg CO₂'}`;
    const poolName = pool => data.profile.id === 'omc' && pool.id === 'pool_006' ? 'OMC Welcome Pool' : pool.name;
    const publicPool = id => `/p/${data.profile.id}/pool/${encodeURIComponent(id)}`;
    const addLink = (parent, label, href) => { const a = document.createElement('a'); a.textContent = label; a.href = href; parent.append(a); return a; };
    const active = data.pools.filter(p => Number(p.total_units) > Number(p.shared_units));
    const completed = data.pools.filter(p => Number(p.total_units) <= Number(p.shared_units));
    const requestedPool = new URL(location.href).searchParams.get('pool');
    const selected = data.pools.find(p => p.id === requestedPool) || active[0] || completed[0];
    $('pools').replaceChildren(); $('completed-list').replaceChildren(); $('selected-workspace').replaceChildren();
    $('completed-pools').hidden = !completed.length;
    if (!active.length) item($('pools'), 'No active pools yet.');
    for (const pool of data.pools) {
      const a = addLink(active.includes(pool) ? $('pools') : $('completed-list'), '', `?pool=${encodeURIComponent(pool.id)}`);
      a.className = 'pool-tab' + (selected?.id === pool.id ? ' selected' : '');
      const small = document.createElement('small'); small.textContent = `${data.profile.name} · ${pool.basis === 'trees' ? 'Trees' : 'CO₂'}`;
      const title = document.createElement('strong'); title.textContent = poolName(pool);
      const remaining = document.createElement('small'); remaining.textContent = `${amountText(Number(pool.total_units) - Number(pool.shared_units), pool.basis)} available`;
      a.append(small, title, remaining);
    }
    if (selected) {
      const pool = selected;
      const available = Number(pool.total_units) - Number(pool.shared_units);
      const details = document.createElement('section'); details.className = 'panel';
      const eyebrow = document.createElement('div'); eyebrow.className = 'eyebrow'; eyebrow.textContent = 'Selected pool'; details.append(eyebrow);
      const title = document.createElement('h2'); title.textContent = poolName(pool); details.append(title);
      const metrics = document.createElement('div'); metrics.className = 'pool-numbers'; details.append(metrics);
      for (const [label, value] of [['Pool total',pool.total_units],['Shared',pool.shared_units],['Available',available]]) {
        const box = document.createElement('div'); box.textContent = label;
        const strong = document.createElement('strong'); strong.textContent = amountText(value,pool.basis); box.append(strong); metrics.append(box);
      }
      item(details, `Status: ${available > 0 ? 'Available' : 'Fully shared'}`);
      item(details, `Shared as: ${pool.basis === 'trees' ? 'Trees' : 'CO₂'}`);
      item(details, `${number(pool.planted_trees)} trees · ${amountText(pool.planted_co2_kg,'co2')} planted`);
      item(details, `${pool.project} · ${pool.species}`);
      const actions = document.createElement('div'); actions.className = 'action-row'; details.append(actions);
      for (const url of pool.proof_urls || []) addLink(actions, 'View planting proof', url).className = 'button-link';
      addLink(actions, 'Pool & records →', publicPool(pool.id)).className = 'button-link';
      const reward = document.createElement('section'); reward.className = 'panel';
      const heading = document.createElement('h2'); heading.textContent = 'Create a Pioneer reward'; reward.append(heading);
      if (available > 0 && data.profile.status === 'active') {
        const form = document.createElement('form'); form.className = 'share-form';
        const field = (label, element) => { const node = document.createElement('label'); node.textContent = label; node.append(element); form.append(node); return element; };
        const pioneer = field('Pioneer Pi username', document.createElement('input')); pioneer.required = true; pioneer.maxLength = 80; pioneer.placeholder = 'e.g. pioneer123';
        const amount = field(`Amount (${pool.basis === 'trees' ? 'whole trees' : 'kg CO₂'})`, document.createElement('input'));
        amount.type = 'number'; amount.min = pool.basis === 'trees' ? '1' : '0.001'; amount.step = pool.basis === 'trees' ? '1' : '0.001'; amount.max = String(available); amount.required = true;
        const reason = field('Reason (optional)', document.createElement('textarea')); reason.maxLength = 500; reason.rows = 2; reason.placeholder = 'e.g. Forest Journey reward';
        item(form, 'This records the reward, reduces the pool balance, and adds a public record.');
        const button = document.createElement('button'); button.textContent = 'Record reward for Pioneer →'; form.append(button);
        let pendingKey;
        form.addEventListener('submit', async event => {
          event.preventDefault(); button.disabled = true; pendingKey ||= crypto.randomUUID();
          try {
            const result = await api('share', {poolId:pool.id,pioneerName:pioneer.value.trim(),units:amount.value,reason:reason.value.trim(),idempotencyKey:pendingKey});
            pendingKey = null; location.href = `/p/${data.profile.id}/records/${encodeURIComponent(result.share.id)}`;
          } catch (error) { message(error.message,true); button.disabled = false; }
        }); reward.append(form);
      } else item(reward, available <= 0 ? 'This pool is fully shared. Choose another pool to continue.' : 'Sharing opens after TPF publishes the verified public page.');
      $('selected-workspace').append(details,reward);
    }
    $('requests').replaceChildren();
    if (!data.requests.some(r => r.status !== 'cancelled')) item($('requests'), 'No open pool requests.');
    for (const request of data.requests.filter(r => r.status !== 'cancelled'))
      item($('requests'), `${number(request.requested_pi)} Pi · ${request.basis === 'trees' ? 'Trees' : 'CO₂'} · ${{new:'Request sent',offered:'Offer ready',selected:'Offer selected',payment_pending:'Payment pending',planting_pending:'Planting pending',connected:'Pool connected',cancelled:'Cancelled'}[request.status] || request.status}`
        + (request.pool_id ? ` · verified pool ${request.pool_id}` : ''));
    renderOrders({data,readOnly:true});
    $('rewards').replaceChildren();
    $('rewards-section').hidden = false;
    if (!data.shares?.length) { item($('rewards'), 'No rewards shared yet. Your first share will appear here and on the public page.'); $('rewards').className = 'empty'; } else $('rewards').className = '';
    for (const share of data.shares || []) {
      const row = document.createElement('div'); row.className = 'pool';
      item(row, `${share.pioneer_name} · ${number(share.units)} ${share.basis === 'trees' ? 'trees' : 'kg CO₂'} · ${new Date(share.created_at).toLocaleString()}`);
      const a = document.createElement('a'); a.href = `/p/${data.profile.id}/records/${encodeURIComponent(share.id)}`;
      if (share.reason) item(row, `For: ${share.reason}`);
      addLink(row, 'View pool record', publicPool(share.pool_id)).className = 'button-link';
      a.textContent = 'View record & share'; a.className = 'button-link'; row.append(a); $('rewards').append(row);
    }
    document.querySelectorAll('form input,form select,form textarea,form button,#offers button').forEach(node => node.disabled = true);
    document.querySelector('#request-form').closest('details').hidden = true;
    document.querySelectorAll('a[href^="/p/"]').forEach(a => a.href = adminSnapshot.portalOrigin + a.getAttribute('href'));
    message('Read-only online workspace. Sharing, pool requests and offer selections are disabled.');
  } catch (error) {
    $('workspace').hidden = true; $('signin').hidden = true; $('workspace-nav').hidden = true; $('footer').hidden = true;
    if (error.message !== 'Sign in required') message(error.message, true);
  }
}
$('claim-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const token = new URL(location.href).searchParams.get('invite');
    const data = await api('claim', { token, password: $('new-password').value });
    history.replaceState(null, '', '/partner/');
    $('partner-id').value = data.partnerId;
    $('new-password').value = '';
    message('Access activated. Sign in with your new password.');
    await refresh();
  } catch (error) { message(error.message, true); }
});
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await api('login', { partnerId: $('partner-id').value.trim(), password: $('password').value });
    $('password').value = ''; message('Signed in.'); await refresh();
  } catch (error) { message(error.message, true); }
});
$('request-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await api('request', { pi: $('pi').value, basis: $('basis').value, message: $('note').value });
    $('request-form').reset(); message('Pool request sent to TPF.'); await refresh();
  } catch (error) { message(error.message, true); }
});
$('logout').addEventListener('click', async () => {
  try { await api('logout', {}); message('Signed out.'); await refresh(); }
  catch (error) { message(error.message, true); }
});
refresh();
