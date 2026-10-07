import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {PGlite} from '@electric-sql/pglite';
import {signSync} from './sync.mjs';
import {hashPassword} from './auth.mjs';

// Run the actual HTTP handlers with only Netlify's database/blob adapters substituted.
// This is an isolated local database test, never a deployed acceptance test.
test('HTTP workflow: publish, invitation, login, shares, public proof and durable Admin events',async()=>{
 const pg=new PGlite();
 const query=(sql,args)=>pg.query(sql,args);
 const db={sql:async(strings,...args)=>(await query(strings.reduce((s,x,i)=>s+x+(i<args.length?`$${i+1}`:''),''),args)).rows,pool:{connect:async()=>({query,release(){}})}};
 const key=Symbol.for('tpf.isolated.workflow.db');globalThis[key]=db;
 const savedSecret=process.env.TPF_OPS_SYNC_SECRET;process.env.TPF_OPS_SYNC_SECRET='isolated-local-test-secret-not-a-live-credential';
 try{
  const folder=new URL('../netlify/database/migrations/',import.meta.url);
  const existingPassword=await hashPassword('existing-account-test-password');
  for(const migration of readdirSync(folder).sort()) {
    if(migration==='202610070008_partner_login_ids') {
      await query(`INSERT INTO partner_profiles(id,name,page_title,colors,local_revision) VALUES ('global-pi-market','Global Pi Market','GPM Mission','{}','existing')`);
      await query(`INSERT INTO partner_accounts(partner_id,password_hash) VALUES ('global-pi-market',$1)`,[existingPassword]);
    }
    await pg.exec(readFileSync(new URL(`${migration}/migration.sql`,folder),'utf8'));
  }
  assert.equal((await query(`SELECT password_hash FROM partner_accounts WHERE partner_id='global-pi-market'`)).rows[0].password_hash,existingPassword);
  async function handler(file){
   const url=new URL(`../netlify/functions/${file}.mjs`,import.meta.url);
   let source=readFileSync(url,'utf8').replace("import { getDatabase } from '@netlify/database';","const getDatabase=()=>globalThis[Symbol.for('tpf.isolated.workflow.db')];").replace("import { getStore } from '@netlify/blobs';","const getStore=()=>({set:async()=>{},get:async()=>null});");
   source=source.replace(/from '(\.\.[^']+)'/g,(_,relative)=>`from '${new URL(relative,url).href}'`);
   return (await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'))).default;
  }
  const ops=await handler('ops-api'),partner=await handler('partner-api'),publicPage=await handler('public-partner');
  const origin='https://isolated-test.invalid';
  async function call(fn,path,body,cookie='',signed=false){
   const raw=body===undefined?'':JSON.stringify(body),method=body===undefined?'GET':'POST';
   const headers={'content-type':'application/json',origin,cookie};
   if(signed){const timestamp=String(Math.floor(Date.now()/1000));headers['x-tpf-timestamp']=timestamp;headers['x-tpf-signature']=signSync(process.env.TPF_OPS_SYNC_SECRET,timestamp,method,path,raw);}
   const response=await fn(new Request(origin+path,{method,headers,...(method==='POST'?{body:raw}:{})}));
   return{status:response.status,body:await response.json(),cookie:response.headers.get('set-cookie')?.split(';')[0]};
  }
  for(const partnerId of ['gpm','global-pi-market']) {
    const existing=await call(partner,'/api/partner/login',{partnerId,password:'existing-account-test-password'});
    assert.equal(existing.status,200);assert.equal(existing.body.partnerId,'global-pi-market');
    assert.equal((await call(partner,'/api/partner/me',undefined,existing.cookie)).body.profile.id,'global-pi-market');
  }
  const colors={background:'#041524',panel:'#17435F',accent:'#43DCFF',text:'#EEF9FF',secondary:'#28543D'};
  const payload=id=>({profile:{schema:'tpf_partner_v1',id,name:'Isolated test partner',section_title:'Test Journey',status:'active',colors},revision:'a'.repeat(64),setup:{schema:'tpf_partner_public_setup_v1',partner_id:id,name:'Isolated test partner',page_title:'Test Journey',live_records:'ONLINE_LEDGER_ONLY',colors,pools:[{id:`${id}-co2`,name:'Isolated CO₂ test pool',basis:'co2',planted_trees:2,planted_co2_kg:200,proof_urls:['https://tree-nation.com/trees/view/123']},{id:`${id}-trees`,name:'Isolated tree test pool',basis:'trees',planted_trees:2,planted_co2_kg:200,proof_urls:['https://tree-nation.com/trees/view/123']}]}});
  // A branded public page and private request flow work before any planting.
  const preplant=payload('preplant'); preplant.setup=null; preplant.profile.login_id='short';
  const prepublished=await call(ops,'/api/ops/publish',preplant,'',true);
  assert.equal(prepublished.status,200);assert.equal(prepublished.body.publishedPools,0);
  assert.equal(new URL(prepublished.body.invitationUrl).searchParams.get('partner'),'preplant');
  const branded=await call(publicPage,'/api/public/preplant/branding');
  assert.equal(branded.status,200);assert.deepEqual(Object.keys(branded.body),['profile']);assert.deepEqual(branded.body.profile.colors,colors);
  const emptyPublic=await call(publicPage,'/api/public/preplant');
  assert.equal(emptyPublic.status,200);assert.deepEqual(emptyPublic.body.pools,[]);assert.deepEqual(emptyPublic.body.records,[]);
  assert.equal((await call(publicPage,'/api/public/preplant/records/missing')).status,404);
  const pretoken=new URL(prepublished.body.invitationUrl).searchParams.get('invite');
  assert.equal((await call(partner,'/api/partner/claim',{token:pretoken,password:'only-for-isolated-tests-123'})).status,200);
  const prelogin=await call(partner,'/api/partner/login',{partnerId:'preplant',password:'only-for-isolated-tests-123'});
  assert.equal(prelogin.status,200);
  const aliasLogin=await call(partner,'/api/partner/login',{partnerId:'short',password:'only-for-isolated-tests-123'});
  assert.equal(aliasLogin.status,200);assert.equal(aliasLogin.body.partnerId,'preplant');
  assert.equal((await call(partner,'/api/partner/me',undefined,aliasLogin.cookie)).body.profile.id,'preplant');
  assert.equal((await call(partner,'/api/partner/login',{partnerId:'short',password:'wrong'})).status,401);
  const duplicateAlias=payload('different');duplicateAlias.profile.login_id='short';
  assert.equal((await call(ops,'/api/ops/publish',duplicateAlias,'',true)).status,409);
  assert.equal((await call(publicPage,'/api/public/different')).status,404);
  assert.equal((await call(ops,'/api/ops/publish',payload('short'),'',true)).status,409);
  assert.equal((await call(publicPage,'/api/public/short')).status,404);
  const legacyUpdate=payload('preplant');legacyUpdate.setup=null;
  assert.equal((await call(ops,'/api/ops/publish',legacyUpdate,'',true)).status,200);
  assert.equal((await call(publicPage,'/api/public/preplant/branding')).body.profile.login_id,'short');

  assert.deepEqual((await call(partner,'/api/partner/me',undefined,prelogin.cookie)).body.pools,[]);
  assert.equal((await call(partner,'/api/partner/me?partner=test-a',undefined,prelogin.cookie)).body.profile.id,'preplant');
  assert.equal((await call(partner,'/api/partner/request',{pi:20,basis:'co2',message:'First pool request before planting'},prelogin.cookie)).status,201);
  const unverified=payload('preplant'); unverified.setup.pools[0].proof_urls=[];
  assert.equal((await call(ops,'/api/ops/publish',unverified,'',true)).status,400);
  assert.deepEqual((await call(publicPage,'/api/public/preplant')).body.pools,[]);
  const published=await call(ops,'/api/ops/publish',payload('test-a'),'',true);assert.equal(published.status,200);assert.equal(published.body.publishedPools,2);
  const invite=new URL(published.body.invitationUrl).searchParams.get('invite');
  assert.equal((await call(partner,'/api/partner/claim',{token:invite,password:'only-for-isolated-tests-123'})).status,200);
  assert.equal((await call(partner,'/api/partner/claim',{token:invite,password:'only-for-isolated-tests-123'})).status,400);
  assert.equal((await call(partner,'/api/partner/login',{partnerId:'test-a',password:'wrong'})).status,401);
  const login=await call(partner,'/api/partner/login',{partnerId:'test-a',password:'only-for-isolated-tests-123'});assert.equal(login.status,200);const cookie=login.cookie;
  assert.equal((await call(partner,'/api/partner/recover',{identification:'test-a',contact:'test@example.invalid'})).status,410);
  assert.equal((await call(ops,'/api/ops/access-requests',undefined,'',true)).body.requests.length,0);
  assert.equal((await call(partner,'/api/partner/me',undefined,cookie)).status,200);
  assert.equal((await call(partner,'/api/partner/me')).status,401);
  const me=await call(partner,'/api/partner/me',undefined,cookie);assert.equal(me.body.pools.length,2);assert.equal(me.body.pools[0].planted_trees,2);
  const adminView=await call(ops,'/api/ops/workspace?partnerId=test-a',undefined,'',true);
  assert.equal(adminView.status,200);assert.equal(adminView.body.readOnly,true);
  const {readOnly,retrievedAt,...snapshot}=adminView.body;assert.deepEqual(snapshot,me.body);
  assert.equal((await call(ops,'/api/ops/workspace?partnerId=test-a')).status,401);
  assert.equal((await call(ops,'/api/ops/workspace?partnerId=bad_id',undefined,'',true)).status,400);
  assert.equal((await call(ops,'/api/ops/workspace?partnerId=missing',undefined,'',true)).status,404);
  assert.equal((await call(ops,'/api/ops/workspace',{partnerId:'test-a'},'',true)).status,404);
  assert(!JSON.stringify(adminView.body).includes('token_hash'));
  const share={poolId:'test-a-co2',pioneerName:'isolated-pioneer',units:'25',reason:'Local test only',idempotencyKey:'00000000-0000-4000-8000-000000000001'};
  const first=await call(partner,'/api/partner/share',share,cookie);assert.equal(first.status,201);
  const repeat=await call(partner,'/api/partner/share',share,cookie);assert.equal(repeat.status,200);assert.equal(repeat.body.share.id,first.body.share.id);
  assert.equal((await call(partner,'/api/partner/share',{...share,units:'201',idempotencyKey:'00000000-0000-4000-8000-000000000002'},cookie)).status,409);
  assert.equal((await call(partner,'/api/partner/share',{...share,poolId:'test-a-trees',units:'0.5',idempotencyKey:'00000000-0000-4000-8000-000000000003'},cookie)).status,400);
  await call(ops,'/api/ops/publish',payload('test-b'),'',true);
  assert.equal((await call(partner,'/api/partner/share',{...share,poolId:'test-b-co2',idempotencyKey:'00000000-0000-4000-8000-000000000004'},cookie)).status,404);
  let pub=await call(publicPage,'/api/public/test-a');assert.equal(pub.status,200);assert.equal(Number(pub.body.pools.find(p=>p.id==='test-a-co2').shared_units),25);assert.equal(pub.body.records.length,1);assert.equal(Number(pub.body.pools.find(p=>p.id==='test-a-co2').share_count),1);
  const sharedView=await call(ops,'/api/ops/workspace?partnerId=test-a',undefined,'',true);assert.equal(Number(sharedView.body.pools.find(p=>p.id==='test-a-co2').shared_units),25);assert.equal(sharedView.body.shares[0].id,first.body.share.id);
  const record=await call(publicPage,`/api/public/test-a/records/${first.body.share.id}`);assert.equal(record.status,200);assert.equal(record.body.record.proof_urls.length,1);
  assert.equal((await call(publicPage,`/api/public/test-b/records/${first.body.share.id}`)).status,404);
  const request=await call(partner,'/api/partner/request',{pi:20,basis:'co2',message:'Local test request'},cookie);assert.equal(request.status,201);
  const offerId='c'.repeat(32);
  const offerPayload={partnerId:'test-a',requestId:request.body.id,revision:'b'.repeat(64),offer:{schema:'tpf_partner_offer_v1',id:offerId,name:'Local offer',status:'ready',search:{basis:'co2'},choices:[{key:'choice-1',project:'Test forest',species:'Test tree',common_name:'Test common name',trees:2,co2_kg:200,partner_price_pi:20}]}};
  assert.equal((await call(ops,'/api/ops/offer',offerPayload,'',true)).status,200);
  assert.equal((await call(partner,'/api/partner/choose',{offerId,choiceKey:'choice-1'},cookie)).status,200);
  assert.equal((await call(partner,'/api/partner/choose',{offerId,choiceKey:'choice-1'},cookie)).body.repeated,true);
  const connectedPayload=payload('test-a');connectedPayload.setup.pools=[{...connectedPayload.setup.pools[0],id:'test-a-request-pool'}];
  connectedPayload.connections=[{requestId:request.body.id,offerId,choiceKey:'choice-1',poolId:'test-a-request-pool'}];
  assert.equal((await call(ops,'/api/ops/publish',connectedPayload,'',true)).status,409);
  const payment={partnerId:'test-a',requestId:request.body.id,action:'confirm-payment',paymentReference:'d'.repeat(64),amountPi:'20',confirmVerified:true};
  assert.equal((await call(ops,'/api/ops/order',payment)).status,401);
  assert.equal((await call(ops,'/api/ops/order',{...payment,partnerId:'test-b'},'',true)).status,409);
  assert.equal((await call(ops,'/api/ops/order',{...payment,amountPi:'19'},'',true)).status,409);
  assert.equal((await call(ops,'/api/ops/order',{...payment,confirmVerified:false},'',true)).status,409);
  assert.equal((await call(ops,'/api/ops/order',payment,'',true)).status,200);
  assert.equal((await call(ops,'/api/ops/order',payment,'',true)).body.repeated,true);
  assert.equal((await call(ops,'/api/ops/order',{partnerId:'test-a',requestId:request.body.id,action:'cancel'},'',true)).status,409);
  assert.equal((await call(ops,'/api/ops/publish',connectedPayload,'',true)).status,200);
  assert.equal((await call(ops,'/api/ops/publish',connectedPayload,'',true)).status,200);
  const connected=await call(partner,'/api/partner/me',undefined,cookie);assert.equal(connected.body.requests[0].status,'connected');assert.equal(connected.body.requests[0].pool_id,'test-a-request-pool');
  const stale=await call(partner,'/api/partner/request',{pi:20,basis:'co2',message:'Disposable request'},cookie);
  const cancel={partnerId:'test-a',requestId:stale.body.id,action:'cancel'};
  assert.equal((await call(ops,'/api/ops/order',cancel,'',true)).status,200);
  assert.equal((await call(ops,'/api/ops/order',cancel,'',true)).body.repeated,true);
  assert.equal((await call(ops,'/api/ops/offer',{...offerPayload,requestId:stale.body.id,offer:{...offerPayload.offer,id:'f'.repeat(32)}},'',true)).status,409);
  const chosenCancel=await call(partner,'/api/partner/request',{pi:20,basis:'co2'},cookie);
  const cancelOffer='e'.repeat(32);
  assert.equal((await call(ops,'/api/ops/offer',{...offerPayload,requestId:chosenCancel.body.id,offer:{...offerPayload.offer,id:cancelOffer}},'',true)).status,200);
  assert.equal((await call(partner,'/api/partner/choose',{offerId:cancelOffer,choiceKey:'choice-1'},cookie)).status,200);
  assert.equal((await call(ops,'/api/ops/order',{...payment,requestId:chosenCancel.body.id},'',true)).status,409); // same transaction cannot fund two orders
  assert.equal((await call(ops,'/api/ops/order',{...cancel,requestId:chosenCancel.body.id},'',true)).status,200);
  assert.equal((await call(partner,'/api/partner/choose',{offerId:cancelOffer,choiceKey:'choice-1'},cookie)).status,409);
  const afterCancel=await call(partner,'/api/partner/me',undefined,cookie);
  assert.equal(afterCancel.body.requests.find(r=>r.id===stale.body.id).status,'cancelled');
  assert.equal(afterCancel.body.shares.length,1);
  const events=await call(ops,'/api/ops/events?after=0',undefined,'',true);assert.equal(events.status,200);assert.deepEqual(events.body.events.map(x=>x.event_type),['request.created','share.created','request.created','offer.selected','request.created','request.created','offer.selected']);
  assert.equal((await call(ops,`/api/ops/events?after=${events.body.next}`,undefined,'',true)).body.events.length,0);
  assert.equal((await call(ops,'/api/ops/events?after=0')).status,401);
  await call(ops,'/api/ops/publish',payload('test-a'),'',true);pub=await call(publicPage,'/api/public/test-a');assert.equal(Number(pub.body.pools.find(p=>p.id==='test-a-co2').shared_units),25);
  assert.equal((await call(partner,'/api/partner/share',{...share,units:'175',idempotencyKey:'00000000-0000-4000-8000-000000000005'},cookie)).status,201);
  assert.equal((await call(partner,'/api/partner/share',{...share,units:'1',idempotencyKey:'00000000-0000-4000-8000-000000000006'},cookie)).status,409);
  await call(partner,'/api/partner/logout',{},cookie);assert.equal((await call(partner,'/api/partner/me',undefined,cookie)).status,401);
 }finally{if(savedSecret===undefined)delete process.env.TPF_OPS_SYNC_SECRET;else process.env.TPF_OPS_SYNC_SECRET=savedSecret;delete globalThis[key];await pg.close();}
});
