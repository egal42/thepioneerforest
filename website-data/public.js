const cacheKey='tpf-public-summary-v1';
function amount(v,places,max){return typeof v==='string'&&new RegExp(places?`^\\d+(\\.\\d{1,${places}})?$`:'^\\d+$').test(v)&&Number.isFinite(Number(v))&&Number(v)<=max;}
function valid(d){
 if(d?.schema!=='tpf_website_summary_v1'||!amount(d.minimumCo2KgPerPi,3,1e6)||Number(d.minimumCo2KgPerPi)<=0)return false;
 if(d.revision===null&&d.publishedAt===null)return d.impact===null;
 if(!/^[a-f0-9]{64}$/.test(d.revision||'')||!Number.isFinite(Date.parse(d.publishedAt)))return false;
 if(d.impact===null)return true;
 const p=d.impact;
 return amount(p?.contributionsPi,7,1e12)&&amount(p?.estimatedCo2Kg,3,1e15)&&(p.trees===null||amount(p.trees,0,1e12))&&/^\d{4}-\d{2}-\d{2}$/.test(p.asOf||'')&&new Date(p.asOf+'T00:00:00Z').toISOString().slice(0,10)===p.asOf&&p.asOf<=new Date().toISOString().slice(0,10);
}
function number(v,maximumFractionDigits=3){return Number(v).toLocaleString(undefined,{maximumFractionDigits});}
export function renderSummary(d,stale=false){
 for(const el of document.querySelectorAll('[data-tpf-minimum]'))el.textContent=number(d.minimumCo2KgPerPi);
 const impact=d.impact;
 for(const [id,key,suffix,precision] of [['total-pi','contributionsPi',' Pi',7],['total-co2','estimatedCo2Kg',' kg',3],['total-trees','trees','',0]]){
  const el=document.getElementById(id);if(el)el.textContent=impact?.[key]!=null?number(impact[key],precision)+suffix:'Not published yet';
 }
 for(const el of document.querySelectorAll('[data-tpf-summary-status]')){
  if(impact)el.textContent=`Records checked through ${impact.asOf}. ${stale?'Showing the last saved summary; the latest update could not be loaded.':`Published ${new Date(d.publishedAt).toLocaleDateString()}.`}`;
  else el.textContent=stale?'The latest public summary could not be loaded.':'Reviewed totals have not been published yet.';
 }
 for(const el of document.querySelectorAll('[data-tpf-policy-status]'))el.textContent=stale?'The public rule could not be refreshed. Showing the last available minimum.':d.publishedAt?`Public settings updated ${new Date(d.publishedAt).toLocaleDateString()}.`:'Current announced minimum. Reviewed website data will appear here after publication.';
}
export async function loadSummary(){
 let cached=null;try{const d=JSON.parse(localStorage.getItem(cacheKey));if(valid(d)&&d.revision&&d.publishedAt)cached=d;}catch{}
 if(cached)renderSummary(cached,true);
 try{
  const response=await fetch('/api/website-data',{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw new Error('Summary unavailable');const d=await response.json();if(!valid(d))throw new Error('Invalid summary');
  renderSummary(d);if(d.revision&&d.publishedAt)try{localStorage.setItem(cacheKey,JSON.stringify(d));}catch{}
 }catch{
  renderSummary(cached||{schema:'tpf_website_summary_v1',minimumCo2KgPerPi:'20',impact:null},true);
 }
}
if(typeof document!=='undefined')loadSummary();
