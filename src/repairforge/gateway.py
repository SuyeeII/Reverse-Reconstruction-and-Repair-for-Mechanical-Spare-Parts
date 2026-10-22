"""Transparent loopback receipt recorder, no prompt/response transformation.
Authorization stays in memory, no headers or credential values are logged.
"""
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import requests,json,time,uuid,hashlib,os
from .authority import write
UPSTREAM=os.environ.get('MODEL_BASE_URL', 'http://127.0.0.1:8317').rstrip('/')
ROOT=Path(__file__).resolve().parents[2]
def receipt(obj,status):
    return {'http_status':status,'response_id':obj.get('id'),'receipt_model':obj.get('model'),'usage':obj.get('usage')}
class Relay(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def do_GET(self):self.forward()
    def do_POST(self):self.forward()
    def log_message(self,*args):pass
    def forward(self):
        if self.path not in ['/v1/models','/v1/chat/completions']:
            self.send_error(404);return
        auth=self.headers.get('Authorization','')
        if not auth.startswith('Bearer '):self.send_error(401);return
        raw=self.rfile.read(int(self.headers.get('Content-Length','0')));request=json.loads(raw or b'{}');rid=uuid.uuid4().hex
        out=ROOT/'evidence/gateway'/rid;out.mkdir(parents=True,exist_ok=False);session=requests.Session();session.trust_env=False;started=time.monotonic()
        report={'request_id':rid,'utc_started':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'upstream':UPSTREAM+self.path,'request_model':request.get('model'),'request_body_sha256':hashlib.sha256(raw).hexdigest(),'stream':bool(request.get('stream')),'receipts':[],'transformations':[],'credentials_logged':False}
        # Only run identifiers, model and hashes are saved from requests.
        import re
        report['run_ids']=sorted(set(re.findall(r'(?:dev_\d+_\w+|test_\d+_(?:agh|mimo(?:_\w+)?)|real_[a-f0-9]{12}_mimo)',raw.decode(errors='replace'))))
        report['configuration']=json.loads((ROOT/'model.selection.json').read_text())
        images=[]
        for message in request.get('messages',[]):
            for part in message.get('content',[]) if isinstance(message.get('content'),list) else []:
                if part.get('type')=='image_url':
                    url=part.get('image_url',{}).get('url','')
                    if url.startswith('data:') and ';base64,' in url:
                        import base64
                        pixels=base64.b64decode(url.split(';base64,',1)[1]);images.append({'sha256':hashlib.sha256(pixels).hexdigest(),'bytes':len(pixels)})
        report['native_image_blocks']=images
        # Headers and authorization are never recorded. Guard against any
        # accidental credential echo before retaining the JSON request body.
        secret_values=[os.environ.get(n,'') for n in ('REPAIRFORGE_MODEL_API_KEY','DEEPSEEK_API_KEY','AGNES_SECRET_REPAIRFORGE_MIMO_KEY')]
        if not any(value and value.encode() in raw for value in secret_values):
            (out/'request.json').write_bytes(raw or b'{}')
        try:
            response=session.request(self.command,UPSTREAM+self.path,headers={'Authorization':auth,'Content-Type':'application/json'},data=raw or None,stream=True,timeout=(5,180))
            self.send_response(response.status_code);self.send_header('Content-Type',response.headers.get('Content-Type','application/json'));self.send_header('Connection','close');self.end_headers();self.close_connection=True
            body=bytearray();pending=b''
            for chunk in response.iter_content(4096):
                if not chunk:continue
                self.wfile.write(chunk);self.wfile.flush();body.extend(chunk);pending+=chunk
                if request.get('stream'):
                    while b'\n' in pending:
                        line,pending=pending.split(b'\n',1)
                        if line.startswith(b'data: ') and line[6:].strip()!=b'[DONE]':
                            try:
                                obj=json.loads(line[6:]);meta=receipt(obj,response.status_code)
                                if meta['receipt_model'] or meta['usage']:report['receipts'].append(meta)
                            except json.JSONDecodeError:pass
            report['http_status']=response.status_code;report['response_sha256']=hashlib.sha256(body).hexdigest()
            if not any(value and value.encode() in body for value in secret_values):(out/'response.raw').write_bytes(body)
            if not request.get('stream'):
                try:report['receipts'].append(receipt(json.loads(body),response.status_code))
                except json.JSONDecodeError:pass
            # Actual model receipt/usage fields only; raw text is unnecessary and could contain secrets.
            report['receipt_models']=sorted(set(x['receipt_model'] for x in report['receipts'] if x['receipt_model']))
            report['usage_receipts']=[x for x in report['receipts'] if x['usage']]
        except Exception as e:
            report['error_type']=type(e).__name__
            try:self.send_error(502,'Upstream transport unavailable')
            except Exception:pass
        finally:
            report['elapsed_seconds']=time.monotonic()-started;write(out/'receipt.json',report);session.close();auth=''
def main():ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('RF_RECEIPT_PORT','48778'))),Relay).serve_forever()
if __name__=='__main__':main()
