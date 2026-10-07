/* Supporting decorative hue: same HLS rotation as the sandbox supporting_accent. */
function applyPartnerTheme(colors, partnerId) {
  for (const [key,value] of Object.entries(colors || {})) {
    const mapped = key === 'background' ? 'bg' : key;
    if (['bg','panel','accent','text','secondary'].includes(mapped) && /^#[a-fA-F0-9]{6}$/.test(value))
      document.documentElement.style.setProperty('--'+mapped,value);
  }
  if (/^#[a-fA-F0-9]{6}$/.test(colors?.secondary || '')) document.documentElement.style.setProperty('--line', colors.secondary);
  const accent = /^#[a-fA-F0-9]{6}$/.test(colors?.accent || '') ? colors.accent : '#a6e3b3';
  let spark = accent;
  if (colors?.colorful ?? partnerId === 'omc') {
    const [r,g,b]=[1,3,5].map(i=>parseInt(accent.slice(i,i+2),16)/255);
    const max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min;
    let hue=delta===0 ? 0 : max===r ? ((g-b)/delta)%6 : max===g ? (b-r)/delta+2 : (r-g)/delta+4;
    hue=((hue/6+0.54)%1+1)%1;
    const l=.68,s=.65,c=(1-Math.abs(2*l-1))*s,x=c*(1-Math.abs((hue*6)%2-1)),m=l-c/2;
    const sector=Math.floor(hue*6),channels=[[c,x,0],[x,c,0],[0,c,x],[0,x,c],[x,0,c],[c,0,x]][sector];
    spark='#'+channels.map(v=>Math.round((v+m)*255).toString(16).padStart(2,'0')).join('').toUpperCase();
  }
  document.documentElement.style.setProperty('--spark',spark);
  if (/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId || '') && validPartnerColors(colors)) {
    try { localStorage.setItem('tpf-partner-theme:' + partnerId, JSON.stringify(colors)); } catch {}
  }
}

// Confirmed common name from the OMC planting; other species keep their supplied name.
function displayPartnerSpecies(pool) {
  const latin = String(pool.species || '').trim();
  const common = pool.common_name || (latin.toLowerCase() === 'bruguiera gymnorhiza' ? 'Black mangrove' : '');
  return common && common.toLowerCase() !== latin.toLowerCase() ? `${common} (${latin})` : latin;
}

// Only presentation is cached. No sessions, balances, invitations or records.
function validPartnerColors(colors) {
  return ['background','panel','accent','text','secondary'].every(key => /^#[a-fA-F0-9]{6}$/.test(colors?.[key] || ''));
}
const tpfDefaultColors = window.tpfDefaultColors = Object.freeze({background:'#061a12',panel:'#102a1c',accent:'#a6e3b3',text:'#e6f5ec',secondary:'#275941'});
function partnerThemeReady() { document.documentElement.removeAttribute('data-theme-loading'); }
(function bootstrapPartnerTheme() {
  const root = document.documentElement;
  const path = location.pathname.split('/').filter(Boolean);
  const id = path[0] === 'p' ? path[1] : path[0] === 'partner' ? new URL(location.href).searchParams.get('partner') : null;
  const initial = window.__TPF_PARTNER_PREVIEW__?.profile || window.__TPF_BRAND_INITIAL__;
  applyPartnerTheme(tpfDefaultColors);
  if (initial && validPartnerColors(initial.colors)) applyPartnerTheme(initial.colors, initial.id);
  else if (/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id || '')) {
    try { const cached = JSON.parse(localStorage.getItem('tpf-partner-theme:' + id)); if (validPartnerColors(cached)) applyPartnerTheme(cached, id); } catch {}
  }
  // Parser-blocking script runs before body paint. Reveal only after fresh data or a clear error.
  if (path[0] === 'p' || path[0] === 'partner' || window.__TPF_PARTNER_PREVIEW__) {
    root.setAttribute('data-theme-loading','');
    const style = document.createElement('style');
    style.textContent = 'html[data-theme-loading]{background:var(--bg);color:var(--text)}html[data-theme-loading] body{visibility:hidden}html[data-theme-loading]::before{content:"Loading…";position:fixed;inset:0;display:grid;place-items:center;font:16px system-ui;color:var(--text);background:var(--bg)}';
    document.head.append(style);
    // Fallback if a module fails to load: restore navigation and show a useful message.
    setTimeout(() => {
      if (!root.hasAttribute('data-theme-loading')) return;
      partnerThemeReady();
      const target = document.getElementById('status') || document.getElementById('message');
      if (target) target.textContent = 'Loading could not finish. Please reload or use the back link.';
    }, 15000);
  }
})();
