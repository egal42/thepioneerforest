import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import Mock

ROOT = Path(__file__).parent / 'partner-payment-update'
sys.path.insert(0, str(ROOT / 'payload/ui'))
from partner_payment import verify_payment, check_match, write_audit, payment_lock
HASH='a'*64
PARTNER='global-pi-market'
RID='11111111-1111-1111-1111-07dff44edb4a'
WALLET='TPF-WALLET'
SOURCE=[{'network':'mainnet','wallet_address':WALLET,'enabled':True}]

def http(memo='',amount='300.0000000',recipient=WALLET,successful=True,count=1):
    tx={'hash':HASH,'successful':successful,'operation_count':count,'memo_type':'text' if memo else 'none','memo':memo,'created_at':'2026-10-08T14:00:01Z'}
    op={'id':'1','type':'payment','asset_type':'native','to':recipient,'from':'GPM-SENDER','amount':amount,'transaction_hash':HASH}
    def get(url,**kw):
        value={'_embedded':{'records':[op]*count}} if '/operations?' in url else tx
        return Mock(raise_for_status=lambda:None,json=lambda:value)
    return get

class Verification(unittest.TestCase):
    def test_manual_without_memo(self):
        evidence=verify_payment(HASH,SOURCE,http())
        check_match(evidence,PARTNER,RID,'300','manual','GPM confirmed this sender and selected offer via DM and receipt.')
        self.assertEqual(evidence['blockchain_memo'],'')
    def test_exact_decimal(self):
        evidence=verify_payment(HASH,SOURCE,http(amount='300.0000001'))
        with self.assertRaises(ValueError): check_match(evidence,PARTNER,RID,'300','manual','GPM confirmation checked')
    def test_wrong_recipient_failed_and_batch(self):
        for get in [http(recipient='OTHER'),http(successful=False),http(count=2)]:
            with self.assertRaises(ValueError): verify_payment(HASH,SOURCE,get)
    def test_memo_and_manual_note_rules(self):
        evidence=verify_payment(HASH,SOURCE,http(memo='GLOBAL-07DFF44EDB4A'))
        check_match(evidence,PARTNER,RID,'300','memo','')
        for method,note in [('bad','reason'),('manual','short')]:
            with self.assertRaises(ValueError): check_match(evidence,PARTNER,RID,'300',method,note)
        evidence['blockchain_memo']='wrong'
        with self.assertRaises(ValueError): check_match(evidence,PARTNER,RID,'300','memo','')
    def test_lock_and_atomic_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            with payment_lock(folder):
                with self.assertRaises(ValueError):
                    with payment_lock(folder): pass
            path=Path(folder)/'audit.json'; write_audit(path,{'status':'prepared'})
            self.assertEqual(json.loads(path.read_text())['status'],'prepared')

from flask import Flask, request, redirect, url_for
import requests
import portal_sync

class Route(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.entries=[];self.classifications={};self.online={};self.calls=0;self.fail=False;self.fail_local=False;self.donations={}
        self.app=Flask(__name__)
        def load_json(path, default=None):
            return json.loads(Path(path).read_text()) if Path(path).exists() else default
        def load_files(path):
            return [{'data':json.loads(f.read_text())} for f in Path(path).glob('*.json')]
        def signed(base,secret,method,path,body):
            self.calls+=1
            if self.fail: raise portal_sync.SyncError('network unavailable')
            previous=self.online.get(body['requestId'])
            if body['paymentReference'] in self.online.values() and previous != body['paymentReference']:
                raise portal_sync.SyncError('duplicate hash')
            self.online[body['requestId']]=body['paymentReference']
            return {'status':'planting_pending','repeated':bool(previous)}
        portal_sync.signed_request=signed
        def ledger(entry):
            if self.fail_local: raise OSError('simulated disk error')
            if not any(e['tx_hash']==entry['tx_hash'] for e in self.entries): self.entries.append(entry)
        self.ns={'app':self.app,'request':request,'redirect':redirect,'url_for':url_for,'re':__import__('re'),
                 'os':os,'ACTIVE_ENV':'mainnet','DATA_ROOT':self.root,'requests':Mock(get=http(),RequestException=requests.RequestException),
                 '_read_partner':lambda pid:{'name':'Global Pi Market'} if pid==PARTNER else None,
                 'load_json':load_json,'load_json_files':load_files,'load_wallet_classification':lambda h:self.classifications.get(h),
                 'load_fund_ledger':lambda:{'entries':self.entries},'load_wallet_sources':lambda:SOURCE,
                 'donation_files_with_tx_hash':lambda:self.donations,'now_iso':lambda:'2026-10-08T14:40:00Z',
                 'get_fund':lambda fid:{'name':'Partner Pool Payments','fund_type':'base','workflow':'record_only','status':'active'},
                 'add_fund_ledger_entry':ledger,'save_wallet_classification':lambda h,d:self.classifications.update({h:d})}
        tree=ast.parse((ROOT/'payload/ui/app.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='partner_portal_order')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'app-route','exec'),self.ns)
        self.app.add_url_rule('/inbox','partner_portal_inbox',lambda:'ok')
        self.client=self.app.test_client()
        write_audit(self.root/'partner-pools/portal-inbox/event.json',{'event_type':'offer.selected','partner_id':PARTNER,'offer_request_id':RID,'selected_price_pi':'300'})
    def tearDown(self): self.temp.cleanup()
    def post(self,**values):
        form={'action':'confirm-payment','confirm_action':'yes','confirm_sender':'yes','payment_reference':HASH,
              'match_method':'manual','match_note':'GPM confirmed the sender and this selected offer; receipt checked.'}
        form.update(values)
        return self.client.post(f'/partners/{PARTNER}/requests/{RID}/order',data=form)
    def test_success_and_repeat(self):
        self.assertEqual(self.post().status_code,302)
        self.assertEqual(self.post().status_code,302)
        self.assertEqual(len(self.entries),1);self.assertFalse(self.donations)
        audit=json.loads((self.root/f'partner-pools/payment-matches/{RID}.json').read_text())
        self.assertEqual(audit['status'],'complete');self.assertEqual(audit['blockchain_memo'],'')
    def test_rejections_before_online(self):
        for changes in [{'confirm_sender':''},{'match_note':'short'},{'match_method':'memo'}]:
            self.assertGreaterEqual(self.post(**changes).status_code,400)
        self.assertEqual(self.calls,0)
    def test_existing_classification_and_contribution(self):
        self.classifications[HASH]={'fund_id':'other'}
        self.assertEqual(self.post().status_code,409);self.classifications.clear()
        self.donations[HASH]={'file':'pending.json'}
        self.assertEqual(self.post().status_code,409);self.assertEqual(self.calls,0)
    def test_network_failure_then_retry(self):
        self.fail=True;self.assertEqual(self.post().status_code,409)
        self.assertFalse(self.entries);self.fail=False
        self.assertEqual(self.post().status_code,302);self.assertEqual(len(self.entries),1)
    def test_local_failure_after_online_then_retry(self):
        self.fail_local=True;self.assertEqual(self.post().status_code,409)
        self.assertEqual(self.online[RID],HASH);self.assertFalse(self.entries)
        self.fail_local=False;self.assertEqual(self.post().status_code,302)
        self.assertEqual(len(self.entries),1)
    def test_transaction_reserved_other_order(self):
        write_audit(self.root/'partner-pools/payment-matches/other.json',{'tx_hash':HASH,'request_id':'other','status':'prepared'})
        self.assertEqual(self.post().status_code,409);self.assertEqual(self.calls,0)
    def test_wrong_amount(self):
        self.ns['requests'].get=http(amount='299')
        self.assertEqual(self.post().status_code,409);self.assertEqual(self.calls,0)
    def test_cross_site(self):
        response=self.client.post(f'/partners/{PARTNER}/requests/{RID}/order',headers={'Origin':'https://other.test'})
        self.assertEqual(response.status_code,403)

if __name__=='__main__':unittest.main()
