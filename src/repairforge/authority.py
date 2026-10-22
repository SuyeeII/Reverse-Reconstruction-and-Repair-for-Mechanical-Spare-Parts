"""Versioned, frozen-contract candidate store. No model decides acceptance."""
import fcntl,hashlib,json,math,re,time
from pathlib import Path
from contextlib import contextmanager

def digest(data):
    if isinstance(data,Path): data=data.read_bytes()
    if not isinstance(data,bytes): data=json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()

def read(p): return json.loads(Path(p).read_text())
def write(p,data):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    q=p.with_suffix(p.suffix+'.new');q.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n');q.replace(p)

class Rejected(ValueError): pass
class Store:
    def __init__(self,root): self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
    def path(self,r):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',r): raise Rejected('INVALID_RUN_ID')
        return self.root/r
    @contextmanager
    def lock(self,r):
        with (self.path(r)/'.lock').open('a') as f:
            fcntl.flock(f,fcntl.LOCK_EX);yield;fcntl.flock(f,fcntl.LOCK_UN)
    def event(self,r,kind,**fields):
        p=self.path(r)/'events.jsonl';rows=p.read_text().splitlines() if p.exists() else []
        prev=digest(rows[-1].encode()) if rows else '0'*64
        e={'run_id':r,'kind':kind,'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'previous_event_sha256':prev,**fields}
        with p.open('a') as f:f.write(json.dumps(e,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n');f.flush()
    def create(self,r,contract,**fields):
        p=self.path(r);p.mkdir(exist_ok=False)
        write(p/'contract.json',contract)
        s={'run_id':r,'state_version':0,'contract_sha256':digest(contract),'decisions':[],'candidate_ids':[],**fields}
        write(p/'state.json',s);self.event(r,'created',contract_sha256=s['contract_sha256']);return s
    def state(self,r):return read(self.path(r)/'state.json')
    def candidates(self,r):return [read(self.path(r)/c/'candidate.json') for c in self.state(r)['candidate_ids']]
    def check(self,r,d,v):
        s=self.state(r)
        if digest(read(self.path(r)/'contract.json'))!=s['contract_sha256']:raise Rejected('CONTRACT_TAMPERED')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',d):raise Rejected('INVALID_DECISION_ID')
        if d in s['decisions']:raise Rejected('DUPLICATE_DECISION')
        if type(v)!=int or v!=s['state_version']:raise Rejected('STALE_STATE_VERSION')
        return s,read(self.path(r)/'contract.json')
    def propose(self,r,d,v,params,parent=None,model=None):
        with self.lock(r):
            s,c=self.check(r,d,v)
            if len(s['candidate_ids'])>=c['candidate_budget']:raise Rejected('CANDIDATE_BUDGET')
            if parent is not None and parent not in s['candidate_ids']:raise Rejected('INVALID_PARENT')
            bounds=c['parameter_bounds']
            allowed=set(bounds)|{'base_hole_x_mm','wall_hole_z_mm','fillet_mm'}
            if set(params)-allowed:raise Rejected('UNKNOWN_PARAMETER')
            for k,x in params.items():
                if not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x):raise Rejected('INVALID_NUMBER')
                if k in bounds and not bounds[k][0]<=x<=bounds[k][1]:raise Rejected('PARAMETER_BOUNDS '+k)
            cid=f"c{len(s['candidate_ids'])+1:03d}";p=self.path(r)/cid;p.mkdir()
            n={'run_id':r,'decision_id':d,'candidate_id':cid,'parent_candidate_id':parent,'state_version':v+1,'parameters':params,'parameters_sha256':digest(params),'contract_sha256':s['contract_sha256'],'model':model,'status':'PROPOSED'}
            write(p/'candidate.json',n);s['state_version']+=1;s['decisions'].append(d);s['candidate_ids'].append(cid);write(self.path(r)/'state.json',s)
            self.event(r,'candidate_proposed',**{k:n[k] for k in ['decision_id','candidate_id','state_version','parameters_sha256','contract_sha256','model']});return n
