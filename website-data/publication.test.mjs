import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PGlite} from '@electric-sql/pglite';
import {signSync} from '../partner-portal/sync.mjs';
import {validateSummary,defaultSummary} from './contract.mjs';

const draft={schema:defaultSummary.schema,environment:'mainnet',minimumCo2KgPerPi:'20',expectedRevision:null,impact:{contributionsPi:'1870.1234567',estimatedCo2Kg:'82510.125',trees:'0',asOf:'2026-10-01'}};
test('public summary validates dates, precision and public fields',()=>{
 const result=validateSummary({...draft,secret:'private',additionPercent:25,reviewNote:'local only'});
 assert.equal(result.impact.trees,'0');assert.equal(result.impact.contributionsPi,'1870.1234567');
 assert.deepEqual(Object.keys(result),['schema','minimumCo2KgPerPi','impact','revision']);
 for(const patch of [{environment:'sandbox'},{minimumCo2KgPerPi:'0'},{minimumCo2KgPerPi:'NaN'},{expectedRevision:undefined},{impact:{...draft.impact,asOf:'2026-02-30'}},{impact:{...draft.impact,asOf:'2999-01-01'}},{impact:{...draft.impact,trees:'1.5'}},{impact:{...draft.impact,contributionsPi:'1.12345678'}},{impact:{...draft.impact,estimatedCo2Kg:'-1'}}])assert.throws(()=>validateSummary({...draft,...patch}));
});
test('HTTP publication is signed, idempotent and rejects stale overwrites',async()=>{
 const pg=new PGlite();const key=Symbol.for('tpf.website.test.db');const secret='isolated-summary-test-secret-not-a-real-credential';
 const old=process.env.TPF_OPS_SYNC_SECRET;process.env.TPF_OPS_SYNC_SECRET=secret;
 const query=(sql,args)=>pg.query(sql,args);
 globalThis[key]={sql:async(strings,...args)=>(await query(strings.reduce((s,x,i)=>s+x+(i<args.length?`$${i+1}`:''),''),args)).rows,pool:{connect:async()=>({query,release(){}})}};
 try{
  await pg.exec(readFileSync(new URL('../netlify/database/migrations/202610080009_website_summary/migration.sql',import.meta.url),'utf8'));
  const url=new URL('../netlify/functions/website-data.mjs',import.meta.url);
  let source=readFileSync(url,'utf8').replace("import {getDatabase} from '@netlify/database';","const getDatabase=()=>globalThis[Symbol.for('tpf.website.test.db')];");
  source=source.replace(/from '(\.\.[^']+)'/g,(_,relative)=>`from '${new URL(relative,url).href}'`);
  const handler=(await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))).default;
  async function call(path,body,signed=false){
   const method=body===undefined?'GET':'POST',raw=body===undefined?'':JSON.stringify(body),headers={};
   if(signed){const ts=String(Math.floor(Date.now()/1000));headers['x-tpf-timestamp']=ts;headers['x-tpf-signature']=signSync(secret,ts,method,path,raw);}
   const response=await handler(new Request('https://isolated.invalid'+path,{method,headers,...(body===undefined?{}:{body:raw})}));return{status:response.status,data:await response.json()};
  }
  assert.deepEqual((await call('/api/website-data')).data,defaultSummary);
  assert.equal((await call('/api/ops/website-data')).status,401);
  assert.equal((await call('/api/website-data',draft)).status,405);
  assert.equal((await call('/api/ops/website-data',draft)).status,401);
  assert.equal((await call('/api/ops/website-data',{...draft,environment:'sandbox'},true)).status,400);
  const first=await call('/api/ops/website-data',{...draft,additionPercent:25,reviewNote:'private'},true);assert.equal(first.status,200);
  const retry=await call('/api/ops/website-data',draft,true);assert.deepEqual(retry,first);
  assert.equal((await query('SELECT count(*) FROM website_summary_history')).rows[0].count,1);
  assert.equal((await call('/api/ops/website-data',{...draft,minimumCo2KgPerPi:'21'},true)).status,409);
  assert.deepEqual((await call('/api/website-data')).data,first.data);
  const second=await call('/api/ops/website-data',{...draft,minimumCo2KgPerPi:'21',expectedRevision:first.data.revision},true);assert.equal(second.status,200);
  assert.equal((await call('/api/ops/website-data',{...draft,impact:{...draft.impact,asOf:'2999-01-01'},expectedRevision:second.data.revision},true)).status,400);
  assert.deepEqual((await call('/api/website-data')).data,second.data);
  assert.equal((await query('SELECT count(*) FROM website_summary_history')).rows[0].count,2);
  assert(!JSON.stringify(second.data).includes('private'));assert(!JSON.stringify(second.data).includes('additionPercent'));
 }finally{if(old===undefined)delete process.env.TPF_OPS_SYNC_SECRET;else process.env.TPF_OPS_SYNC_SECRET=old;delete globalThis[key];await pg.close();}
});
test('browser retains dated saved figures on failures and never invents totals',async()=>{
 const source=readFileSync(new URL('./public.js',import.meta.url),'utf8').replace("if(typeof document!=='undefined')loadSummary();",'');
 const ui=(await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64')));
 const nodes=Object.fromEntries(['total-pi','total-co2','total-trees','minimum','summary','policy'].map(k=>[k,{textContent:''}]));
 const oldGlobals={document:globalThis.document,localStorage:globalThis.localStorage,fetch:globalThis.fetch};
 let cache=null;
 globalThis.document={getElementById:id=>nodes[id],querySelectorAll:selector=>[nodes[{'[data-tpf-minimum]':'minimum','[data-tpf-summary-status]':'summary','[data-tpf-policy-status]':'policy'}[selector]]]};
 globalThis.localStorage={getItem:()=>cache,setItem:(_,value)=>cache=value};
 try{
  globalThis.fetch=async()=>{throw new Error('offline');};await ui.loadSummary();assert.equal(nodes.minimum.textContent,'20');assert.equal(nodes['total-co2'].textContent,'Not published yet');
  const published={...validateSummary(draft),publishedAt:'2026-10-08T10:00:00Z'};
  globalThis.fetch=async()=>({ok:true,json:async()=>published});await ui.loadSummary();assert(nodes['total-pi'].textContent.includes('1234567'));assert(nodes.summary.textContent.includes('2026-10-01'));
  globalThis.fetch=async()=>({ok:false});await ui.loadSummary();assert(nodes.summary.textContent.includes('last saved'));assert(nodes['total-co2'].textContent.endsWith(' kg'));
  globalThis.fetch=async()=>({ok:true,json:async()=>({...published,impact:{...published.impact,estimatedCo2Kg:'NaN'}})});await ui.loadSummary();assert(nodes.summary.textContent.includes('last saved'));
 }finally{for(const [key,value] of Object.entries(oldGlobals)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}}
});
