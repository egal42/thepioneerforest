import {getDatabase} from '@netlify/database';
import {verifySync} from '../../partner-portal/sync.mjs';
import {validateSummary,defaultSummary} from '../../website-data/contract.mjs';
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'}});
export default async function handler(request){
 const path=new URL(request.url).pathname;
 const admin=path==='/api/ops/website-data';
 if(!admin&&path!=='/api/website-data')return json({error:'Not found'},404);
 if(!['GET','POST'].includes(request.method)||(!admin&&request.method!=='GET'))return json({error:'Method not allowed'},405);
 const body=request.method==='POST'?await request.text():'';
 if(body.length>10000)return json({error:'Payload too large'},413);
 if(admin&&!verifySync(request,body,process.env.TPF_OPS_SYNC_SECRET))return json({error:'Unauthorized'},401);
 try{
  const db=getDatabase();
  if(request.method==='GET'){
   const rows=await db.sql`SELECT document FROM website_summary WHERE id='tpf'`;
   return json(rows[0]?.document||defaultSummary);
  }
  let input,summary;
  try{input=JSON.parse(body);summary=validateSummary(input);}catch(e){return json({error:e.message},400);}
  const client=await db.pool.connect();
  try{
   await client.query('BEGIN');
   // Claim initial row too, so concurrent first publications cannot silently overwrite.
   await client.query(`INSERT INTO website_summary(id,revision,document) VALUES ('tpf','', $1::jsonb) ON CONFLICT(id) DO NOTHING`,[JSON.stringify(defaultSummary)]);
   const current=(await client.query(`SELECT revision,document FROM website_summary WHERE id='tpf' FOR UPDATE`)).rows[0];
   if(current.revision===summary.revision){await client.query('COMMIT');return json(current.document);}
   if((current.revision||null)!==input.expectedRevision){await client.query('ROLLBACK');return json({error:'Published data changed. Refresh and review it before publishing again.'},409);}
   const document={...summary,publishedAt:new Date().toISOString()};
   await client.query(`INSERT INTO website_summary_history(revision,document) VALUES ($1,$2::jsonb) ON CONFLICT(revision) DO NOTHING`,[summary.revision,JSON.stringify(document)]);
   await client.query(`UPDATE website_summary SET revision=$1,document=$2::jsonb,published_at=now() WHERE id='tpf'`,[summary.revision,JSON.stringify(document)]);
   await client.query('COMMIT');return json(document);
  }catch(e){await client.query('ROLLBACK');throw e;}finally{client.release();}
 }catch(e){console.error('Website summary error:',e.message);return json({error:'Public summary temporarily unavailable'},503);}
}
export const config={path:['/api/website-data','/api/ops/website-data']};
