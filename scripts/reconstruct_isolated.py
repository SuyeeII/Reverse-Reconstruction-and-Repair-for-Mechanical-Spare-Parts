"""Narrow process boundary. No renderer imports and no truth reads.
Python audit denies oracle paths. Host user namespace isolation is unavailable;
this is an input contract and read-audit boundary, not an OS security claim.
"""
import argparse,sys,json,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');p.add_argument('--backend',choices=['legacy_opencv','colmap_metric'],default='colmap_metric');args=p.parse_args()
root=Path(__file__).resolve().parents[1];out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True);audit=[]
def observe(event,values):
    if event!='open' or not isinstance(values[0],(str,bytes)):return
    name=Path(values[0]).resolve()
    if 'oracle' in name.parts:raise PermissionError('TRUTH_ACCESS_REJECTED')
    if root in name.parents and '.venv' not in name.parts:audit.append(str(name))
sys.addaudithook(observe)
from repairforge.reconstruct import reconstruct,reconstruct_colmap_metric
try:
 compute=reconstruct_colmap_metric if args.backend=='colmap_metric' else reconstruct
 r=compute(args.input,args.output);print(json.dumps(r,ensure_ascii=False))
except Exception as e:
 (out/'failure.json').write_text(json.dumps({'status':'RECONSTRUCTION_FAILED','error_type':type(e).__name__,'reason':str(e),'truth_access':False},ensure_ascii=False,indent=2)+'\n');raise
finally:
 (out/'read_audit.json').write_text(json.dumps({'python_file_accesses':sorted(set(audit)),'truth_access_denied':True,'os_isolation':'user namespaces unavailable; no OS sandbox claim','scope':'narrow reconstruct process; evaluator and input author separate'},ensure_ascii=False,indent=2)+'\n')
