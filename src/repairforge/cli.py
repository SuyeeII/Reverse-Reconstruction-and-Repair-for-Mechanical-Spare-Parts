import sys,os,json,contextlib,traceback
from pathlib import Path
from .service import Service
from .authority import Rejected
root=Path(os.environ.get('REPAIRFORGE_ROOT',Path(__file__).resolve().parents[2])).resolve();service=Service(root)
try:
    request=json.load(sys.stdin)
    if request['tool']=='create_run':result=service.create(**request['args'])
    else:
        with (root/'reports/tool-process.log').open('a') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):result=service.dispatch(request['tool'],request['args'])
    print(json.dumps({'ok':True,'data':result},ensure_ascii=False,allow_nan=False))
except Exception as e:
    a=locals().get('request',{}).get('args',{});r=a.get('run_id')
    if r and service.store.path(r).is_dir():service.store.event(r,'tool_rejected' if isinstance(e,Rejected) else 'tool_error',tool=locals().get('request',{}).get('tool'),decision_id=a.get('decision_id'),reason=str(e),error_type=type(e).__name__)
    print(json.dumps({'ok':False,'error':type(e).__name__,'reason':str(e)},ensure_ascii=False));sys.exit(1)
