import { drawShareCard } from '/public-partner/card.js';
const text=(parent,tag,value,className)=>{const n=document.createElement(tag);n.textContent=value;if(className)n.className=className;parent.append(n);return n;};
export async function renderRewardTools(parent,profile,record) {
  const amount=Number(record.units).toLocaleString(undefined,{maximumFractionDigits:3});
  const unit=record.basis === 'trees' ? 'trees' : 'kg CO₂';
  const publicUrl=new URL(`/p/${profile.id}/records/${encodeURIComponent(record.id)}`,location.origin).href;
  text(parent,'h2','Share this reward'); text(parent,'p','Card, details and message come from the saved reward. These tools do not create another share.');
  const grid=document.createElement('div');grid.className='reward-grid';parent.append(grid);
  const art=document.createElement('div');grid.append(art);text(art,'h3','Share card');
  const templates=document.createElement('div');templates.className='template-picker';art.append(templates);
  const tree=text(templates,'button','🌳 Tree','template-btn'),planet=text(templates,'button','🌍 Planet','template-btn');
  const canvas=document.createElement('canvas');canvas.style.cssText='display:block;width:100%;border-radius:20px';art.append(canvas);
  const download=text(art,'button','Download share card','card-download');
  const info=document.createElement('div');grid.append(info);text(info,'h3','Reward details');
  const details=document.createElement('div');details.className='reward-output';info.append(details);
  const lines=[`Pioneer: ${record.pioneer_name}`,`Shared: ${amount} ${unit}`,`Pool: ${record.pool_name}`,`For: ${record.reason || '—'}`,`Date: ${new Date(record.created_at).toLocaleString()}`,`Record ID: ${record.id}`];
  for(const line of lines)text(details,'p',line);
  const link=document.createElement('a');link.href=publicUrl;link.textContent='View public record →';link.className='button-link';details.append(link);
  for(const url of record.proof_urls || []){const proof=document.createElement('a');proof.href=url;proof.textContent='View planting proof';proof.className='button-link';details.append(proof);}
  const actions=document.createElement('div');actions.className='reward-actions';details.append(actions);
  const copyDetails=text(actions,'button','Copy reward details'),copyLink=text(actions,'button','Copy public record link');
  text(info,'h3','Share with your community');const post=document.createElement('div');post.className='reward-output';info.append(post);
  const proof=(record.proof_urls || []).map(url=>`Planting proof: ${url}`).join('\n');
  const message=`${profile.name} shared ${amount} ${unit} with ${record.pioneer_name} through The Pioneer Forest.\nPool: ${record.pool_name}${record.reason ? `\nFor: ${record.reason}` : ''}\nPublic record: ${publicUrl}${proof ? `\n${proof}` : ''}`;
  text(post,'pre',message);const copy=text(post,'button','Copy post text');
  let template=record.basis === 'trees' ? 'tree' : 'planet';
  let drawing=false;
  async function render(){drawing=true;download.disabled=true;tree.classList.toggle('on',template==='tree');planet.classList.toggle('on',template==='planet');try{await drawShareCard(canvas,profile,record,template);}finally{drawing=false;download.disabled=false;}}
  tree.addEventListener('click',async()=>{if(!drawing){template='tree';await render();}});planet.addEventListener('click',async()=>{if(!drawing){template='planet';await render();}});
  download.addEventListener('click',()=>{const a=document.createElement('a');a.href=canvas.toDataURL('image/png');a.download=`${record.id}-${template}.png`;a.click();});
  for(const [button,value] of [[copy,message],[copyLink,publicUrl],[copyDetails,lines.join('\n')]])button.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(value);button.textContent='Copied';}catch{button.textContent='Copy unavailable — select the text above';}});
  await render();
}
