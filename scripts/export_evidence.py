"""Export saved results including unsuccessful runs. Does not run or alter solvers."""
from pathlib import Path
import argparse
from repairforge.authority import read,write
from repairforge.scene import export_run
R=Path(__file__).resolve().parents[1]
def export(ids=None):
    items=[]
    for f in sorted((R/'runs').glob('*/state.json')):
        s=read(f);p=f.parent
        if not(s['candidate_ids'] or (p/'features/features.json').exists() or (p/'reconstruction/failure.json').exists()):continue
        if ids is None or s['run_id'] in ids:
            x=export_run(R,s['run_id']);x['images']=['/assets/inputs/'+s['case_id']+'/images/'+im.name for im in sorted((R/'inputs'/s['case_id']/'images').glob('*')) if im.suffix.lower() in ('.png','.jpg','.jpeg')]
            if (p/'reconstruction/failure.json').exists() and 'reconstruction' not in x:x['reconstruction_failure']=read(p/'reconstruction/failure.json')
            for name,file in [('independent_acceptance','independent_acceptance.json'),('model_report','model_report.json')]:
                if (p/file).exists():
                    report=read(p/file);x[name]=report if name=='independent_acceptance' else {k:report.get(k) for k in ('session_id','request_models','actual_receipt_models','model_identity_pass','protocol_pass','elapsed_seconds')}
            x['input_source']=read(R/'inputs'/s['case_id']/'source.json')
            write(R/'web/data'/s['run_id']/'scene.json',x)
        status=s['candidate_ids'] and read(p/s['candidate_ids'][-1]/'candidate.json')['status'] or ('RECONSTRUCTION_FAILED' if (p/'reconstruction/failure.json').exists() else 'NEED_MORE_VIEWS')
        items.append(dict(run_id=s['run_id'],case_id=s['case_id'],method=s['method'],status=status,file='data/'+s['run_id']+'/scene.json'))
    items.sort(key=lambda x:x['run_id'])
    write(R/'web/data/index.json',items);return items
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id');a=p.parse_args();print('Exported',len(export([a.run_id] if a.run_id else None)))
