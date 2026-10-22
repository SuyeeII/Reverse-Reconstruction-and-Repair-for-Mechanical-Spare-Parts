"""Loopback-only project evidence UI. Denies oracle, secrets and arbitrary files."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
import argparse,urllib.parse,json,base64,tempfile,uuid,subprocess,os,importlib.util
ROOT=Path(__file__).resolve().parents[1]
class EvidenceHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/jobs/'):
            import re
            rid=self.path[len('/api/jobs/'):]
            if not re.fullmatch(r'real_[a-f0-9]{12}_mimo',rid):self.send_error(400);return
            p=ROOT/'runs'/rid
            readj=lambda f:json.loads(f.read_text()) if f.exists() else None
            state=readj(p/'state.json');accept=readj(p/'independent_acceptance.json');model=readj(p/'model_report.json')
            failure=readj(ROOT/'reports'/f'{rid}-startup-failure.json');completion=readj(ROOT/'reports'/f'{rid}-completion.json')
            result={'run_id':rid,'state_version':state.get('state_version') if state else None,'completed':bool(model or failure or completion),'startup_failure':failure,'completion':completion,'acceptance':accept,'scene':'data/'+rid+'/scene.json' if (ROOT/'web/data'/rid/'scene.json').exists() else None}
            body=json.dumps(result,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        return super().do_GET()

    def do_POST(self):
        if self.path!='/api/import-and-run':self.send_error(404);return
        if self.headers.get('Origin') not in [None,'http://127.0.0.1:'+str(self.server.server_port)]:self.send_error(403);return
        count=int(self.headers.get('Content-Length','0'))
        if not 0<count<=80*1024*1024:self.send_error(413);return
        try:
            data=json.loads(self.rfile.read(count));photos=data['images']
            if not 12<=len(photos)<=24:raise ValueError('请提供12–24张图像')
            task=data['task'].strip()
            if not task or len(task)>8000:raise ValueError('请提供任务，最多8000字')
            case='real_'+uuid.uuid4().hex[:12]
            spec=importlib.util.spec_from_file_location('repairforge_import',ROOT/'scripts/import_photos.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory(prefix='repairforge-upload-') as tmp:
                p=Path(tmp);(p/'images').mkdir()
                for i,item in enumerate(photos):
                    ext=item['extension'].lower()
                    if ext not in ['png','jpg','jpeg']:raise ValueError('仅支持PNG/JPEG')
                    raw=base64.b64decode(item['data'],validate=True)
                    if not raw or len(raw)>8*1024*1024:raise ValueError('单张图像最大8MB')
                    (p/'images'/f'{i:02d}.{ext}').write_bytes(raw)
                (p/'scale.json').write_text(json.dumps(data['scale']))
                (p/'requirements.json').write_text(json.dumps(data['requirements']))
                target=module.import_case(case,p/'images',p/'scale.json',p/'requirements.json')
            task_file=target/'first_input.txt';task_file.write_text(task)
            run=case+'_mimo';env=dict(os.environ);env.update(REPAIRFORGE_ROOT=str(ROOT),AGH_HOME=str(ROOT/'.agh'),AGNES_PROFILE='local-dev',PYTHONPATH=str(ROOT/'src'))
            log=(ROOT/'reports'/f'{run}.log').open('w')
            proc=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_vision_and_export.py'),'--run-id',run,'--case-id',case,'--task-file',str(task_file)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            result={'ok':True,'run_id':run,'case_id':case,'process_id':proc.pid,'status':'已保存原始上传，单任务AGH会话启动；验收结果尚未产生。'}
            status=202
        except Exception as e:result={'ok':False,'reason':str(e)};status=400
        body=json.dumps(result,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def translate_path(self,path):
        clean=urllib.parse.unquote(urllib.parse.urlparse(path).path)
        if clean.startswith('/assets/'):
            rel=Path(clean[8:]);target=(ROOT/rel).resolve()
            try:canonical=target.relative_to(ROOT)
            except ValueError:return str(ROOT/'web/404-missing')
            if not canonical.parts or canonical.parts[0] not in ('inputs','runs','reports','delivery'):return str(ROOT/'web/404-missing')
            return str(target)
        target=(ROOT/'web'/clean.lstrip('/')).resolve()
        return str(target) if ROOT/'web' in [target,*target.parents] else str(ROOT/'web/404-missing')
    def log_message(self,*args):pass
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=48765);a=p.parse_args()
ThreadingHTTPServer(('127.0.0.1',a.port),EvidenceHandler).serve_forever()
