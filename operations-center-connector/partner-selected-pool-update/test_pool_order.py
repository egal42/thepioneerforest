import ast, copy, json, os, re, subprocess, sys, tempfile, unittest
from decimal import Decimal, InvalidOperation
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).parent/'update/payload/ui'))
from partner_pool_order import resolve_choice, selected_catalog_option
from partner_payment import write_audit
import requests, portal_sync
from flask import Flask, request, redirect, url_for
ROOT=Path(__file__).parent
RID='11111111-1111-1111-1111-07dff44edb4a'; PARTNER='global-pi-market'; HASH='a'*64
CHOICE={'key':'716:3493','project_id':716,'species_id':3493,'project':'Preservation of Mt. Elgon Ecosystem','species':'Citrus limon','common_name':'Lemon','trees':48,'co2_kg':'960','partner_price_pi':'300.00','planting_cost_eur':'16.80'}
EVENT={'event_type':'offer.selected','partner_id':PARTNER,'offer_request_id':RID,'entity_id':'offer1','selected_key':'716:3493','selected_basis':'trees','selected_trees':48,'selected_co2_kg':'960','selected_price_pi':'300'}
OFFER={'schema':'tpf_partner_offer_v1','id':'offer1','search':{'basis':'trees'},'choices':[dict(CHOICE),dict(CHOICE,key='716:3494',species_id=3494)]}
AUDIT={'status':'complete','partner_id':PARTNER,'request_id':RID,'tx_hash':HASH,'amount_pi':'300'}
ORDER={'id':RID,'status':'planting_pending','payment_reference':HASH}
CAT={'projects':[{'project_id':716,'species':[{'id':3493,'stock':100,'price':.35,'life_time_CO2':20}]}]}
class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.offer=copy.deepcopy(OFFER);self.order=dict(ORDER);self.catalog=copy.deepcopy(CAT);self.purchases=[];self.fail=False;self.refresh_ok=True
        write_audit(self.root/'partner-pools/portal-inbox/event.json',EVENT)
        write_audit(self.root/f'partner-pools/payment-matches/{RID}.json',AUDIT)
        self.app=Flask(__name__)
        def load(path,default=None): return json.loads(Path(path).read_text()) if Path(path).exists() else default
        def purchase(*args):
            self.purchases.append(args)
            if self.fail: raise requests.RequestException('ambiguous response')
            pool={'pool_id':args[0],'owner_kind':args[8],'owner_partner_id':args[9]}
            file=self.root/'co2-pool/pools'/f'{args[0]}.json';write_audit(file,pool)
            return {'ok':True,'pool':pool,'pool_file':str(file)}
        self.context={}
        def render(template,**values): self.context=values;return template
        portal_sync.signed_request=lambda *args,**kwargs:{'requests':[self.order]}
        self.ns={'app':self.app,'request':request,'redirect':redirect,'url_for':url_for,'re':re,'os':os,'ACTIVE_ENV':'mainnet','DATA_ROOT':self.root,
                 'Decimal':Decimal,'InvalidOperation':InvalidOperation,'Path':Path,'requests':requests,'subprocess':subprocess,
                 '_read_partner':lambda pid:{'name':'Global Pi Market'} if pid==PARTNER else None,'_read_partner_offer':lambda oid:self.offer if oid=='offer1' else None,
                 'load_json':load,'load_json_path':lambda p,default=None:self.catalog if p.name=='full_catalog.json' else load(p,default),
                 'load_json_files':lambda p:[{'data':load(f)} for f in Path(p).glob('*.json')],
                 'pool_next_id':lambda:'pool_007','now_iso':lambda:'2026-10-08T18:00:00Z','render_template':render,
                 'default_pool_message':lambda *a:'#ThePioneerForest selected pool','pool_name_exists':lambda name:False,
                 'run_catalog_refresh':lambda:{'ran':self.refresh_ok,'exit_code':0 if self.refresh_ok else 1},
                 'create_pool_from_browser':purchase,'save_json_path':write_audit}
        tree=ast.parse((ROOT/'update/payload/ui/app.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['_paid_partner_pool_selection','partner_order_prepare_pool','partner_order_plant_selected_pool']]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'routes','exec'),self.ns)
        self.app.add_url_rule('/inbox','partner_portal_inbox',lambda:'inbox')
        self.app.add_url_rule('/pool/<pool_id>','pool_detail',lambda pool_id:pool_id)
        self.client=self.app.test_client()
    def tearDown(self): self.tmp.cleanup()
    def prepare(self,rid=RID): return self.client.post(f'/partners/{PARTNER}/requests/{rid}/prepare-pool')
    def plant(self,**changes):
        form={'confirm':'YES','confirm_offer':'yes','revision':self.context.get('draft',{}).get('revision',''),'pool_name':'GPM Mission Pool','tree_nation_message':'#ThePioneerForest GPM'};form.update(changes)
        return self.client.post(f'/partners/{PARTNER}/requests/{RID}/plant-selected-pool',data=form)
    def test_prepare_no_purchase_exact_option_and_stable_reservation(self):
        self.assertEqual(self.prepare().status_code,200);self.assertFalse(self.purchases)
        self.assertEqual(self.context['choice']['key'],'716:3493');self.assertEqual(self.context['selected']['quantity_needed'],48)
        self.assertEqual(self.prepare().status_code,200);self.assertEqual(self.context['draft']['pool_id'],'pool_007')
    def test_unpaid_and_wrong_hash_blocked(self):
        for update in [{'status':'payment_pending'},{'status':'planting_pending','payment_reference':'b'*64}]:
            self.order.update(update);self.assertEqual(self.prepare().status_code,409)
        self.assertFalse(self.purchases)
    def test_missing_or_changed_offer_blocked(self):
        self.offer['choices'][0]['trees']=47;self.assertEqual(self.prepare().status_code,409)
        self.offer={};self.assertEqual(self.prepare().status_code,409);self.assertFalse(self.purchases)
    def test_stock_price_estimate_and_missing_species_blocked(self):
        for update in [{'stock':47},{'price':.36},{'life_time_CO2':21},{'id':999}]:
            self.catalog=copy.deepcopy(CAT);self.catalog['projects'][0]['species'][0].update(update)
            self.assertEqual(self.prepare().status_code,409)
        self.assertFalse(self.purchases)
    def test_approval_and_revision_required(self):
        self.prepare()
        for update in [{'confirm':'yes'},{'confirm_offer':''},{'revision':'bad'},{'tree_nation_message':'no hashtag'}]:
            self.assertGreaterEqual(self.plant(**update).status_code,400)
        self.assertFalse(self.purchases)
    def test_refresh_and_changed_catalog_stop_before_purchase(self):
        self.prepare();self.refresh_ok=False;self.assertEqual(self.plant().status_code,409)
        self.refresh_ok=True;self.catalog['projects'][0]['species'][0]['stock']=1
        self.assertEqual(self.plant().status_code,409);self.assertFalse(self.purchases)
    def test_success_ownership_order_reference_and_repeat_no_purchase(self):
        self.prepare();self.assertEqual(self.plant().status_code,200)
        args=self.purchases[0];self.assertEqual(args[5]['species_id'],3493);self.assertEqual(args[5]['project_id'],716);self.assertEqual(args[5]['quantity_needed'],48)
        self.assertEqual(args[8:10],('partner',PARTNER))
        pool=json.loads((self.root/'co2-pool/pools/pool_007.json').read_text());self.assertEqual(pool['partner_request_id'],RID);self.assertEqual(pool['partner_payment_tx_hash'],HASH)
        self.assertEqual(self.plant().status_code,302);self.assertEqual(len(self.purchases),1)
    def test_ambiguous_failure_blocks_repeat(self):
        self.prepare();self.fail=True;self.assertEqual(self.plant().status_code,409)
        self.fail=False;self.assertEqual(self.plant().status_code,409);self.assertEqual(self.prepare().status_code,409)
        self.assertEqual(len(self.purchases),1)
    def test_reserved_id_collision_stops_before_purchase(self):
        self.prepare();write_audit(self.root/'co2-pool/pools/pool_007.json',{})
        self.assertEqual(self.plant().status_code,409);self.assertFalse(self.purchases)
    def test_distinct_orders_reserve_distinct_ids(self):
        self.prepare();other=RID.replace('11111111','22222222',1)
        write_audit(self.root/'partner-pools/portal-inbox/event2.json',dict(EVENT,offer_request_id=other))
        write_audit(self.root/f'partner-pools/payment-matches/{other}.json',dict(AUDIT,request_id=other))
        self.order=dict(ORDER,id=other);self.assertEqual(self.prepare(other).status_code,200);self.assertEqual(self.context['draft']['pool_id'],'pool_008')
    def test_cross_site_and_unknown_request_blocked(self):
        r=self.client.post(f'/partners/{PARTNER}/requests/{RID}/prepare-pool',headers={'Origin':'https://other.test'})
        self.assertEqual(r.status_code,403);self.assertEqual(self.prepare('bad').status_code,404)
    def test_co2_basis_keeps_exact_quantity(self):
        event=dict(EVENT,selected_basis='co2');write_audit(self.root/'partner-pools/portal-inbox/event.json',event);self.offer['search']['basis']='co2'
        self.prepare();self.assertEqual(self.plant().status_code,200);self.assertEqual(self.purchases[0][4],960);self.assertEqual(self.purchases[0][5]['quantity_needed'],48)
if __name__=='__main__':unittest.main()
