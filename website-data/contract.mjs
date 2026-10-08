import {createHash} from 'node:crypto';
export const defaultSummary=Object.freeze({schema:'tpf_website_summary_v1',minimumCo2KgPerPi:'20',impact:null,publishedAt:null,revision:null});
function decimal(value,places,max){
  const s=String(value ?? '');
  if(!new RegExp(places ? `^\\d+(?:\\.\\d{1,${places}})?$` : '^\\d+$').test(s)||!Number.isFinite(Number(s))||Number(s)>max) throw new Error('Invalid public amount');
  return s.replace(/^0+(?=\d)/,'').replace(/(\.\d*?)0+$/,'$1').replace(/\.$/,'');
}
export function validateSummary(input,now=new Date()){
  if(input?.schema!=='tpf_website_summary_v1'||input.environment!=='mainnet') throw new Error('Only reviewed mainnet summaries may be published');
  const minimumCo2KgPerPi=decimal(input.minimumCo2KgPerPi,3,1000000);
  if(Number(minimumCo2KgPerPi)<=0) throw new Error('Minimum must be positive');
  if(input.expectedRevision!==null&&!/^[a-f0-9]{64}$/.test(input.expectedRevision||'')) throw new Error('Refresh the published summary before publishing');
  let impact=null;
  if(input.impact!==null){
    const p=input.impact;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(p?.asOf||'')) throw new Error('Choose the date through which records have been checked');
    const date=new Date(p.asOf+'T00:00:00Z');
    if(!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==p.asOf||p.asOf>now.toISOString().slice(0,10)) throw new Error('Invalid review date');
    impact={estimatedCo2Kg:decimal(p.estimatedCo2Kg,3,1e15),trees:decimal(p.trees,0,1e12),asOf:p.asOf};
  }
  const summary={schema:defaultSummary.schema,minimumCo2KgPerPi,impact};
  return {...summary,revision:createHash('sha256').update(JSON.stringify(summary)).digest('hex')};
}
