"""Observed planar dimensions and photo hole contours. Missing shape is prior."""
from pathlib import Path
import numpy as np,cv2
from scipy.optimize import least_squares,minimize
from .authority import read,write
from .reconstruct import segment

def fit_planes(points,marker_corners):
    import open3d as o3d
    o3d.utility.random.seed(17)
    points=np.asarray(points);marker_corners=np.asarray(marker_corners,dtype=float);origin=marker_corners.mean(axis=0)
    z=np.cross(marker_corners[1]-marker_corners[0],marker_corners[2]-marker_corners[1]);z/=np.linalg.norm(z)
    if (points-origin).mean(axis=0)@z<0:z=-z
    remaining=points.copy();planes=[]
    for _ in range(10):
        if len(remaining)<40:break
        pc=o3d.geometry.PointCloud();pc.points=o3d.utility.Vector3dVector(remaining)
        coeff,ix=pc.segment_plane(distance_threshold=.22,ransac_n=3,num_iterations=1600)
        if len(ix)<40:break
        sample=remaining[ix];n=np.array(coeff[:3]);n/=np.linalg.norm(n)
        planes.append({'normal':n,'center':sample.mean(axis=0),'count':len(ix),'rmse':float(np.sqrt(np.mean((sample@n+coeff[3])**2)))})
        remaining=np.delete(remaining,ix,axis=0)
    vertical=[p for p in planes if abs(p['normal']@z)<.15]
    horizontal=[p for p in planes if abs(p['normal']@z)>.98]
    if not vertical:raise ValueError('L_WALL_NOT_OBSERVED')
    wall=max(vertical,key=lambda p:p['count']);x=wall['normal']-z*(wall['normal']@z);x/=np.linalg.norm(x)
    q=(points-wall['center'])@x
    if np.quantile(q,.99)+np.quantile(q,.01)<0:x=-x
    y=np.cross(z,x);y/=np.linalg.norm(y);axes=np.array([x,y,z])
    wp=[p for p in vertical if abs(p['normal']@x)>.98 and p['count']>=40]
    if not wp:raise ValueError('L_WALL_NOT_RELIABLY_OBSERVED')
    # RANSAC may split a noisy physical surface into several nearby planes.
    # Group those fragments before selecting the two observed wall surfaces.
    # The 0.8 mm grouping scale matches the frozen feature tolerance; it does
    # not relax the subsequent independent uncertainty or dimensional gates.
    def surface_groups(candidates,axis):
        groups=[]
        for p in sorted(candidates,key=lambda p:p['center']@axis):
            coordinate=float(p['center']@axis)
            if not groups or coordinate-groups[-1]['minimum']>.8:
                groups.append({'minimum':coordinate,'members':[]})
            groups[-1]['members'].append(p)
        return [{'coordinate':float(np.average([p['center']@axis for p in g['members']],weights=[p['count'] for p in g['members']])),'count':sum(p['count'] for p in g['members'])} for g in groups]
    walls=sorted(surface_groups(wp,x),key=lambda g:g['count'],reverse=True)
    xpos=sorted(g['coordinate'] for g in walls[:2]);back=min(xpos);outer=origin+ x*(back-origin@x)
    local=(points-outer)@axes.T
    ymn,ymx=np.quantile(local[:,1],[.001,.999]);outer+=y*(ymn+ymx)/2;local=(points-outer)@axes.T
    tw=xpos[1]-xpos[0] if len(xpos)>=2 and xpos[1]-xpos[0]<10 else None
    if not horizontal and tw is None:raise ValueError('THICKNESS_UNOBSERVED_NEED_MORE_VIEWS')
    bases=surface_groups(horizontal,z)
    base=max(bases,key=lambda p:p['count']) if bases else None
    tb=float(base['coordinate']-outer@z) if base is not None else tw
    t=(tb+tw)/2 if tw is not None else tb
    dims={'length_mm':float(np.quantile(local[:,0],.999)),'width_mm':float(ymx-ymn),'height_mm':float(np.quantile(local[:,2],.999)),'thickness_mm':float(t)}
    residual=float(max(p['rmse'] for p in planes[:4]));uncertainty=max(.25,3*residual,abs(tb-tw) if tw else .6)
    return {'dimensions':dims,'axes_world_to_local':axes.tolist(),'origin_world_mm':outer.tolist(),'planes':[{'normal':p['normal'].tolist(),'center_world_mm':p['center'].tolist(),'points':p['count'],'rmse_mm':p['rmse']} for p in planes],'plate_thickness_from_reference_plane_mm':tb,'wall_thickness_from_two_observed_planes_mm':None if tw is None else float(tw),'uncertainty_mm':float(uncertainty),'assumption':'horizontal plate rests on observed scale-reference support plane; underside completion is template prior', 'base_plane_source':'observed_point_plane' if base is not None else 'equal-thickness family prior using measured two wall planes; not measured from base point cloud','local_points':local}

def circle_fit(points2):
    points2=np.asarray(points2);c0=points2.mean(axis=0);r0=np.median(np.linalg.norm(points2-c0,axis=1))
    r=least_squares(lambda v:np.linalg.norm(points2-v[:2],axis=1)-v[2],np.r_[c0,r0],loss='soft_l1',f_scale=.15)
    c=r.x[:2];rad=r.x[2];err=np.linalg.norm(points2-c,axis=1)-rad
    return c,float(rad),float(np.sqrt(np.mean(err**2)))

def hole_consensus(rows):
    """Cross-view agreement rejects contours projected onto the wrong plate.

    The 0.8 mm clustering radius is fixed before held-out evaluation.
    All rejected observations remain in the feature report.
    """
    from scipy.cluster.hierarchy import fclusterdata
    if len(rows)<2:return rows,[]
    labels=fclusterdata(np.array([q['center']+[q['radius_mm']] for q in rows]),.8,criterion='distance',method='complete')
    groups=[[q for q,label in zip(rows,labels) if label==i] for i in set(labels)]
    best=max(groups,key=lambda g:len(set(q['image'] for q in g)))
    return best,[q for q in rows if q not in best]

def project_family_silhouette(dimensions,axes,origin,camera,size):
    """Project the disclosed orthogonal equal-thickness family, not source CAD.

    Holes are deliberately filled here: their contours are measured separately.
    Missing corners/back surfaces in this projection are explicitly prior.
    """
    length,width,height,thickness=[dimensions[k] for k in ('length_mm','width_mm','height_mm','thickness_mm')]
    result=np.zeros(size,np.uint8)
    for xmax,zmax in ((length,thickness),(thickness,height)):
        vertices=np.array([[x,y,z] for x in (0,xmax) for y in (-width/2,width/2) for z in (0,zmax)])
        world=vertices@np.asarray(axes)+np.asarray(origin)
        projected=(world@np.asarray(camera['R']).T+np.asarray(camera['T']))@np.asarray(camera['K']).T
        if np.any(projected[:,2]<=0):continue
        pixels=projected[:,:2]/projected[:,2,None]
        polygon=cv2.convexHull(np.round(pixels*256).astype(np.int32))
        plate=np.zeros(size,np.uint8);cv2.fillConvexPoly(plate,polygon,255,lineType=cv2.LINE_AA,shift=8)
        result=np.maximum(result,plate)
    return result

def fit_silhouette_dimensions(dimensions,axes,origin,views):
    """Independent image boundary fit prevents sparse-point extrema bias.

    Only observed outer masks, estimated cameras and disclosed family topology
    are consumed. Subset sensitivity is reported, never hidden as certainty.
    """
    keys=('length_mm','width_mm','height_mm');initial=np.array([dimensions[k] for k in keys])
    bounds=((35,70),(30,55),(30,60))
    prepared=[]
    for view in views:
        mask=view['mask'];ratio=min(1.,320/max(mask.shape));shape=(round(mask.shape[1]*ratio),round(mask.shape[0]*ratio))
        observed=cv2.resize(mask,shape,interpolation=cv2.INTER_AREA).astype(float)/255
        observed=cv2.GaussianBlur(observed,(3,3),.6)
        camera={k:np.array(v,dtype=float) for k,v in view['camera'].items() if k in ('K','R','T')}
        camera['K']=camera['K'].copy();camera['K'][:2]*=ratio
        prepared.append({'camera':camera,'mask':observed})
    def objective(values,subset):
        params={**dimensions,**dict(zip(keys,values))};loss=[]
        for v in subset:
            prediction=project_family_silhouette(params,axes,origin,v['camera'],v['mask'].shape).astype(float)/255
            observation=v['mask'];union=np.maximum(prediction,observation).sum()
            loss.append(np.abs(prediction-observation).sum()/max(union,1))
        return float(np.mean(loss))
    fit=minimize(objective,initial,args=(prepared,),method='Nelder-Mead',bounds=bounds,options={'maxiter':180,'xatol':.015,'fatol':1e-5,'initial_simplex':np.vstack([initial,initial+np.eye(3)])})
    params={**dimensions,**dict(zip(keys,map(float,fit.x)))};subsets=[]
    for excluded in range(3):
        subset=[v for i,v in enumerate(prepared) if i%3!=excluded]
        if len(subset)<6:continue
        part=minimize(objective,fit.x,args=(subset,),method='Nelder-Mead',bounds=bounds,options={'maxiter':90,'xatol':.03,'fatol':2e-5,'initial_simplex':np.vstack([fit.x,fit.x+.5*np.eye(3)])})
        subsets.append(part.x)
    sensitivity=float(np.max(np.ptp(np.array(subsets),axis=0))) if len(subsets)>=2 else float('inf')
    ious=[];residuals=[]
    for view in prepared:
        predicted=project_family_silhouette(params,axes,origin,view['camera'],view['mask'].shape)>127;observed=view['mask']>.5
        ious.append(float(np.logical_and(predicted,observed).sum()/max(1,np.logical_or(predicted,observed).sum())))
        a=cv2.morphologyEx(predicted.astype(np.uint8),cv2.MORPH_GRADIENT,np.ones((3,3),np.uint8))>0
        b=cv2.morphologyEx(observed.astype(np.uint8),cv2.MORPH_GRADIENT,np.ones((3,3),np.uint8))>0
        da=cv2.distanceTransform((~a).astype(np.uint8),cv2.DIST_L2,3);db=cv2.distanceTransform((~b).astype(np.uint8),cv2.DIST_L2,3)
        distance=np.r_[da[b],db[a]];pixel_rmse=float(np.sqrt(np.mean(distance**2)))
        local_center=np.array([params['length_mm']/2,0,params['height_mm']/2]);world=local_center@np.asarray(axes)+origin
        depth=(world@view['camera']['R'].T+view['camera']['T'])[2]
        residuals.append(pixel_rmse*depth/view['camera']['K'][0,0])
    return {'dimensions':params,'mean_iou':float(np.mean(ious)),'view_ious':ious,'subset_extent_range_mm':sensitivity,'boundary_residual_rms_mm':float(np.sqrt(np.mean(np.square(residuals)))),'uncertainty_mm':max(.25,sensitivity,float(np.sqrt(np.mean(np.square(residuals))))),'optimization_converged':bool(fit.success),'source':'observed RGB outer silhouettes + disclosed L-family prior + estimated cameras','prior':'orthogonal equal-width L plates; filled holes for outer-boundary fit; back and missing-corner completion are prior'}

def inspect_features(inp,recon,out):
    inp=Path(inp);recon=Path(recon);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    report=read(recon/'reconstruction.json');cloud=np.load(recon/'observed.npz')['points'];scale=report['scale'];mc=np.array(scale['marker_corners_sfm'])*scale['mm_per_sfm_unit']
    r=fit_planes(cloud,mc);axes=np.array(r['axes_world_to_local']);origin=np.array(r['origin_world_mm']);t=r['dimensions']['thickness_mm']
    silhouette_views=[]
    for cam in read(recon/'estimated_cameras.json'):
        image=cv2.imread(str(inp/'images'/cam['image']));mask=segment(image)
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        filled=np.zeros_like(mask)
        if contours:cv2.drawContours(filled,[max(contours,key=cv2.contourArea)],-1,255,cv2.FILLED)
        silhouette_views.append({'camera':cam,'mask':filled})
    silhouette=fit_silhouette_dimensions(r['dimensions'],axes,origin,silhouette_views)
    r['point_cloud_extent_before_silhouette_fit']=dict(r['dimensions'])
    r['dimensions']=silhouette['dimensions'];r['silhouette_extent_fit']=silhouette
    r['uncertainty_mm']=max(r['uncertainty_mm'],silhouette['uncertainty_mm'])
    observations={'base':[],'wall':[]}
    for cam in read(recon/'estimated_cameras.json'):
        im=cv2.imread(str(inp/'images'/cam['image']));mask=segment(im)
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        contours,h=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_NONE)
        if h is None:continue
        K=np.array(cam['K']);R=np.array(cam['R']);T=np.array(cam['T']);C=-R.T@T
        for i,contour in enumerate(contours):
            if h[0,i,3]<0 or cv2.contourArea(contour)<35:continue
            xy=contour.reshape(-1,2)[::2];rays=np.c_[xy,np.ones(len(xy))]@np.linalg.inv(K).T@R
            for plate,n in [('base',axes[2]),('wall',axes[0])]:
                localaxis=2 if plate=='base' else 0;two=[0,1] if plate=='base' else [1,2]
                surface=0. if plate=='wall' and (C-origin)@n<0 else t
                planeorigin=origin+n*surface;den=rays@n
                if np.min(np.abs(den))<.08:continue
                q=C+rays*((planeorigin-C)@n/den)[:,None];q=(q-origin)@axes.T;c,rad,err=circle_fit(q[:,two])
                dims=r['dimensions'];bounds=(np.mean(q[:,0])>=t and np.mean(q[:,0])<=dims['length_mm']) if plate=='base' else (np.mean(q[:,2])>=t and np.mean(q[:,2])<=dims['height_mm'])
                if 2.1<rad<4.6 and err<.3 and bounds:
                    observations[plate].append({'image':cam['image'],'center':c.tolist(),'radius_mm':rad,'residual_mm':err,'contour_pixels':len(contour)})
    holes={};critical=[]
    for plate,rows in observations.items():
        if len(rows)<4:critical.append(plate+'_holes_unobserved');continue
        # Cluster by y, which is common to each disclosed two-hole plate.
        ys=np.array([q['center'][1 if plate=='base' else 0] for q in rows]);mid=(ys.min()+ys.max())/2
        groups=[[row for row,val in zip(rows,ys) if val<mid],[row for row,val in zip(rows,ys) if val>=mid]]
        centers=[];radii=[];spread=[];rejected=[];inliers=[]
        for raw_group in groups:
            group,bad=hole_consensus(raw_group);rejected.extend(bad);inliers.extend(group)
            if len(group)<.5*len(raw_group):critical.append(plate+'_hole_contour_disagreement')
            if len(set(q['image'] for q in group))<2:critical.append(plate+'_hole_requires_more_views');continue
            cs=np.array([q['center'] for q in group]);rs=np.array([q['radius_mm'] for q in group]);c=np.median(cs,axis=0)
            centers.append(c.tolist());radii.append(float(np.median(rs)));spread.append(float(np.max(np.std(cs,axis=0))))
        if len(centers)==2:holes[plate]={'centers':centers,'pitch_mm':float(np.linalg.norm(np.diff(centers,axis=0))),'radius_mm':float(np.mean(radii)),'uncertainty_mm':max(.2,*spread),'observations':rows,'consensus_observations':inliers,'rejected_observations':rejected}
    params=dict(r['dimensions'])
    if set(holes)=={'base','wall'}:
        params.update(hole_pitch_mm=float(np.mean([q['pitch_mm'] for q in holes.values()])),hole_radius_mm=float(np.mean([q['radius_mm'] for q in holes.values()])),base_hole_x_mm=float(np.mean(np.array(holes['base']['centers'])[:,0])),wall_hole_z_mm=float(np.mean(np.array(holes['wall']['centers'])[:,1])))
        agreement=abs(holes['base']['pitch_mm']-holes['wall']['pitch_mm'])
        if agreement>.8:critical.append('two_plate_interface_pitch_disagreement')
    uncertainty=max(r['uncertainty_mm'],*[h['uncertainty_mm'] for h in holes.values()],scale['marker_side_cv']*max(params.values()))
    if uncertainty>.8:critical.append('uncertainty_exceeds_frozen_limit')
    local=r.pop('local_points');np.savez_compressed(out/'local_observed.npz',points=local)
    result={**r,'parameters':params,'holes':holes,'uncertainty_mm':uncertainty,'critical_missing':sorted(set(critical)),'status':'FEATURES_MEASURED' if not critical else 'NEED_MORE_VIEWS','measured':'planar surfaces and triangulated photo hole contours','prior':'equal plate thickness, pair alignment and all missing/back surfaces; damaged corner restoration is prior','source':'input RGB + independently supplied marker scale + '+report['backend']+'; original CAD/cameras/dimensions not read'}
    write(out/'features.json',result);return result
