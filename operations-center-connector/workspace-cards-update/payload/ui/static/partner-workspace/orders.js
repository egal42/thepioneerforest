// Shared by the authenticated workspace and read-only Admin projection.
const number = value => Number(value).toLocaleString(undefined, {maximumFractionDigits:7});
export const orderLabel = status => ({new:'Request sent',offered:'Offer ready',selected:'Payment pending',payment_pending:'Payment pending',planting_pending:'Payment confirmed · Pool being prepared',connected:'Pool connected',cancelled:'Order cancelled'}[status] || 'Status unavailable');
export const noticeKey = (partner, request) => `tpf:pool-ready:${partner}:${request.id}:${request.pool_id}`;
export function notices(data, dismissed = () => false) {
  return data.requests.flatMap(request => {
    const offer = data.offers.find(o => o.request_id === request.id && o.status !== 'withdrawn');
    const pool = data.pools.find(p => p.id === request.pool_id);
    if (request.status === 'connected') {
      if (!pool || Number(pool.share_count) > 0 || Number(pool.shared_units) > 0 || data.shares?.some(s=>s.pool_id===pool.id) || dismissed(noticeKey(data.profile.id,request))) return [];
      const remaining=Number(pool.total_units)-Number(pool.shared_units);
      if (remaining<=0) return [];
      return [{request, pool, text:`Your pool is ready — ${number(remaining)} ${pool.basis === 'trees' ? 'trees' : 'kg CO₂'} available to share.`,action:'Open your pool',ready:true}];
    }
    const text={new:'Your pool request is with TPF. We’ll prepare an offer for you.',offered:'You have a new offer from TPF. Review the options and choose one.',selected:'Your choice is saved. View the payment instructions for this order.',payment_pending:'Your choice is saved. View the payment instructions for this order.',planting_pending:'Payment confirmed. TPF is preparing and connecting your pool.'}[request.status];
    return text ? [{request,offer,text,action:request.status==='offered'?'Review offer':['selected','payment_pending'].includes(request.status)?'View payment instructions':'View order'}] : [];
  });
}
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const paragraph=(parent,text)=>parent.append(node('p',text));
const details=(parent,label)=>{const n=node('details',null,'order-details');n.append(node('summary',label));parent.append(n);return n;};
function link(parent,text,href){const a=node('a',text,'button-link');a.href=href;parent.append(a);return a;}
export function renderOrders({data, readOnly=false, onChoose, onError=()=>{}, onMessage=()=>{}}) {
  const get=id=>document.getElementById(id);
  const publicPool=id=>`/p/${encodeURIComponent(data.profile.id)}/pool/${encodeURIComponent(id)}`;
  let top=get('order-notices');
  if (!top){top=node('section',null,'order-notices');top.id='order-notices';top.setAttribute('aria-label','Updates and next steps');get('workspace').prepend(top);}
  top.replaceChildren();
  const dismissed=key=>{try{return !readOnly && localStorage.getItem(key)==='dismissed';}catch{return false;}};
  for(const notice of notices(data,dismissed)){
    const row=node('article',null,'order-notice');paragraph(row,notice.text);
    link(row,notice.action,notice.ready ? (readOnly?publicPool(notice.pool.id):`/partner/?pool=${encodeURIComponent(notice.pool.id)}`):(notice.offer ? `#order-${notice.request.id}` : '#requests'));
    if(notice.ready && !readOnly){const button=node('button','Dismiss','notice-dismiss');button.type='button';button.addEventListener('click',()=>{try{localStorage.setItem(noticeKey(data.profile.id,notice.request),'dismissed');}catch{onMessage('Notice hidden for this visit. Your browser could not save the dismissal.');}row.remove();top.hidden=!top.children.length;});row.append(button);}
    if(notice.ready && readOnly) paragraph(row,'Partner notice preview. Viewing this does not dismiss their notice.');
    top.append(row);
  }
  top.hidden=!top.children.length;
  const offers=get('offers');offers.replaceChildren();get('offers-section').hidden=!data.offers.some(o=>o.status!=='withdrawn');
  get('offers-section').querySelector('h2').textContent='Offers & orders';
  for(const offer of data.offers.filter(o=>o.status!=='withdrawn')){
    const request=data.requests.find(r=>r.id===offer.request_id);
    const selected=data.choices.find(c=>c.offer_id===offer.id && c.choice_key===offer.selected_key);
    const pool=request && data.pools.find(p=>p.id===request.pool_id);
    const cancelled=request?.status==='cancelled';
    const actionable=offer.status==='offered' && request?.status==='offered';
    const card=node('article',null,'order-card');card.id=`order-${offer.request_id}`;
    const head=node('div',null,'order-heading');head.append(node('h3',pool?.name || (selected ? `${selected.common_name || selected.species} ${request?.basis==='trees'?'Tree':'CO₂'} Pool`:'Pool offer')));head.append(node('span',orderLabel(request?.status),'order-status'));card.append(head);
    if(selected){paragraph(card,`${number(selected.trees)} ${selected.common_name || selected.species} trees · ${selected.project}`);paragraph(card,`${number(selected.price_pi)} Pi${request?.payment_reference ? ' · Payment confirmed':''}`);}
    if(pool) link(card,'View pool →',publicPool(pool.id));
    if(request?.status==='planting_pending') paragraph(card,'TPF will connect your pool after checking the planting proof.');
    const history=details(card, actionable?'Review offer options':'Show order details');history.open=actionable || ['selected','payment_pending'].includes(request?.status);
    if(request?.created_at) paragraph(history,'Requested: '+new Date(request.created_at).toLocaleString());
    if(request?.payment_reference) paragraph(history,'Verified payment transaction: '+request.payment_reference);
    if(selected) paragraph(history,`${number(selected.co2_kg)} kg estimated CO₂ capture over time`);
    if(['selected','payment_pending'].includes(request?.status) && selected){
      const payment=node('div',null,'payment-instructions');paragraph(payment,'Payment instructions');
      if(!readOnly && (location.hostname.startsWith('deploy-preview-') || ['localhost','127.0.0.1'].includes(location.hostname))) paragraph(payment,'Test only — please do not send Pi for this offer.');
      const memo=data.profile.id.replaceAll('-','').slice(0,6).toUpperCase()+'-'+request.id.slice(-12).toUpperCase();
      for(const [label,value] of [['Amount to send',String(selected.price_pi).replace(/(\.\d*?)0+$/,'$1').replace(/\.$/,'')],['TPF wallet','GDJQWS634MNY2XQ6FKOM6Z2PP5RQWEWLBNQICV43WI4IVWT3RC7VHD3M'],['Wallet note',memo]]){
        const row=node('p',`${label}: ${value}${label==='Amount to send'?' Pi':''}`);payment.append(row);
        if(!readOnly){const b=node('button','Copy');b.type='button';b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(value);onMessage(label+' copied.');}catch{onError('Copy unavailable. Select the displayed value.');}});row.append(b);}
      }
      paragraph(payment,'Include the wallet note if your wallet supports it. If it cannot, contact TPF with your transaction reference so the payment can be matched.');history.append(payment);
    }
    const options=actionable?history:details(history,'Original offer options');
    for(const choice of data.choices.filter(c=>c.offer_id===offer.id)){
      const option=node('div',null,'offer-option');option.append(node('strong',`${choice.common_name || choice.species} · ${choice.project}`));paragraph(option,`${number(choice.trees)} trees · ${number(choice.co2_kg)} kg estimated CO₂ capture · ${number(choice.price_pi)} Pi`);
      if(choice.choice_key===offer.selected_key) option.append(node('span','Selected option','order-status'));
      if(actionable && !cancelled){const button=node('button',readOnly?'Choose this offer (partner only)':`Choose this offer · ${number(choice.price_pi)} Pi`);button.type='button';button.disabled=readOnly;button.addEventListener('click',async()=>{button.disabled=true;try{await onChoose(offer.id,choice.choice_key);}catch(error){onError(error.message);button.disabled=false;}});option.append(button);}
      options.append(option);
    }
    offers.append(card);
  }
}
