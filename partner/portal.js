const $ = id => document.getElementById(id);
const message = (text, bad = false) => { $('message').textContent = text; $('message').className = bad ? 'error' : 'success'; };
async function api(action, body) {
  const response = await fetch('/api/partner/' + action, {
    method: body ? 'POST' : 'GET', credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
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
    $('signin').hidden = true; $('workspace').hidden = false; $('logout').hidden = false;
    $('workspace-nav').hidden = false;
    $('header-name').textContent = data.profile.name;
    $('footer').hidden = false;
    $('footer').textContent = `${data.profile.name} × The Pioneer Forest · Partner Pool`;
    $('public-link').hidden = data.profile.status !== 'active';
    $('public-link').href = `/p/${data.profile.id}/`;
    if (data.profile.logo_url?.startsWith(`/api/public/${data.profile.id}/logo/`)) {
      $('header-logo').src = '/api/partner/logo';
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
      const a = addLink(active.includes(pool) ? $('pools') : $('completed-list'), '', `/partner/?pool=${encodeURIComponent(pool.id)}`);
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
      item(details, `${pool.project} · ${displayPartnerSpecies(pool)}`);
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
            pendingKey = null; location.href = `/partner/?pool=${encodeURIComponent(pool.id)}&reward=${encodeURIComponent(result.share.id)}`;
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
    $('offers').replaceChildren();
    $('offers-section').hidden = !data.offers.some(o => o.status !== 'withdrawn');
    if (!data.offers.length) item($('offers'), 'No offers yet.');
    for (const offer of data.offers.filter(o => o.status !== 'withdrawn')) {
      const section = document.createElement('section'); section.className = 'pool';
      const heading = document.createElement('h3'); heading.textContent = offer.title;
      section.append(heading);
      item(section, offer.status === 'selected' ? 'Your offer choice is saved. Payment details and progress are below.' : 'Choose the option you like. The Pi amount shown is its full offer price. Choosing an offer saves your choice; payment and planting happen later.');
      if (offer.status === 'selected') {
        const request = data.requests.find(r => r.id === offer.request_id);
        const choice = data.choices.find(c => c.offer_id === offer.id && c.choice_key === offer.selected_key);
        if (request && choice) {
          const payment = document.createElement('section'); payment.className = 'panel';
          const title = document.createElement('h3'); title.textContent = 'Payment & pool progress'; payment.append(title);
          if (request.status === 'connected') item(payment, 'Your verified pool is connected.');
          else if (request.status === 'planting_pending') item(payment, 'Payment checked by TPF. Planting and verified pool connection are next.');
          else {
            if (location.hostname.startsWith('deploy-preview-') || ['localhost','127.0.0.1'].includes(location.hostname))
              item(payment, 'Test only — please do not send Pi for this offer.');
            const memo = data.profile.id.replaceAll('-', '').slice(0,6).toUpperCase() + '-' + request.id.slice(-12).toUpperCase();
            for (const [label,value] of [['Amount to send', `${String(choice.price_pi).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')} Pi`], ['TPF wallet', 'GDJQWS634MNY2XQ6FKOM6Z2PP5RQWEWLBNQICV43WI4IVWT3RC7VHD3M'], ['Put in the wallet note', memo]]) {
              const row=document.createElement('p'); row.style.overflowWrap='anywhere'; row.textContent=label+': '+value+' ';
              const copy=document.createElement('button'); copy.type='button'; copy.textContent='Copy';
              copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(label==='Amount to send'?String(choice.price_pi):value);message(label+' copied.');}catch{message('Copy unavailable. Select the displayed value.',true);}});
              row.append(copy); payment.append(row);
            }
            item(payment, 'Use the exact wallet note so TPF can match your payment. TPF checks the payment before planting begins.');
          }
          if (request.payment_reference) item(payment, 'Verified payment reference: '+request.payment_reference);
          section.append(payment);
        }
      }
      for (const choice of data.choices.filter(c => c.offer_id === offer.id)) {
        const card = document.createElement('div');
        item(card, `${choice.project} · ${choice.common_name || choice.species} · ${choice.trees} trees · ${choice.co2_kg} kg CO₂ · ${choice.price_pi} Pi final offer price`);
        if (offer.status === 'offered') {
          const button = document.createElement('button');
          button.textContent = `Choose this offer · ${choice.price_pi} Pi`;
          button.addEventListener('click', async () => {
            button.disabled = true;
            try { await api('choose', { offerId: offer.id, choiceKey: choice.choice_key });
              message('Your choice was saved. See the payment details below.'); await refresh(); }
            catch (error) { message(error.message, true); button.disabled = false; }
          });
          card.append(button);
        } else if (choice.choice_key === offer.selected_key) item(card, 'Selected');
        section.append(card);
      }
      $('offers').append(section);
    }
    $('rewards').replaceChildren();
    $('rewards-section').hidden = false;
    if (!data.shares?.length) { item($('rewards'), 'No rewards shared yet. Your first share will appear here and on the public page.'); $('rewards').className = 'empty'; } else $('rewards').className = '';
    for (const share of data.shares || []) {
      const row = document.createElement('div'); row.className = 'pool';
      item(row, `${share.pioneer_name} · ${number(share.units)} ${share.basis === 'trees' ? 'trees' : 'kg CO₂'} · ${new Date(share.created_at).toLocaleString()}`);
      const a = document.createElement('a'); a.href = `/partner/?pool=${encodeURIComponent(share.pool_id)}&reward=${encodeURIComponent(share.id)}`;
      if (share.reason) item(row, `For: ${share.reason}`);
      addLink(row, 'View pool record', publicPool(share.pool_id)).className = 'button-link';
      a.textContent = 'Card & sharing tools'; a.className = 'button-link'; row.append(a); $('rewards').append(row);
    }
    const rewardId = new URL(location.href).searchParams.get('reward');
    $('reward-tools').hidden = !rewardId; $('reward-tools').replaceChildren();
    if (rewardId) {
      const saved = data.shares.find(s => s.id === rewardId);
      const pool = saved && data.pools.find(p => p.id === saved.pool_id);
      if (!saved || !pool) { item($('reward-tools'),'This reward is not available in your workspace.'); }
      else {
        const { renderRewardTools } = await import('/partner/reward.js');
        await renderRewardTools($('reward-tools'),data.profile,{...saved,pool_name:poolName(pool),proof_urls:pool.proof_urls || []});
      }
      $('reward-tools').scrollIntoView({block:'start'});
    }
  } catch (error) {
    $('workspace').hidden = true; $('signin').hidden = false; $('workspace-nav').hidden = true; $('footer').hidden = true;
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
$('recovery-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button=event.currentTarget.querySelector('button'); button.disabled=true;
  try {
    const result=await api('recover',{identification:$('recovery-identification').value,contact:$('recovery-contact').value,note:$('recovery-note').value});
    $('recovery-form').reset(); $('recovery-status').textContent=result.message;
  } catch(error) { $('recovery-status').textContent=error.message; }
  finally { button.disabled=false; }
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
