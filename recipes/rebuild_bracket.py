"""Rebuild a part from the included views and export its repaired design."""
from pathlib import Path
import sys,time,json
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'src'))
from repairforge.service import Service
s=Service(root);rid='example_'+str(time.time_ns());s.create(rid,'bracket',method='image-to-repaired-part')
def call(name,**kwargs):
 v=s.store.state(rid)['state_version']
 return s.dispatch(name,{'run_id':rid,'decision_id':f'{name}-{v}','state_version':v,**kwargs})
call('reconstruct_views');call('inspect_features');c=call('propose_cad')['candidate'];first=call('evaluate_design',candidate_id=c['candidate_id'])
repaired=call('revise_cad',parent_candidate_id=c['candidate_id'],changes={'thickness_mm':7.4,'fillet_mm':6.0})['candidate']
result=call('evaluate_design',candidate_id=repaired['candidate_id'])
export=call('export_manufacturing',candidate_id=repaired['candidate_id'])
print(json.dumps({'run_id':rid,'output':str(s.store.path(rid)),'evaluation':result,'manufacturing':export},ensure_ascii=False,indent=2))
