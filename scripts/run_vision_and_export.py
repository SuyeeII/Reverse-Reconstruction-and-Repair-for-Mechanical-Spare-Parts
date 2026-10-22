"""Run a new design task and export its generated CAD/FEM scene."""
from pathlib import Path
import argparse,subprocess,sys,json
R=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--case-id',required=True);p.add_argument('--task-file');a=p.parse_args()
command=[sys.executable,str(R/'scripts/vision_runtime.py'),'run',a.run_id,a.case_id]
if a.task_file:command+=['--task-file',a.task_file]
code=subprocess.run(command,cwd=R).returncode
if (R/'runs'/a.run_id/'state.json').exists():
 subprocess.run([sys.executable,str(R/'scripts/export_evidence.py'),'--run-id',a.run_id],cwd=R,check=True)
(R/'reports').mkdir(exist_ok=True)
(R/'reports'/f'{a.run_id}-completion.json').write_text(json.dumps({'run_id':a.run_id,'completed':True,'exit_code':code}))
raise SystemExit(code)
