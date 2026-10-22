"""Export actual CAD/FEM/path artifacts for independent offline evidence viewing."""
from pathlib import Path
import numpy as np,trimesh,json
from .authority import read,write

def boundary_faces(tets):
    candidates=np.concatenate([tets[:,i] for i in [[0,1,2],[0,1,3],[0,2,3],[1,2,3]]]);cells=np.tile(np.arange(len(tets)),4)
    _,index,counts=np.unique(np.sort(candidates,axis=1),axis=0,return_index=True,return_counts=True)
    kept=index[counts==1];return candidates[kept],cells[kept]

def export_run(root,run_id):
    root=Path(root);path=root/'runs'/run_id;out=root/'web/data'/run_id;out.mkdir(parents=True,exist_ok=True);state=read(path/'state.json')
    r={'run_id':run_id,'case_id':state['case_id'],'method':state['method'],'state_version':state['state_version'],'candidates':[],'events':[],'images':[]}
    if (path/'events.jsonl').exists():r['events']=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
    r['images']=['/assets/inputs/'+state['case_id']+'/images/'+f.name for f in sorted((root/'inputs'/state['case_id']/'images').glob('*.png'))]
    if (path/'reconstruction/reconstruction.json').exists():r['reconstruction']=read(path/'reconstruction/reconstruction.json')
    if (path/'features/features.json').exists():r['features']=read(path/'features/features.json')
    source=path/'features/local_observed.npz'
    if source.exists():r['pointcloud']=np.load(source)['points'].round(4).tolist()
    for cid in state['candidate_ids']:
        c=read(path/cid/'candidate.json');mesh=trimesh.load(path/cid/'part.stl',force='mesh');c['cad']={'vertices':mesh.vertices.round(4).tolist(),'faces':mesh.faces.tolist()}
        fp=path/cid/'fem_2.npz'
        if fp.exists():
            a=np.load(fp);faces,ix=boundary_faces(a['tets']);c['fem']={'vertices':a['points'].round(4).tolist(),'faces':faces.tolist(),'stress_mpa':a['von_mises_mpa'][ix].round(5).tolist(),'displacement_mm':np.linalg.norm(a['displacement'],axis=1).round(6).tolist(),'display_note':'表面颜色为相邻二次四面体的积分平均应力；验收使用原始积分点最大值，无裁剪。'}
        if (path/cid/'manufacturing/toolpaths.json').exists():c['paths']=read(path/cid/'manufacturing/toolpaths.json')
        c['downloads']={'STEP':'/assets/runs/'+run_id+'/'+cid+'/part.step','STL':'/assets/runs/'+run_id+'/'+cid+'/part.stl','G-code':'/assets/runs/'+run_id+'/'+cid+'/manufacturing/part.gcode'}
        r['candidates'].append(c)
    write(out/'scene.json',r);return r

def export_all(root):
    root=Path(root);items=[]
    for f in sorted((root/'runs').glob('*/state.json')):
        s=read(f)
        if s['candidate_ids'] or (f.parent/'features/features.json').exists():
            r=export_run(root,s['run_id']);items.append({'run_id':s['run_id'],'case_id':s['case_id'],'method':s['method'],'status':r['candidates'][-1]['status'] if r['candidates'] else 'NEED_MORE_VIEWS','file':'data/'+s['run_id']+'/scene.json'})
    write(root/'web/data/index.json',items);return items
