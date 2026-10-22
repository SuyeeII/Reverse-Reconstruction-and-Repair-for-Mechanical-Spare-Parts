"""Real PrusaSlicer CLI, nonempty extrusion/layer audit and offline motion replay."""
from pathlib import Path
import subprocess,re,shutil,time,math
import numpy as np,trimesh
from .authority import write,digest
ROOT=Path(__file__).resolve().parents[2]

def parse_gcode(path,out):
    xyz=np.zeros(3);e=0.;relative=False;relative_xyz=False;kind='';layer=0;layers=set();segments=[];extrusions=0;support_e=0.;total_e=0.;minxyz=np.full(3,np.inf);maxxyz=np.full(3,-np.inf)
    text=Path(path).read_text(errors='replace')
    for line in text.splitlines():
        if line.startswith(';TYPE:'):kind=line.split(':',1)[1].strip()
        if line.startswith(';LAYER_CHANGE'):layer+=1
        code=line.split(';',1)[0].strip();command=code.split(' ',1)[0]
        if command=='M82':relative=False
        elif command=='M83':relative=True
        elif command=='G90':relative_xyz=False
        elif command=='G91':relative_xyz=True
        vals={k:float(v) for k,v in re.findall(r'([XYZE])(-?\d+(?:\.\d+)?)',code)}
        if command=='G92':
            if 'E' in vals:e=vals['E']
            for i,k in enumerate('XYZ'):
                if k in vals:xyz[i]=vals[k]
        if command not in ['G0','G1']:continue
        before=xyz.copy();new=xyz.copy()
        for i,k in enumerate('XYZ'):
            if k in vals:new[i]=vals[k]+(xyz[i] if relative_xyz else 0)
        de=(vals.get('E',0) if relative else vals.get('E',e)-e)
        if 'E' in vals:e=e+vals['E'] if relative else vals['E']
        if de>0 and np.linalg.norm(new-before)>1e-5:
            if not np.isfinite(new).all():raise ValueError('NONFINITE_PATH')
            layers.add(round(float(new[2]),4));extrusions+=1;total_e+=de
            is_support='support' in kind.lower()
            if is_support:support_e+=de
            minxyz=np.minimum(minxyz,new);maxxyz=np.maximum(maxxyz,new)
            segments.append([*np.round(before,3).tolist(),*np.round(new,3).tolist(),int(is_support),layer])
        xyz=new
    fil=re.search(r'; filament used \[g\] = ([\d.]+)',text)
    duration=re.search(r'; estimated printing time \(normal mode\) = (.+)',text)
    volumefactor=math.pi*(1.75/2)**2
    report={'layers':layer or len(layers),'layer_count_source':'PrusaSlicer LAYER_CHANGE comments' if layer else 'extrusion heights fallback','extrusion_height_count':len(layers),'extrusion_segments':extrusions,'filament_extruded_mm':total_e,'support_filament_mm':support_e,'support_volume_mm3':support_e*volumefactor,'filament_estimated_g':float(fil.group(1)) if fil else total_e*volumefactor*1.24/1000,'printing_time_estimate':duration.group(1).strip() if duration else None,'extrusion_bounds_mm':None if not segments else [minxyz.tolist(),maxxyz.tolist()],'motion_only':'G-code运动回放；不模拟熔融沉积、热应力或实物打印'}
    write(Path(out)/'toolpaths.json',{'segments':segments,'layers':sorted(layers),'report':report});return report

def slice_part(stl,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);stl=Path(stl).resolve();binary=ROOT/'runtime/system/usr/bin/prusa-slicer';config=ROOT/'configs/print.ini';shutil.copyfile(config,out/'print.ini')
    gcode=out/'part.gcode';command=[str(binary),'--load',str(config),'--threads','4','--export-gcode','--center','110,110','--output',str(gcode.resolve()),str(stl)]
    start=time.monotonic();proc=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=300);(out/'slicer.log').write_text(proc.stdout)
    mesh=trimesh.load(stl,force='mesh');r={'engine':'PrusaSlicer Debian/Ubuntu 2.7.2+dfsg-1build2','command':command,'exit_code':proc.returncode,'elapsed_seconds':time.monotonic()-start,'source_stl_sha256':digest(stl),'configuration_sha256':digest(config),'input_watertight':bool(mesh.is_watertight),'input_winding_consistent':bool(mesh.is_winding_consistent),'gcode_bytes':gcode.stat().st_size if gcode.exists() else 0,'slicer_automatic_mesh_repair':'PrusaSlicer built-in implicit repair may run; does not retroactively certify raw input'}
    if r['exit_code']==0 and r['gcode_bytes']:
        r.update(parse_gcode(gcode,out));r['gcode_sha256']=digest(gcode)
        r['paths_inside_build_volume']=all(0<=x<=220.01 for x in r['extrusion_bounds_mm'][0][:2]+r['extrusion_bounds_mm'][1][:2]) and r['extrusion_bounds_mm'][1][2]<=220
        r['accepted_slicing']=r['extrusion_segments']>100 and r['layers']>1 and r['paths_inside_build_volume']
    else:r['accepted_slicing']=False
    write(out/'slicing.json',r);return r
