"""Guarded native domain operations; images remain immutable attachments."""
from pathlib import Path
import sys,subprocess,time,shutil,math,json
from .authority import Store,Rejected,read,write,digest

class Service:
    def __init__(self,root,run_root=None):self.root=Path(root).resolve();self.store=Store(run_root or self.root/'runs')
    def create(self,run_id,case_id,method='AGH_mimo_v2.6_pro'):
        if not __import__('re').fullmatch('[A-Za-z0-9_-]+',case_id):raise Rejected('INVALID_CASE_ID')
        inp=self.root/'inputs'/case_id
        if not inp.is_dir():raise Rejected('INPUT_NOT_FOUND')
        hashes={str(p.relative_to(inp)):digest(p) for p in inp.rglob('*') if p.is_file()}
        return self.store.create(run_id,read(self.root/'configs/acceptance.json'),case_id=case_id,method=method,input_sha256=digest(hashes),input_hashes=hashes)
    def summary(self):
        runs=[]
        for p in sorted(self.store.root.glob('*/state.json')):
            s=read(p);c=self.store.candidates(s['run_id']);runs.append({'run_id':s['run_id'],'state_version':s['state_version'],'case_id':s.get('case_id'),'method':s.get('method'),'candidates':[{'candidate_id':q['candidate_id'],'status':q['status'],'parameters':q['parameters'],'evaluation':q.get('summary'),'manufacturing':q.get('manufacturing')} for q in c]})
        return {'runs':runs,'model':read(self.root/'model.selection.json') if (self.root/'model.selection.json').exists() else None,'scope':'仿真图像／参考板辅助COLMAP与轮廓拟合；真实CAD、FEM和CLI切片','jev':'not_run_no_credential','dashboard':'http://127.0.0.1:48905'}
    def _brief(self,r):
        state=self.store.state(r);feature_file=self.store.path(r)/'features/features.json';features=read(feature_file) if feature_file.exists() else None;observations={k:features[k] for k in ['status','parameters','critical_missing','uncertainty_mm','base_plane_source']} if features else None;feedback_file=self.store.path(r)/'reconstruction/reconstruction.json';failure_file=self.store.path(r)/'reconstruction/failure.json';feedback=read(feedback_file) if feedback_file.exists() else read(failure_file) if failure_file.exists() else None;return {'reconstruction_feedback':feedback,'input_access':'Images and scale are already bound by case_id; domain tools read them. If reconstruction failed, report the algorithm limitation or request additional views for a new immutable run; do not invent geometry.','run_id':r,'state_version':state['state_version'],'case_id':state.get('case_id'),'observations':observations,'candidates':self.store.candidates(r),'contract':read(self.store.path(r)/'contract.json')}
    def dispatch(self,tool,a):
        if tool=='summary':return self.summary()
        r=a['run_id'];path=self.store.path(r);state=self.store.state(r)
        if tool=='list_candidates':return self._brief(r)
        if tool=='view_photos':
            names=a.get('frame_ids',[])
            if not isinstance(names,list) or len(names)!=1:raise Rejected('IMAGE_BATCH_LIMIT: retrieve one original image per call; frozen AGH retains three recent image results')
            if any(not isinstance(n,str) or not __import__('re').fullmatch(r'[A-Za-z0-9_-]{1,80}\.(png|jpg|jpeg)',n) for n in names):raise Rejected('IMAGE_ID')
            inp=self.root/'inputs'/state['case_id']
            hashes={str(p.relative_to(inp)):digest(p) for p in inp.rglob('*') if p.is_file()}
            if digest(hashes)!=state['input_sha256']:raise Rejected('INPUT_CHANGED')
            images=[]
            for name in names:
                f=inp/'images'/name
                if f.is_symlink() or f.resolve().parent!=(inp/'images').resolve() or not f.is_file():raise Rejected('IMAGE_ID')
                images.append({'frame_id':name,'path':str(f.relative_to(self.root)),'sha256':digest(f),'mime':'image/png' if name.endswith('.png') else 'image/jpeg'})
            self.store.event(r,'photos_viewed',state_version=state['state_version'],images=images)
            return {'run_id':r,'state_version':state['state_version'],'images':images,'available_frame_ids':sorted(p.name for p in (inp/'images').iterdir() if p.is_file()),'source':read(inp/'source.json'),'scale':read(inp/'scale.json'),'dimensional_estimates_from_model_accepted':False,'limitation':'Visual observations guide tool use only. Independent geometry, FEM and slicing decide acceptance.'}
        d,v=a['decision_id'],a['state_version']
        self.store.check(r,d,v)
        if tool in ['inspect_features','propose_cad'] and not (path/'reconstruction/reconstruction.json').exists() and (path/'reconstruction/failure.json').exists():raise Rejected('RECONSTRUCTION_FAILED_CANNOT_FIT_OR_INVENT_GEOMETRY')
        inp=self.root/'inputs'/state.get('case_id','')
        hashes={str(p.relative_to(inp)):digest(p) for p in inp.rglob('*') if p.is_file()} if state.get('case_id') else {}
        if state.get('input_sha256') and digest(hashes)!=state['input_sha256']:raise Rejected('INPUT_CHANGED')
        if tool in ['propose_cad','revise_cad']:
            feature=read(path/'features/features.json')
            if feature['critical_missing']:raise Rejected('CRITICAL_FEATURES_UNOBSERVED_NEED_MORE_VIEWS')
            p=dict(feature['parameters']);parent=None
            if tool=='revise_cad':
                parent=a['parent_candidate_id'];old=read(path/parent/'candidate.json');p=dict(old['parameters']);changes=a['changes']
                if set(changes)-{'thickness_mm','fillet_mm'}:raise Rejected('INTERFACE_EDITS_FORBIDDEN')
                if not 0<=changes.get('fillet_mm',p.get('fillet_mm',0))<=6:raise Rejected('FILLET_BOUNDS')
                p.update(changes)
            selection=read(self.root/'model.selection.json') if state.get('method','').startswith('AGH') else None
            c=self.store.propose(r,d,v,p,parent,selection)
            from .physics import make_cad
            cad=make_cad(p,path/c['candidate_id']);c['cad_hashes']={'step':cad['step_sha256'],'stl':cad['stl_sha256']};write(path/c['candidate_id']/'candidate.json',c)
            return {'candidate':c,**self._brief(r)}
        # Serialize mutations including expensive solves, preserving rejection-before-side-effect.
        with self.store.lock(r):
            s,contract=self.store.check(r,d,v);result={};cid=a.get('candidate_id');candidate=None
            if cid:
                if cid not in s['candidate_ids']:raise Rejected('UNKNOWN_CANDIDATE')
                candidate=read(path/cid/'candidate.json')
                if digest(candidate['parameters'])!=candidate['parameters_sha256']:raise Rejected('PARAMETERS_CHANGED')
                if tool=='export_manufacturing' and candidate['status']!='PHYSICS_ACCEPTED':raise Rejected('CANDIDATE_NOT_ACCEPTED')
                for key,file in [('step','part.step'),('stl','part.stl')]:
                    if key in candidate.get('cad_hashes',{}) and digest(path/cid/file)!=candidate['cad_hashes'][key]:raise Rejected('CAD_FILE_CHANGED')
            self.store.event(r,'tool_started',tool=tool,decision_id=d,candidate_id=cid,state_version=v)
            if tool=='reconstruct_views':
                target=path/'reconstruction'
                if (target/'reconstruction.json').exists():raise Rejected('RECONSTRUCTION_ALREADY_DONE')
                target.mkdir(exist_ok=True)
                with (target/'process.log').open('w') as log:
                    p=subprocess.run([sys.executable,str(self.root/'scripts/reconstruct_isolated.py'),str(inp),str(target)],stdout=log,stderr=subprocess.STDOUT,timeout=300)
                if p.returncode:result=read(target/'failure.json');result['process_exit_code']=p.returncode
                else:
                    full=read(target/'reconstruction.json');result={k:full[k] for k in ['status','backend','input_views','registered_views','foreground_points','elapsed_seconds','truth_access']};result['calibration_rmse_px']=full.get('camera_calibration_rmse_px')
            elif tool=='inspect_features':
                from .features import inspect_features
                full=inspect_features(inp,path/'reconstruction',path/'features');result={k:full[k] for k in ['status','parameters','uncertainty_mm','critical_missing','source','prior','base_plane_source']}
            elif tool=='evaluate_design':
                if candidate['status']!='PROPOSED':raise Rejected('CANDIDATE_ALREADY_EVALUATED')
                from .evaluate import evaluate_design
                full=evaluate_design(candidate['parameters'],path/cid,contract)
                result={'accepted_physics':full['accepted_physics'],'violations':full['violations'],'mass_g':full['mass_g'],'max_displacement_mm':full['mesh_reports'][-1]['max_displacement_mm'],'max_von_mises_mpa':full['mesh_reports'][-1]['max_von_mises_mpa'],'reaction_relative_error':full['mesh_reports'][-1]['reaction_relative_error'],'mesh_displacement_relative_change':full['mesh_displacement_relative_change'],'report':str((path/cid/'evaluation.json').relative_to(self.root)),'limitations':full['limitations']}
                candidate['status']='PHYSICS_ACCEPTED' if full['accepted_physics'] else 'PHYSICS_REJECTED';candidate['summary']=result;candidate['cad_hashes']={'step':full['cad']['step_sha256'],'stl':full['cad']['stl_sha256']};write(path/cid/'candidate.json',candidate)
            elif tool=='export_manufacturing':
                from .manufacture import slice_part
                full=slice_part(path/cid/'part.stl',path/cid/'manufacturing');result={k:full[k] for k in ['accepted_slicing','exit_code','layers','extrusion_segments','gcode_bytes','filament_estimated_g','support_volume_mm3','printing_time_estimate','motion_only'] if k in full}
                candidate['status']='ACCEPTED_COMPUTATIONAL_DELIVERY' if full['accepted_slicing'] else 'SLICING_REJECTED';candidate['manufacturing']=result;write(path/cid/'candidate.json',candidate)
            else:raise Rejected('UNKNOWN_TOOL')
            s['state_version']+=1;s['decisions'].append(d);write(path/'state.json',s)
            self.store.event(r,'tool_finished',tool=tool,decision_id=d,candidate_id=cid,state_version=s['state_version'],result=result)
            return {'result':result,**self._brief(r)}
