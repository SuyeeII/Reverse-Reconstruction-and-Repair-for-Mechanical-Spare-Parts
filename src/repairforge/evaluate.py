"""Frozen, independent computational design acceptance; no model self-rating."""
from pathlib import Path
import numpy as np
from .authority import write,digest,read,Rejected
from .physics import make_cad,mesh_step,solve_elastic

def evaluate_design(p,out,contract):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);cad=read(out/'cad_report.json') if (out/'cad_report.json').exists() else make_cad(p,out);reports=[]
    if cad['parameters_sha256']!=digest(p) or cad['step_sha256']!=digest(out/'part.step') or cad['stl_sha256']!=digest(out/'part.stl'):raise Rejected('CAD_REPORT_BINDING_MISMATCH')
    mat=contract['material'];lim=contract['limits'];force=np.array(contract['loading']['direction'])*contract['loading']['force_n']
    for size in contract['mesh_sizes_mm']:
        pts,tets=mesh_step(out/'part.step',out/f'mesh_{size:g}.msh',size)
        r,_,_=solve_elastic(pts,tets,mat['young_mpa'],mat['poisson'],force,lambda x:np.isclose(x[0],0,atol=1e-5),lambda x:np.isclose(x[0],p['length_mm'],atol=1e-5),out/f'fem_{size:g}')
        r['mesh_size_mm']=size;reports.append(r)
    fine=reports[-1];coarse=reports[-2];delta=abs(fine['max_displacement_mm']-coarse['max_displacement_mm'])/max(fine['max_displacement_mm'],1e-12)
    stress_delta=abs(fine['max_von_mises_mpa']-coarse['max_von_mises_mpa'])/max(fine['max_von_mises_mpa'],1e-12)
    mass=cad['volume_mm3']*mat['density_g_cm3']/1000
    tests={'solid_watertight':cad['watertight'] and cad['cad_valid'] and cad['solid_count']==1,'nominal_wall':p['thickness_mm']>=lim['min_wall_mm'],'hole_edge_ligament':cad['feature_edge_ligament_mm']>=lim['min_wall_mm'],'mass':mass<=lim['mass_g'],'displacement':fine['max_displacement_mm']<=lim['displacement_mm'],'stress_peak':fine['max_von_mises_mpa']<=mat['allowable_von_mises_mpa'],'force_balance':all(r['reaction_relative_error']<=lim['reaction_relative_error'] for r in reports),'mesh_displacement_stability':delta<=lim['mesh_displacement_relative_change']}
    r={'accepted_physics':all(tests.values()),'tests':tests,'violations':[k for k,v in tests.items() if not v],'mass_g':mass,'cad':cad,'mesh_reports':reports,'mesh_displacement_relative_change':delta,'mesh_peak_stress_relative_change':stress_delta,'contract_sha256':digest(contract),'parameters_sha256':digest(p),'stress_acceptance':'maximum quadrature von Mises at finest mesh, no trimming of failure peaks','uncertainty':'two meshes test displacement stability; local singular stress need not converge; all peaks retained','limitations':mat['calibration']}
    write(out/'evaluation.json',r);return r
