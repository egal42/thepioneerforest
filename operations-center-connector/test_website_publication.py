import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'website-data-update/payload/ui'))
sys.path.insert(0, str(Path(__file__).parent))
import website_publication as sync
from website_calculation import calculate

def write(root, name, data):
    path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data))

def purchase(q=48, rate=20, token='abcdef', tree=9740016, payment=6662435):
    return {'quantity': q, 'total_co2_kg': q*rate, 'payment_id': payment,
            'created_at': '2026-10-08T12:00:00Z', 'certificates': [{'tree_id': tree,
            'certificate_url': 'https://tree-nation.com/certificate/'+token}]}

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.state = self.root/'website-data/publication.json'
        write(self.root,'co2-pool/pools/pool_007.json',purchase())
        self.online = {'schema':'tpf_website_summary_v1','minimumCo2KgPerPi':'20','impact':None,'revision':None,'publishedAt':None}
        self.posts=[]
    def tearDown(self): self.tmp.cleanup()
    def api(self, origin, secret, method, path, payload=None):
        self.assertEqual(path, '/api/website-data/admin')
        if method == 'POST':
            self.assertEqual(payload['expectedRevision'],self.online['revision'])
            self.posts.append(payload.copy())
            self.online = {k:v for k,v in payload.items() if k not in ('environment','expectedRevision')}
            self.online.update(revision=str(len(self.posts))*64,publishedAt='2026-10-08T12:00:00Z')
        return self.online.copy()
    def activate(self):
        c=calculate(self.root)
        return sync.handle_form({'action':'enable','confirmed':'yes','fingerprint':c['fingerprint']}, self.state, {}, 'mainnet','https://isolated.invalid','fake',self.root)
    def cycle(self,config=None,env='mainnet'):
        sync.tick(self.state,self.root,config or {},env,'https://isolated.invalid','fake')
    def test_duplicate_proofs_history_raw_and_pool_count_once(self):
        write(self.root,'plantings/duplicate.json',purchase())
        write(self.root,'project-intelligence/history/historical_ledger_import.json',{'records':[{'annotations':[{'impact':{'trees':48,'co2_kg':960},'links':{'certificate':'https://tree-nation.com/certificate/abcdef'}}]}]})
        write(self.root,'tree-nation/result.json',{'request':{'payload':{'quantity':48}},'response':{'status_code':200,'json':{'status':'ok','payment_id':6662435,'trees':[{'id':9740016,'certificate_url':'https://tree-nation.com/certificate/abcdef','species_life_time_CO2':20}]}}})
        write(self.root,'co2-pool/allocations/share.json',{'trees':1000})
        c=calculate(self.root);self.assertEqual((c['trees'],c['co2']),(48,'960'));self.assertFalse(c['issues']);self.assertEqual(c['duplicates'],3)
    def test_conflict_missing_proof_and_sandbox_rejected(self):
        write(self.root,'plantings/conflict.json',purchase(q=49));self.assertTrue(calculate(self.root)['issues'])
        (self.root/'plantings/conflict.json').unlink()
        p=purchase();p['certificates'][0]['certificate_url']='https://youcannevertestenough.tree-nation.com/certificate/abcdef'
        write(self.root,'plantings/sandbox.json',p);self.assertTrue(calculate(self.root)['issues'])
    def test_enable_once_new_purchase_and_setting_sync_automatically(self):
        with patch.object(sync,'signed_request',side_effect=self.api):
            self.assertTrue(self.activate()['ok']);self.assertEqual(len(self.posts),1)
            self.cycle();self.assertEqual(len(self.posts),1)
            write(self.root,'plantings/new.json',purchase(q=2,rate=50,token='123abc',tree=999,payment=123))
            self.cycle();self.assertEqual(self.online['impact']['trees'],'50');self.assertEqual(self.online['impact']['estimatedCo2Kg'],'1060')
            self.cycle({'min_co2_per_pi':21});self.assertEqual(self.online['minimumCo2KgPerPi'],'21')
            self.assertTrue(sync.screen(self.state,{'min_co2_per_pi':21},'mainnet','x','x',self.root)['current'])
    def test_failure_retries_and_missing_purchase_blocks(self):
        with patch.object(sync,'signed_request',side_effect=self.api): self.activate()
        old=self.online.copy()
        with patch.object(sync,'signed_request',side_effect=sync.SyncError('offline')): self.cycle()
        self.assertFalse(sync.screen(self.state,{},'mainnet','x','x',self.root)['current'])
        with patch.object(sync,'signed_request',side_effect=self.api): self.cycle()
        self.assertTrue(sync.screen(self.state,{},'mainnet','x','x',self.root)['current'])
        (self.root/'co2-pool/pools/pool_007.json').unlink()
        with patch.object(sync,'signed_request',side_effect=self.api): self.cycle()
        self.assertEqual(self.online,old);self.assertEqual(sync._read(self.state)['status'],'attention')
    def test_no_enable_no_network_and_no_test_publication(self):
        with patch.object(sync,'signed_request') as api:
            self.cycle();self.cycle(env='sandbox');api.assert_not_called()
    def test_stale_initial_check_and_foreign_overwrite_stop(self):
        with patch.object(sync,'signed_request',side_effect=self.api):
            bad=sync.handle_form({'action':'enable','confirmed':'yes','fingerprint':'old'},self.state,{},'mainnet','x','x',self.root)
            self.assertFalse(bad['ok']);self.activate()
            self.online['minimumCo2KgPerPi']='50';self.online['revision']='f'*64
            self.cycle();self.assertEqual(len(self.posts),1);self.assertIn('elsewhere',sync._read(self.state)['error'])
    def test_reviewed_correction_can_resume_without_routine_review(self):
        with patch.object(sync,'signed_request',side_effect=self.api):
            self.activate()
            self.online['minimumCo2KgPerPi']='50';self.online['revision']='f'*64
            self.cycle()
            c=calculate(self.root)
            result=sync.handle_form({'action':'reconcile','confirmed':'yes','fingerprint':c['fingerprint'],'reason':'Checked local setting against the records'},self.state,{},'mainnet','x','x',self.root)
            self.assertTrue(result['ok']);self.assertEqual(self.online['minimumCo2KgPerPi'],'20')
            self.assertEqual(len(sync._read(self.state)['corrections']),1)
            self.cycle();self.assertEqual(len(self.posts),2)

    def test_corrupt_state_and_record_never_show_green(self):
        self.state.parent.mkdir();self.state.write_text('{broken')
        self.assertFalse(sync.screen(self.state,{},'mainnet','x','x',self.root)['current'])
        write(self.root,'plantings/broken.json',{'certificates':42,'quantity':1,'total_co2_kg':20})
        self.assertTrue(calculate(self.root)['issues'])
    def test_lost_acknowledgment_does_not_duplicate_publication(self):
        with patch.object(sync,'signed_request',side_effect=self.api):self.activate()
        write(self.root,'plantings/new.json',purchase(q=2,token='123abc',tree=999,payment=123))
        def lose_ack(*args,**kwargs):
            result=self.api(*args,**kwargs)
            if args[2]=='POST': raise sync.SyncError('connection lost after save')
            return result
        with patch.object(sync,'signed_request',side_effect=lose_ack):self.cycle()
        self.assertEqual(len(self.posts),2)
        with patch.object(sync,'signed_request',side_effect=self.api):self.cycle()
        self.assertEqual(len(self.posts),2);self.assertEqual(sync._read(self.state)['status'],'current')

if __name__=='__main__': unittest.main()
