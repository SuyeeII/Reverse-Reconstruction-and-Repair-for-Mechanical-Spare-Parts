"""Start the project workbench and its optional AGH connection."""
from pathlib import Path
import argparse,os,subprocess,socket,time,json,signal,hashlib
R=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=48905);p.add_argument('--live',action='store_true');p.add_argument('--foreground',action='store_true');a=p.parse_args()
env=dict(os.environ,REPAIRFORGE_ROOT=str(R),AGH_HOME=str(R/'.agh'),AGNES_PROFILE='local-dev',PYTHONPATH=str(R/'src'),OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='4',MKL_NUM_THREADS='4',NUMEXPR_NUM_THREADS='4',RF_RECEIPT_PORT=str(a.port+3),RF_NATIVE_WEB_PORT=str(a.port+2),LD_LIBRARY_PATH=str(R/'runtime/system/usr/lib/x86_64-linux-gnu'),NO_PROXY='127.0.0.1,localhost')
os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:4]);(R/'reports').mkdir(exist_ok=True)
for port in [a.port]+([a.port+1,a.port+2,a.port+3] if a.live else []):
    with socket.socket() as check:check.bind(('127.0.0.1',port))
owned=[]
def start(label,command):
    process=subprocess.Popen(command,cwd=R,env=env,stdout=(R/'reports'/('vision-'+label+'.log')).open('a'),stderr=subprocess.STDOUT,start_new_session=True);owned.append(process)
    (R/'reports'/('vision-'+label+'.pid')).write_text(str(process.pid))
    return process
def cleanup():
    for process in reversed(owned):
        if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
    for process in owned:process.wait(timeout=10)
if a.live:
    (R/'runtime').mkdir(exist_ok=True)
    (R/'runtime/connection.json').write_text(json.dumps({'gateway_port':a.port+3,'web_port':a.port+2,'viewer_port':a.port}))
    key=env.get('REPAIRFORGE_MODEL_API_KEY') or env.get('DEEPSEEK_API_KEY')
    if not key:raise SystemExit('Protected model environment is required for live mode')
    env['AGNES_SECRET_REPAIRFORGE_MIMO_KEY']=key
    profile=R/'.agh/profiles/local-dev/profile.yaml'
    if profile.exists():raise SystemExit('Existing project home: use its current daemon or a fresh extraction; active runtime will not be replaced')
    profile.parent.mkdir(parents=True,exist_ok=True)
    text=(R/'configs/agh-profile.yaml').read_text().replace('127.0.0.1:48908','127.0.0.1:'+str(a.port+3));profile.write_text(text)
    model=json.loads((R/'model.selection.json').read_text());model.update(configuration_sha256=hashlib.sha256(text.encode()).hexdigest(),transport='http://127.0.0.1:'+str(a.port+3)+'/v1',profile_scope=str(profile))
    (R/'model.selection.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n')
    try:
        start('gateway',[str(R/'.venv/bin/python'),'-m','repairforge.gateway'])
        daemon=start('daemon',[str(R/'runtime/node'),str(R/'runtime/agh/daemon.mjs'),'--profile','local-dev','--home',str(R/'.agh'),'--workspace',str(R),'--data-dir',str(R/'.agh/data'),'--web-addr','127.0.0.1:'+str(a.port+1),'--web-origin','http://127.0.0.1:'+str(a.port+2)])
        for _ in range(160):
            if daemon.poll() is not None:raise RuntimeError('Own daemon exited')
            ready=subprocess.run([str(R/'runtime/node'),str(R/'scripts/vision_admin.mjs')],cwd=R,env=env,capture_output=True,text=True,timeout=5)
            if ready.returncode==0:break
            time.sleep(.25)
        else:raise RuntimeError('Own daemon readiness timeout')
        activation=subprocess.run([str(R/'runtime/node'),str(R/'scripts/native_vision.mjs'),'activate'],cwd=R,env=env,stdout=(R/'reports/vision-activation.log').open('w'),stderr=subprocess.STDOUT,timeout=90)
        if activation.returncode:raise RuntimeError('Native domain plugin activation failed')
        status=subprocess.run([str(R/'runtime/node'),str(R/'scripts/vision_admin.mjs')],cwd=R,env=env,capture_output=True,text=True,check=True,timeout=10)
        package=next(x for x in json.loads(status.stdout)['packages']['packages'] if x['id']=='@repairforge/vision-domain-v3')
        if package.get('actual')!='running' or package.get('trusted') is not True or package.get('version')!=json.loads((R/'plugin/package.json').read_text())['version']:raise RuntimeError('Domain package not ready')
        (R/'reports/vision-bootstrap-readiness.json').write_text(json.dumps({'ready':True,'package':package,'root':str(R),'ports':[a.port+i for i in range(4)]},indent=2)+'\n')
        start('native-web',[str(R/'runtime/node'),str(R/'runtime/agh/agnes.mjs'),'serve','--port',str(a.port+2)])
    except Exception:cleanup();raise
viewer=start('viewer',[str(R/'.venv/bin/python'),str(R/'scripts/serve.py'),'--port',str(a.port)])
print('机械备件逆向重建与修复: http://127.0.0.1:'+str(a.port)+(' 路 live MiMo vision/tools' if a.live else ' 路 local workbench'),flush=True)
if a.foreground:
    try:viewer.wait()
    except KeyboardInterrupt:cleanup()
