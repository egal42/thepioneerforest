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
    $('partner-name').textContent = data.profile.name;
    const oldLogo = document.getElementById('partner-logo'); oldLogo?.remove();
    if (data.profile.status === 'active' && data.profile.logo_url?.startsWith(`/api/public/${data.profile.id}/logo/`)) {
      const logo = document.createElement('img'); logo.id = 'partner-logo'; logo.src = data.profile.logo_url;
      logo.alt = `${data.profile.name} logo`; logo.style.cssText = 'max-width:110px;max-height:110px;object-fit:contain';
      $('partner-name').before(logo);
    }
    for (const [key, value] of Object.entries(data.profile.colors || {})) {
      if (['background', 'panel', 'accent', 'text'].includes(key) && /^#[a-fA-F0-9]{6}$/.test(value))
        document.documentElement.style.setProperty('--' + (key === 'background' ? 'bg' : key), value);
    }
    $('pools').replaceChildren();
    if (!data.pools.length) item($('pools'), 'No verified pool is connected yet.');
    for (const pool of data.pools) {
      const card = document.createElement('div'); card.className = 'pool';
      const heading = document.createElement('h3'); heading.textContent = pool.name;
      card.append(heading);
      item(card, `${pool.basis === 'trees' ? 'Trees' : 'CO₂ kg'} · Total ${pool.total_units} · Shared ${pool.shared_units}`);
      if (data.profile.status === 'active') {
        const form = document.createElement('form');
        const pioneerLabel = document.createElement('label'); pioneerLabel.textContent = 'Pioneer username';
        const pioneer = document.createElement('input'); pioneer.required = true; pioneer.maxLength = 80;
        pioneerLabel.append(pioneer);
        const amountLabel = document.createElement('label'); amountLabel.textContent = `Amount (${pool.basis === 'trees' ? 'trees' : 'kg CO₂'})`;
        const amount = document.createElement('input'); amount.type = 'number'; amount.min = pool.basis === 'trees' ? '1' : '0.001';
        amount.step = pool.basis === 'trees' ? '1' : '0.001'; amount.required = true;
        amountLabel.append(amount);
        const reasonLabel = document.createElement('label'); reasonLabel.textContent = 'Reason (optional)';
        const reason = document.createElement('textarea'); reason.maxLength = 500; reasonLabel.append(reason);
        const button = document.createElement('button'); button.textContent = 'Record share';
        form.append(pioneerLabel, amountLabel, reasonLabel, button);
        let pendingKey;
        form.addEventListener('submit', async event => {
          event.preventDefault(); button.disabled = true;
          pendingKey ||= crypto.randomUUID();
          try {
            const result = await api('share', { poolId: pool.id, pioneerName: pioneer.value.trim(),
              units: amount.value, reason: reason.value.trim(), idempotencyKey: pendingKey });
            pendingKey = null;
            message(`Share recorded: ${result.share.id}. Public record: /p/${data.profile.id}/records/${result.share.id}`);
            await refresh();
          } catch (error) { message(error.message, true); button.disabled = false; }
        });
        card.append(form);
      } else item(card, 'Sharing opens after TPF publishes the verified public page.');
      $('pools').append(card);
    }
    $('requests').replaceChildren();
    if (!data.requests.length) item($('requests'), 'No requests yet.');
    for (const request of data.requests)
      item($('requests'), `${request.requested_pi} Pi · ${request.basis === 'trees' ? 'Trees' : 'CO₂'} · ${request.status}`
        + (request.pool_id ? ` · verified pool ${request.pool_id}` : ''));
    $('offers').replaceChildren();
    if (!data.offers.length) item($('offers'), 'No offers yet.');
    for (const offer of data.offers) {
      const section = document.createElement('section'); section.className = 'pool';
      const heading = document.createElement('h3'); heading.textContent = offer.title;
      section.append(heading);
      item(section, offer.status === 'selected' ? 'You selected an option. TPF will handle the next step.' : 'Choose one option. No payment or planting happens now.');
      for (const choice of data.choices.filter(c => c.offer_id === offer.id)) {
        const card = document.createElement('div');
        item(card, `${choice.project} · ${choice.common_name || choice.species} · ${choice.trees} trees · ${choice.co2_kg} kg CO₂ · ${choice.price_pi} Pi final offer price`);
        if (offer.status === 'offered') {
          const button = document.createElement('button');
          button.textContent = `Choose this offer · ${choice.price_pi} Pi`;
          button.addEventListener('click', async () => {
            button.disabled = true;
            try { await api('choose', { offerId: offer.id, choiceKey: choice.choice_key });
              message('Your choice was saved. TPF will contact you about the next step.'); await refresh(); }
            catch (error) { message(error.message, true); button.disabled = false; }
          });
          card.append(button);
        } else if (choice.choice_key === offer.selected_key) item(card, 'Selected');
        section.append(card);
      }
      $('offers').append(section);
    }
  } catch (error) {
    $('workspace').hidden = true; $('signin').hidden = false; $('logout').hidden = true;
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
