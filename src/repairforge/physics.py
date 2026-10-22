"""Real CadQuery solids and Gmsh/scikit-fem 3D linear elasticity, mm/N/MPa."""
import json,time
from pathlib import Path
import numpy as np
import trimesh
from .authority import write,digest

def make_cad(p,out):
    import cadquery as cq
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    L,W,H,t=(p[k] for k in ['length_mm','width_mm','height_mm','thickness_mm'])
    r,pitch=p['hole_radius_mm'],p['hole_pitch_mm'];bx=p['base_hole_x_mm'];wz=p['wall_hole_z_mm']
    if t>=min(L,H) or pitch+2*r+2>W or not t+r<bx<L-r-1 or not t+r<wz<H-r-1:raise ValueError('HOLE_OR_WALL_GEOMETRY_INVALID')
    base=cq.Workplane('XY').box(L,W,t,centered=(False,True,False))
    wall=cq.Workplane('XY').box(t,W,H,centered=(False,True,False))
    obj=base.union(wall)
    fillet=p.get('fillet_mm',0.)
    if fillet>0:
        edges=[e for e in obj.val().Edges() if abs(e.Center().x-t)<1e-5 and abs(e.Center().z-t)<1e-5 and e.Length()>W-.01]
        if not edges:raise ValueError('FILLET_EDGE_NOT_FOUND')
        obj=obj.newObject(edges).fillet(fillet)
    for y in [-pitch/2,pitch/2]:
        obj=obj.cut(cq.Workplane('XY').center(bx,y).circle(r).extrude(t+2).translate((0,0,-1)))
        cyl=cq.Solid.makeCylinder(r,t+2,cq.Vector(-1,y,wz),cq.Vector(1,0,0))
        obj=obj.cut(cyl)
    cq.exporters.export(obj,str(out/'part.step'))
    cq.exporters.export(obj,str(out/'part.stl'),tolerance=.06,angularTolerance=.08)
    mesh=trimesh.load(out/'part.stl',force='mesh');mesh.merge_vertices()
    result={'parameters':p,'parameters_sha256':digest(p),'step_sha256':digest(out/'part.step'),'stl_sha256':digest(out/'part.stl'),'solid_count':len(obj.solids().vals()),'cad_valid':obj.val().isValid(),'watertight':bool(mesh.is_watertight),'winding_consistent':bool(mesh.is_winding_consistent),'volume_mm3':float(obj.val().Volume()),'mesh_volume_mm3':float(mesh.volume),'bounds_mm':mesh.bounds.tolist(),'triangles':len(mesh.faces),'minimum_nominal_plate_thickness_mm':t,'feature_edge_ligament_mm':min((W-pitch)/2-r,L-bx-r,H-wz-r,bx-r-t,wz-r-t)}
    write(out/'cad_report.json',result);return result

def mesh_step(step,out,size):
    import gmsh,meshio
    gmsh.initialize();gmsh.option.setNumber('General.NumThreads',4);gmsh.option.setNumber('General.Terminal',0)
    try:
        gmsh.model.add('repairforge');gmsh.model.occ.importShapes(str(step));gmsh.model.occ.synchronize()
        gmsh.option.setNumber('Mesh.MeshSizeMin',size);gmsh.option.setNumber('Mesh.MeshSizeMax',size)
        gmsh.option.setNumber('Mesh.Algorithm3D',1);gmsh.model.mesh.generate(3)
        gmsh.write(str(out));m=meshio.read(out)
        return m.points.T,np.concatenate([x.data for x in m.cells if x.type=='tetra']).T
    finally:gmsh.finalize()

def mesh_stl(stl,out,size):
    """Gmsh discrete-surface tetrahedralization, no template CAD replacement."""
    import gmsh,meshio
    gmsh.initialize();gmsh.option.setNumber('General.NumThreads',4);gmsh.option.setNumber('General.Terminal',0)
    try:
        gmsh.model.add('raw_reconstruction');gmsh.merge(str(stl))
        gmsh.model.mesh.classifySurfaces(np.pi/4,True,True,np.pi)
        gmsh.model.mesh.createGeometry()
        surfaces=[tag for dim,tag in gmsh.model.getEntities(2)]
        gmsh.model.geo.addVolume([gmsh.model.geo.addSurfaceLoop(surfaces)]);gmsh.model.geo.synchronize()
        gmsh.option.setNumber('Mesh.MeshSizeMin',size);gmsh.option.setNumber('Mesh.MeshSizeMax',size);gmsh.model.mesh.generate(3);gmsh.write(str(out))
        m=meshio.read(out);return m.points.T,np.concatenate([x.data for x in m.cells if x.type=='tetra']).T
    finally:gmsh.finalize()

def solve_elastic(points,tets,E,nu,force,clamp_selector,load_selector,out):
    from skfem import MeshTet,ElementVector,ElementTetP2,Basis,FacetBasis,LinearForm,asm,condense,solve
    from skfem.models.elasticity import linear_elasticity,lame_parameters
    from skfem.helpers import sym_grad
    import meshio
    started=time.monotonic();m=MeshTet(points,tets);el=ElementVector(ElementTetP2());b=Basis(m,el,intorder=3)
    lam,mu=lame_parameters(E,nu);K=asm(linear_elasticity(lam,mu),b)
    fixed=m.facets_satisfying(clamp_selector);loaded=m.facets_satisfying(load_selector)
    if len(fixed)==0 or len(loaded)==0:raise ValueError('EMPTY_CONSTRAINT_OR_LOAD_REGION')
    fb=FacetBasis(m,el,facets=loaded,intorder=3);area=float(np.sum(fb.dx));traction=np.asarray(force)/area
    @LinearForm
    def load(v,w):return sum(traction[i]*v[i] for i in range(3))
    f=asm(load,fb);D=b.get_dofs(facets=fixed).all();u=solve(*condense(K,f,D=D));reaction=K@u-f
    r=np.array([np.sum(reaction[D[np.isin(D,b.split_indices()[i])]]) for i in range(3)])
    applied=np.array([f[ix].sum() for ix in b.split_indices()]);balance=float(np.linalg.norm(r+applied)/max(np.linalg.norm(applied),1e-12))
    strain=sym_grad(b.interpolate(u));trace=np.einsum('iieq->eq',strain)
    stress=2*mu*strain+lam*np.eye(3)[:,:,None,None]*trace
    dev=stress-np.eye(3)[:,:,None,None]*np.einsum('iieq->eq',stress)[None,None,:,:]/3
    vm=np.sqrt(1.5*np.einsum('ijeq,ijeq->eq',dev,dev));weights=b.dx
    elem_vm=np.sum(vm*weights,axis=1)/np.sum(weights,axis=1);volume=weights.sum(axis=1)
    order=np.argsort(elem_vm);c=np.cumsum(volume[order])/volume.sum();p95=float(elem_vm[order[np.searchsorted(c,.95)]])
    displ=u[b.nodal_dofs];maxdisp=float(np.linalg.norm(u.reshape((-1,3)),axis=1).max())
    meshio.write(str(Path(out).with_suffix('.vtu')),meshio.Mesh(points.T,[('tetra',tets.T)],point_data={'displacement_mm':displ.T},cell_data={'von_mises_mpa':[elem_vm]}))
    np.savez_compressed(Path(out).with_suffix('.npz'),points=points.T,tets=tets.T,displacement=displ.T,von_mises_mpa=elem_vm)
    result={'element':'quadratic_tetrahedron_P2','nodes':points.shape[1],'tetrahedra':tets.shape[1],'dofs':int(b.N),'young_mpa':E,'poisson':nu,'applied_force_n':applied.tolist(),'reaction_n':r.tolist(),'reaction_relative_error':balance,'loaded_area_mm2':area,'constrained_facets':len(fixed),'loaded_facets':len(loaded),'max_displacement_mm':maxdisp,'max_von_mises_mpa':float(vm.max()),'volume_weighted_p95_von_mises_mpa':p95,'mean_von_mises_mpa':float(np.sum(vm*weights)/weights.sum()),'strain_energy_n_mm':float(.5*u@(K@u)),'volume_mm3':float(volume.sum()),'solve_seconds':time.monotonic()-started,'linear_small_displacement':True,'claim':'计算模型结果；未经校准，不是FDM实物承载保证。尖角和理想夹持附近峰值需审查。'}
    write(Path(out).with_suffix('.json'),result);return result,displ,m

def verify_beam(out):
    import cadquery as cq
    out=Path(out);out.mkdir(parents=True,exist_ok=True);L,W,t,E,nu,F=60.,12.,8.,2200.,.35,8.
    cq.exporters.export(cq.Workplane('XY').box(L,W,t,centered=(False,True,False)),str(out/'beam.step'))
    reports=[]
    for size in [4.,3.]:
        pts,tets=mesh_step(out/'beam.step',out/f'beam-{size}.msh',size)
        r,disp,m=solve_elastic(pts,tets,E,nu,[0,0,-F],lambda x:np.isclose(x[0],0),lambda x:np.isclose(x[0],L),out/f'beam-{size}')
        r['tip_mean_displacement_mm']=float(-np.mean(disp[2,np.isclose(m.p[0],L)]));reports.append(r)
    # Euler-Bernoulli + Timoshenko shear contribution for the rectangular cantilever.
    bending=F*L**3/(3*E*(W*t**3/12));shear=F*L/((5/6)*(E/(2*(1+nu)))*W*t)
    exact=bending+shear;computed=reports[-1]['tip_mean_displacement_mm']
    result={'benchmark':'uniform-end-traction cantilever, analytical beam + shear comparison','analytical_displacement_mm':exact,'refined_displacement_mm':computed,'relative_deflection_error':abs(computed-exact)/exact,'reaction_relative_error':reports[-1]['reaction_relative_error'],'mesh_reports':reports}
    write(out/'beam_verification.json',result);return result
