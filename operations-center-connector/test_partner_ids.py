import ast,re,copy,json,tempfile,hashlib,subprocess,shutil
from pathlib import Path
r=Path(__file__).resolve().parent.parent;p=r/'operations-center-connector/partner-id-update'
tree=ast.parse((p/'payload/ui/app.py').read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_partner_id','_partner_form_record')]
records=[{'id':'omc','name':'OMC'},{'id':'global-pi-market','name':'Global Pi Market'}]
ns={'re':re,'now_iso':lambda:'test','_read_partner':lambda id:next((x for x in records if x['id']==id),None),'_all_partners':lambda:records,'PARTNER_COLORS':{'background':'#183030'}}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'tested-app','exec'),ns)
form={'name':'New Partner Name','section_title':'New Mission','partner_id':'npm'}
new=ns['_partner_form_record'](form);assert new['id']=='npm' and new['login_id']=='npm'
for id in ('','omc','gpm','wrong id'):
 try:ns['_partner_form_record']({**form,'partner_id':id})
 except ValueError:pass
 else:raise AssertionError(id)
gpm={**new,'id':'global-pi-market','name':'Global Pi Market','colors':{'background':'#183030'},'pool_ids':['existing-pool']}
saved=ns['_partner_form_record']({'name':'Global Pi Market','section_title':'GPM Mission','login_id':'gpm','color_background':'#183030'},gpm)
assert saved['id']==gpm['id'] and saved['pool_ids']==gpm['pool_ids'] and saved['colors']==gpm['colors'] and saved['login_id']=='gpm'
try:ns['_partner_form_record']({'name':'Global Pi Market','section_title':'GPM Mission','login_id':'omc'},gpm)
except ValueError:pass
else:raise AssertionError('collision accepted')
# Install over the exact currently supplied Admin files, repeat, and preserve user data.
manifest=json.loads((p/'manifest.json').read_text())
for entry in manifest['files']:entry['new_sha256']=hashlib.sha256((p/'payload'/entry['path']).read_bytes()).hexdigest()
(p/'manifest.json').write_text(json.dumps(manifest,indent=2))
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp)
 originals={'ui/app.py':'page-launch-update/payload/ui/app.py','ui/templates/partner_form.html':'partner-editor-update/payload/ui/templates/partner_form.html','ui/templates/partner_detail.html':'page-launch-update/payload/ui/templates/partner_detail.html','ui/portal_sync.py':'order-update/payload/ui/portal_sync.py'}
 for dest,src in originals.items():
  f=root/dest;f.parent.mkdir(parents=True,exist_ok=True);shutil.copy(r/'operations-center-connector'/src,f)
 data=root/'partners/gpm.json';data.parent.mkdir();data.write_text('unchanged-user-data')
 for _ in range(2):
  result=subprocess.run(['python3',str(p/'install.py'),str(root)],capture_output=True,text=True);assert result.returncode==0,result.stdout+result.stderr
 assert data.read_text()=='unchanged-user-data'
print('Admin creation, aliases, collision rejection and installer preservation passed')
