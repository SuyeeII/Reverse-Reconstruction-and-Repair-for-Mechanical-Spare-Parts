"""Submit one image-bearing design request through the local AGH connection."""
from pathlib import Path
import os,json,subprocess,sys
from repairforge.authority import read,write
from repairforge.service import Service
R=Path(__file__).resolve().parents[1]
if len(sys.argv)<4 or sys.argv[1]!='run':raise SystemExit('run RUN_ID CASE_ID [--task-file PATH]')
rid,case=sys.argv[2:4]
connection=read(R/'runtime/connection.json')
env=dict(os.environ,REPAIRFORGE_ROOT=str(R),AGH_HOME=str(R/'.agh'),AGNES_PROFILE='local-dev',PYTHONPATH=str(R/'src'),RF_RECEIPT_PORT=str(connection['gateway_port']))
key=env.get('REPAIRFORGE_MODEL_API_KEY') or env.get('DEEPSEEK_API_KEY')
if not key:raise SystemExit('Set REPAIRFORGE_MODEL_API_KEY')
env['AGNES_SECRET_REPAIRFORGE_MIMO_KEY']=key
service=Service(R);service.create(rid,case,'AGH_native_vision')
run=service.store.path(rid)
task=(R/'configs/task.txt').read_text().replace('{run_id}',rid).replace('{case_id}',case)
if '--task-file' in sys.argv:
 supplied=Path(sys.argv[sys.argv.index('--task-file')+1]).resolve()
 if not supplied.is_relative_to((R/'inputs'/case).resolve()):raise ValueError('Task file must belong to the selected input')
 task=supplied.read_text()
names=sorted(p.name for p in (R/'inputs'/case/'images').iterdir() if p.suffix.lower() in ('.png','.jpg','.jpeg'))
if len(names)<3:raise ValueError('At least three input views are needed')
frames=[names[i] for i in (0,len(names)//3,2*len(names)//3)]
write(run/'user_task.json',{'first_input':task,'case_id':case,'initial_frames':frames,'attachment_metadata':{'source':read(R/'inputs'/case/'source.json'),'scale':read(R/'inputs'/case/'scale.json')}})
code=subprocess.run([str(R/'runtime/node'),str(R/'scripts/native_vision.mjs'),'run',rid],cwd=R,env=env,timeout=900).returncode
raise SystemExit(code)
