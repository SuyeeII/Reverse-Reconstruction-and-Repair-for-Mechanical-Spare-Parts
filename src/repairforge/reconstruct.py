"""Truth-free reference-assisted official COLMAP; legacy OpenCV evidence is separate.
Only RGB images and a standalone reference marker measurement are accepted.
"""
from pathlib import Path
import json,time
import numpy as np,cv2
from .authority import read,write,digest

def validate_input(inp):
    inp=Path(inp).resolve();s=read(inp/'scale.json')
    allowed={'marker_dictionary','marker_id','marker_side_mm','measurement_uncertainty_mm','source','markers'}
    if set(s)-allowed:raise ValueError('UNSUPPORTED_SCALE_FIELD')
    if not 1<float(s['marker_side_mm'])<500:raise ValueError('INVALID_SCALE_REFERENCE')
    if inp.is_symlink() or 'oracle' in inp.parts:raise ValueError('TRUTH_PATH_FORBIDDEN')
    files=sorted((inp/'images').glob('*.png'))+sorted((inp/'images').glob('*.jpg'))
    if not 12<=len(files)<=24:raise ValueError('NEED_12_TO_24_VIEWS')
    if any(f.is_symlink() for f in files):raise ValueError('INPUT_SYMLINK_FORBIDDEN')
    return s,files

def segment(im):
    hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
    return ((hsv[:,:,1]>80)&(hsv[:,:,0]>=130)&(hsv[:,:,0]<=175)).astype(np.uint8)*255

def triangulate_marker(reconstruction,inp,s):
    dictionary=cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco,s['marker_dictionary']));det=cv2.aruco.ArucoDetector(dictionary)
    obs=[]
    for im in reconstruction.images.values():
        image=cv2.imread(str(inp/'images'/im.name));corners,ids,_=det.detectMarkers(image)
        if ids is None or int(s['marker_id']) not in ids:continue
        corner=corners[int(np.where(ids.flatten()==int(s['marker_id']))[0][0])].reshape(4,2)
        R=im.cam_from_world().rotation.matrix();T=im.cam_from_world().translation;K=reconstruction.cameras[im.camera_id].calibration_matrix();P=K@np.c_[R,T]
        obs.append((im.name,corner,P))
    if len(obs)<3:raise ValueError('INSUFFICIENT_SCALE_MARKER_VIEWS')
    points=[];errors=[]
    for corner_index in range(4):
        A=[]
        for _,corners,P in obs:
            u,v=corners[corner_index];A.extend([u*P[2]-P[0],v*P[2]-P[1]])
        _,_,V=np.linalg.svd(A);q=V[-1];q=q[:3]/q[3];points.append(q)
        for _,corners,P in obs:
            u=P@np.r_[q,1];errors.append(float(np.linalg.norm(u[:2]/u[2]-corners[corner_index])))
    points=np.array(points);sides=np.linalg.norm(points-np.roll(points,-1,axis=0),axis=1)
    factor=s['marker_side_mm']/np.median(sides)
    report={'method':'4 observed ArUco corners triangulated in COLMAP estimated cameras','visible_marker_views':len(obs),'marker_side_mm':s['marker_side_mm'],'mm_per_sfm_unit':float(factor),'marker_side_cv':float(np.std(sides)/np.mean(sides)),'marker_reprojection_rmse_px':float(np.sqrt(np.mean(np.square(errors)))),'marker_corners_sfm':points.tolist(),'reference_measurement_uncertainty_mm':s.get('measurement_uncertainty_mm',0),'source':'image observations + separately supplied marker length'}
    if report['marker_side_cv']>.05 or report['marker_reprojection_rmse_px']>3:raise ValueError('SCALE_REFERENCE_INCONSISTENT')
    return factor,report

def reconstruct_colmap(inp,out):
    import pycolmap,open3d as o3d
    inp=Path(inp).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True);scale,files=validate_input(inp);start=time.monotonic()
    db=out/'database.db';sp=out/'sparse';sp.mkdir(exist_ok=True)
    if db.exists():raise ValueError('RECONSTRUCTION_OUTPUT_ALREADY_EXISTS')
    ex=pycolmap.FeatureExtractionOptions();ex.num_threads=4;ex.use_gpu=False;ex.max_image_size=900;ex.sift.max_num_features=12000;ex.sift.peak_threshold=.003
    pycolmap.extract_features(str(db),str(inp/'images'),camera_mode=pycolmap.CameraMode.SINGLE,camera_model='PINHOLE',extraction_options=ex,device=pycolmap.Device.cpu)
    match=pycolmap.FeatureMatchingOptions();match.num_threads=4;match.use_gpu=False
    pycolmap.match_exhaustive(str(db),matching_options=match,device=pycolmap.Device.cpu)
    opts=pycolmap.IncrementalPipelineOptions();opts.num_threads=4;opts.mapper.num_threads=4;opts.random_seed=17;opts.mapper.random_seed=17;opts.mapper.init_min_tri_angle=8;opts.min_model_size=6
    models=pycolmap.incremental_mapping(str(db),str(inp/'images'),str(sp),options=opts)
    if not models:raise ValueError('COLMAP_NO_RECONSTRUCTION')
    rec=max(models.values(),key=lambda r:r.num_reg_images());factor,marker=triangulate_marker(rec,inp,scale)
    ids=list(rec.points3D);points=np.array([rec.points3D[i].xyz for i in ids]);colors=np.array([rec.points3D[i].color for i in ids])
    obscounts=np.zeros(len(points),int);fgcounts=np.zeros(len(points),int);idmap={pid:i for i,pid in enumerate(ids)}
    cameras=[]
    for im in rec.images.values():
        image=cv2.imread(str(inp/'images'/im.name));mask=segment(image);cv2.imwrite(str(out/(im.name+'.mask.png')),mask)
        for p2 in im.points2D:
            if not p2.has_point3D():continue
            ix=idmap.get(p2.point3D_id);x,y=np.rint(p2.xy).astype(int)
            if ix is not None and 0<=x<mask.shape[1] and 0<=y<mask.shape[0]:obscounts[ix]+=1;fgcounts[ix]+=int(mask[y,x]>0)
        cameras.append({'image':im.name,'K':rec.cameras[im.camera_id].calibration_matrix().tolist(),'R':im.cam_from_world().rotation.matrix().tolist(),'T':(im.cam_from_world().translation*factor).tolist(),'source':'estimated_by_COLMAP'})
    keep=(fgcounts>=2)&(fgcounts>=.75*obscounts)&np.isfinite(points).all(axis=1);pts=points[keep]*factor;cols=colors[keep]
    if len(pts)<300:raise ValueError('INSUFFICIENT_FOREGROUND_GEOMETRY')
    cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(pts);cloud.colors=o3d.utility.Vector3dVector(cols/255.)
    cloud,idx=cloud.remove_statistical_outlier(nb_neighbors=20,std_ratio=2.5);pts=np.asarray(cloud.points);cols=np.asarray(cloud.colors)
    o3d.io.write_point_cloud(str(out/'foreground.ply'),cloud);np.savez_compressed(out/'observed.npz',points=pts,colors=cols)
    rec.export_PLY(str(out/'sfm_unscaled.ply'))
    write(out/'estimated_cameras.json',cameras)
    report={'backend':'official pycolmap 3.13.0 / COLMAP CPU SIFT + bundle adjustment','camera_input':'none; unknown intrinsics/extrinsics estimated from images','truth_access':False,'geometry':'sparse multi-view triangulated RGB feature point cloud; not dense MVS','input_views':len(files),'registered_views':rec.num_reg_images(),'points_sfm':rec.num_points3D(),'foreground_points':len(pts),'mean_reprojection_error_px':rec.compute_mean_reprojection_error(),'scale':marker,'input_hashes':{f.name:digest(f) for f in files},'elapsed_seconds':time.monotonic()-start,'scope':'textured saturated purple L bracket; foreground segmentation from RGB HSV, requires masks for other colors','status':'RECONSTRUCTED'}
    write(out/'reconstruction.json',report);return report

def estimate_reference_cameras(inp,out):
    """Calibrate from independent board observations, before any part fitting.

    The board specification is a scale attachment. Camera parameters and the
    part's dimensions are never supplied by an image author or CAD oracle.
    """
    inp=Path(inp).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    scale,files=validate_input(inp)
    if 'markers' not in scale:raise ValueError('REFERENCE_BOARD_REQUIRED')
    board={m['id']:np.asarray(m['corners_mm'],np.float32) for m in scale['markers']}
    for corners in board.values():
        if corners.shape!=(4,3) or not np.isfinite(corners).all() or np.ptp(corners[:,2])>1e-6 or not np.allclose(np.linalg.norm(corners-np.roll(corners,-1,axis=0),axis=1),scale['marker_side_mm']):raise ValueError('INVALID_REFERENCE_BOARD')
    detector_params=cv2.aruco.DetectorParameters();detector_params.cornerRefinementMethod=cv2.aruco.CORNER_REFINE_SUBPIX
    detector=cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco,scale['marker_dictionary'])),detector_params)
    objects=[];pixels=[];names=[];size=None;skipped=[]
    for f in files:
        image=cv2.imread(str(f))
        if image is None:raise ValueError('IMAGE_DECODE_FAILED')
        current=(image.shape[1],image.shape[0])
        if size is not None and current!=size:raise ValueError('MIXED_IMAGE_DIMENSIONS')
        size=current;corners,ids,_=detector.detectMarkers(image)
        pairs=[] if ids is None else [(board[int(i)],c.reshape(4,2)) for i,c in zip(ids.flatten(),corners) if int(i) in board]
        if len(pairs)<2:skipped.append({'image':f.name,'reason':'fewer than two reference markers'});continue
        objects.append(np.vstack([p[0] for p in pairs]));pixels.append(np.vstack([p[1] for p in pairs]));names.append(f.name)
    if len(objects)<6:raise ValueError('NEED_MORE_REFERENCE_BOARD_VIEWS')
    K0=np.array([[size[0]*1.2,0,size[0]/2],[0,size[0]*1.2,size[1]/2],[0,0,1.]])
    flags=cv2.CALIB_USE_INTRINSIC_GUESS|cv2.CALIB_FIX_ASPECT_RATIO|cv2.CALIB_ZERO_TANGENT_DIST|cv2.CALIB_FIX_K1|cv2.CALIB_FIX_K2|cv2.CALIB_FIX_K3|cv2.CALIB_FIX_K4|cv2.CALIB_FIX_K5|cv2.CALIB_FIX_K6
    rms,K,dist,rotations,translations=cv2.calibrateCamera(objects,pixels,size,K0,np.zeros(5),flags=flags)
    if rms>1.5 or not .4*size[0]<K[0,0]<3*size[0]:raise ValueError('REFERENCE_CAMERA_CALIBRATION_FAILED')
    cameras=[]
    for name,obj,pix,rv,tv in zip(names,objects,pixels,rotations,translations):
        err=float(np.sqrt(np.mean(np.sum((cv2.projectPoints(obj,rv,tv,K,dist)[0].reshape(-1,2)-pix)**2,axis=1))))
        if err>1.5:skipped.append({'image':name,'reason':'marker residual exceeds 1.5 px','rmse_px':err});continue
        cameras.append({'image':name,'K':K.tolist(),'R':cv2.Rodrigues(rv)[0].tolist(),'T':tv.flatten().tolist(),'marker_reprojection_rmse_px':err,'source':'estimated only from RGB-observed independent reference board'})
    if len(cameras)<6:raise ValueError('NEED_MORE_REFERENCE_BOARD_VIEWS')
    result={'cameras':cameras,'rmse_px':float(rms),'image_size':list(size),'input_views':len(files),'registered_views':len(cameras),'skipped_views':skipped,'truth_access':False,'scale_attachment_sha256':digest(inp/'scale.json'),'scope':'shared pinhole, square pixels and zero distortion; observed reference board only'}
    write(out/'reference_calibration.json',result);write(out/'reference_estimated_cameras.json',cameras)
    return result

def reconstruct_colmap_metric(inp,out):
    """Official COLMAP SIFT, multi-view tracks and geometric triangulation.

    Initial camera poses come from observed scale-board images. This is
    reference-assisted photogrammetry, not uncalibrated SfM or VGGT inference.
    """
    import pycolmap,open3d as o3d
    inp=Path(inp).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    scale,files=validate_input(inp);started=time.monotonic();dbpath=out/'database.db'
    if dbpath.exists():raise ValueError('RECONSTRUCTION_OUTPUT_ALREADY_EXISTS')
    calibration=estimate_reference_cameras(inp,out)
    selected={c['image']:c for c in calibration['cameras']}
    masks=out/'rgb_masks';masks.mkdir()
    for name in selected:
        cv2.imwrite(str(masks/(name+'.png')),segment(cv2.imread(str(inp/'images'/name))))
    K=np.asarray(calibration['cameras'][0]['K']);width,height=calibration['image_size']
    reader=pycolmap.ImageReaderOptions();reader.mask_path=str(masks)
    reader.camera_params=','.join(str(x) for x in [K[0,0],K[1,1],K[0,2],K[1,2]])
    ex=pycolmap.FeatureExtractionOptions();ex.num_threads=4;ex.use_gpu=False;ex.max_image_size=900;ex.sift.max_num_features=12000;ex.sift.peak_threshold=.003
    pycolmap.extract_features(str(dbpath),str(inp/'images'),image_names=sorted(selected),camera_mode=pycolmap.CameraMode.SINGLE,camera_model='PINHOLE',reader_options=reader,extraction_options=ex,device=pycolmap.Device.cpu)
    match=pycolmap.FeatureMatchingOptions();match.num_threads=4;match.use_gpu=False;match.guided_matching=True
    verify=pycolmap.TwoViewGeometryOptions();verify.ransac.max_error=1.5
    pycolmap.match_exhaustive(str(dbpath),matching_options=match,verification_options=verify,device=pycolmap.Device.cpu)
    database=pycolmap.Database.open(str(dbpath))
    try:dbimages=database.read_all_images();dbcameras=database.read_all_cameras()
    finally:database.close()
    initial=out/'reference_initial';initial.mkdir()
    camera_lines=[]
    for camera in dbcameras:
        camera_lines.append(f"{camera.camera_id} PINHOLE {width} {height} "+' '.join(str(v) for v in [K[0,0],K[1,1],K[0,2],K[1,2]]))
    image_lines=[]
    for image in dbimages:
        cam=selected[image.name];quat=pycolmap.Rotation3d(np.asarray(cam['R'])).quat
        values=[quat[3],*quat[:3],*cam['T']]
        image_lines.append(f"{image.image_id} "+' '.join(str(x) for x in values)+f" {image.camera_id} {image.name}\n")
    (initial/'cameras.txt').write_text('\n'.join(camera_lines)+'\n')
    (initial/'images.txt').write_text('\n'.join(image_lines)+'\n')
    (initial/'points3D.txt').write_text('')
    reconstruction=pycolmap.Reconstruction();reconstruction.read_text(str(initial))
    opts=pycolmap.IncrementalPipelineOptions();opts.num_threads=4;opts.mapper.num_threads=4;opts.random_seed=17;opts.triangulation.random_seed=17
    opts.triangulation.min_angle=3.;opts.triangulation.ignore_two_view_tracks=False
    opts.triangulation.merge_max_reproj_error=1.5;opts.triangulation.complete_max_reproj_error=1.5
    opts.ba_refine_focal_length=False;opts.ba_refine_extra_params=False;opts.ba_refine_principal_point=False;opts.fix_existing_frames=True
    opts.max_runtime_seconds=240
    reconstruction=pycolmap.triangulate_points(reconstruction,str(dbpath),str(inp/'images'),str(out/'sparse'),options=opts,refine_intrinsics=False)
    factor,marker=triangulate_marker(reconstruction,inp,scale)
    ids=list(reconstruction.points3D)
    if not ids:raise ValueError('COLMAP_NO_FOREGROUND_TRACKS')
    points=np.array([reconstruction.points3D[i].xyz for i in ids])*factor
    colors=np.array([reconstruction.points3D[i].color for i in ids])/255.
    cameras=[];data=[];track_lengths=[]
    for image in reconstruction.images.values():
        rotation=image.cam_from_world().rotation.matrix();translation=image.cam_from_world().translation*factor
        kmat=reconstruction.cameras[image.camera_id].calibration_matrix();mask=segment(cv2.imread(str(inp/'images'/image.name)))
        cameras.append({'image':image.name,'K':kmat.tolist(),'R':rotation.tolist(),'T':translation.tolist(),'source':'COLMAP multi-view triangulation with reference-board RGB estimated initial cameras; no truth camera'})
        data.append({'P':kmat@np.c_[rotation,translation],'mask':mask})
    for i in ids:track_lengths.append(len(reconstruction.points3D[i].track.elements))
    visible,agreement=silhouette_consistency(points,data)
    finite=np.isfinite(points).all(axis=1)
    # Existing reference-board domain bounds and 300-point admission are retained.
    keep=visible&finite&(points[:,2]>-.5)&(points[:,2]<100)&(np.abs(points[:,0])<150)&(np.abs(points[:,1])<100)
    cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(points[keep]);cloud.colors=o3d.utility.Vector3dVector(colors[keep])
    cloud=cloud.voxel_down_sample(.15)
    if len(cloud.points)>=20:cloud,_=cloud.remove_statistical_outlier(nb_neighbors=20,std_ratio=2.5)
    count=len(cloud.points)
    diagnostics={'backend':'official pycolmap 3.13.0 COLMAP CPU','registered_views':reconstruction.num_reg_images(),'colmap_points':len(ids),'visibility_consistent_points':int(keep.sum()),'filtered_foreground_points':count,'required_foreground_points':300,'calibration_rmse_px':calibration['rmse_px'],'mean_reprojection_error_px':reconstruction.compute_mean_reprojection_error(),'track_length_min':int(min(track_lengths)),'track_length_median':float(np.median(track_lengths)),'reference_scale':marker,'truth_access':False}
    write(out/'geometry_diagnostics.json',diagnostics)
    if count<300:raise ValueError(f'INSUFFICIENT_FOREGROUND_GEOMETRY: official COLMAP filtered {count} points; minimum remains 300')
    o3d.io.write_point_cloud(str(out/'foreground.ply'),cloud);np.savez_compressed(out/'observed.npz',points=np.asarray(cloud.points),colors=np.asarray(cloud.colors))
    write(out/'estimated_cameras.json',cameras)
    result={'status':'RECONSTRUCTED','backend':'official pycolmap 3.13.0 / COLMAP CPU SIFT + guided geometric matching + multi-view triangulation','camera_input':'reference-board RGB estimated cameras; no original CAD or truth cameras','geometry':'sparse observed multi-view track point cloud; not dense MVS, VGGT, or shape completion','truth_access':False,'input_views':len(files),'registered_views':reconstruction.num_reg_images(),'foreground_points':count,'points_sfm':len(ids),'mean_reprojection_error_px':diagnostics['mean_reprojection_error_px'],'camera_calibration_rmse_px':calibration['rmse_px'],'scale':marker,'input_hashes':{f.name:digest(f) for f in files},'elapsed_seconds':time.monotonic()-started,'scope':'textured saturated purple L bracket; independent reference-board attachment; RGB-only HSV foreground mask; missing shape remains prior','silhouette_verification':{'input_points':len(ids),'kept_points':int(keep.sum()),'minimum_view_fraction':.7}}
    write(out/'reconstruction.json',result);return result

def metric_triangulate(xy1,xy2,P1,P2):
    q=cv2.triangulatePoints(np.asarray(P1,dtype=float),np.asarray(P2,dtype=float),np.asarray(xy1,dtype=float).T,np.asarray(xy2,dtype=float).T).T
    points=q[:,:3]/q[:,3,None];h=np.c_[points,np.ones(len(points))];u1=h@P1.T;u2=h@P2.T
    e1=np.linalg.norm(u1[:,:2]/u1[:,2,None]-xy1,axis=1);e2=np.linalg.norm(u2[:,:2]/u2[:,2,None]-xy2,axis=1)
    valid=np.isfinite(points).all(axis=1)&(u1[:,2]>0)&(u2[:,2]>0)&(e1<1.5)&(e2<1.5)
    return points,valid

def silhouette_consistency(points,data,threshold=.7):
    """Independent RGB multi-view silhouettes veto stereo false matches.

    Uses only estimated projection matrices and observed foreground masks.
    Out-of-frame or behind-camera projections count against agreement.
    """
    h=np.c_[points,np.ones(len(points))];votes=np.zeros(len(points),int)
    for view in data:
        q=h@view['P'].T;mask=view['mask'];uv=q[:,:2]/np.maximum(q[:,2,None],1e-9)
        xy=np.rint(np.clip(uv,-1e6,1e6)).astype(int)
        inside=(q[:,2]>0)&(xy[:,0]>=0)&(xy[:,0]<mask.shape[1])&(xy[:,1]>=0)&(xy[:,1]<mask.shape[0])
        ix=np.flatnonzero(inside);votes[ix]+=(mask[xy[ix,1],xy[ix,0]]>0)
    ratios=votes/max(1,len(data))
    return (votes>=3)&(ratios>=threshold),ratios

def reconstruct(inp,out):
    """Restricted fiducial-assisted multi-view triangulation; not COLMAP success."""
    import open3d as o3d
    inp=Path(inp).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True);scale,files=validate_input(inp);start=time.monotonic()
    if 'markers' not in scale:return reconstruct_colmap(inp,out)
    detector_params=cv2.aruco.DetectorParameters();detector_params.cornerRefinementMethod=cv2.aruco.CORNER_REFINE_SUBPIX
    detector=cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco,scale['marker_dictionary'])),detector_params)
    board={m['id']:np.array(m['corners_mm'],np.float32) for m in scale['markers']}
    for m in board.values():
        if m.shape!=(4,3) or not np.isfinite(m).all() or np.ptp(m[:,2])>1e-6 or not np.allclose(np.linalg.norm(m-np.roll(m,-1,axis=0),axis=1),scale['marker_side_mm']):raise ValueError('INVALID_REFERENCE_BOARD')
    observations=[];obj=[];pix=[];size=None
    for f in files:
        im=cv2.imread(str(f));cs,ids,_=detector.detectMarkers(im);size=(im.shape[1],im.shape[0]);pairs=[]
        if ids is not None:
            pairs=[(board[int(i)],c.reshape(4,2)) for i,c in zip(ids.flatten(),cs) if int(i) in board]
        if len(pairs)<2:continue
        op=np.vstack([p[0] for p in pairs]);ip=np.vstack([p[1] for p in pairs]);observations.append((f,im,op,ip));obj.append(op);pix.append(ip)
    if len(obj)<6:raise ValueError('NEED_MORE_REFERENCE_BOARD_VIEWS')
    K0=np.array([[size[0]*1.2,0,size[0]/2],[0,size[0]*1.2,size[1]/2],[0,0,1.]])
    flags=cv2.CALIB_USE_INTRINSIC_GUESS|cv2.CALIB_FIX_ASPECT_RATIO|cv2.CALIB_ZERO_TANGENT_DIST|cv2.CALIB_FIX_K1|cv2.CALIB_FIX_K2|cv2.CALIB_FIX_K3|cv2.CALIB_FIX_K4|cv2.CALIB_FIX_K5|cv2.CALIB_FIX_K6
    rms,K,dist,rv,tv=cv2.calibrateCamera(obj,pix,size,K0,np.zeros(5),flags=flags)
    if rms>1.5 or not .4*size[0]<K[0,0]<3*size[0]:raise ValueError('REFERENCE_CAMERA_CALIBRATION_FAILED')
    cameras=[];data=[];sift=cv2.SIFT_create(nfeatures=12000,contrastThreshold=.012)
    calibration_errors=[]
    for (f,im,op,ip),r,t in zip(observations,rv,tv):
        R=cv2.Rodrigues(r)[0];T=t.flatten();P=K@np.c_[R,T];pred=cv2.projectPoints(op,r,t,K,dist)[0].reshape(-1,2);err=float(np.sqrt(np.mean(np.sum((pred-ip)**2,axis=1))));calibration_errors.append(err)
        if err>1.5:continue
        mask=segment(im);cv2.imwrite(str(out/(f.name+'.mask.png')),mask)
        kp,desc=sift.detectAndCompute(cv2.cvtColor(im,cv2.COLOR_BGR2GRAY),mask)
        if desc is None:continue
        cameras.append({'image':f.name,'K':K.tolist(),'R':R.tolist(),'T':T.tolist(),'source':'RGB-observed external marker-board calibration; not truth camera','marker_reprojection_rmse_px':err})
        data.append({'name':f.name,'points':np.array([p.pt for p in kp]),'desc':desc,'P':P,'R':R,'T':T,'image':im,'K':K,'mask':mask})
    points=[];colors=[];pair_reports=[];matcher=cv2.FlannBasedMatcher(dict(algorithm=1,trees=4),dict(checks=80))
    for i in range(len(data)):
        for j in range(i+1,len(data)):
            a,b=data[i],data[j];Ca=-a['R'].T@a['T'];Cb=-b['R'].T@b['T']
            if np.linalg.norm(Ca-Cb)<10 or np.linalg.norm(Ca-Cb)>220:continue
            pairs=matcher.knnMatch(a['desc'],b['desc'],k=2);matches=[x for p in pairs if len(p)==2 for x,y in [p] if x.distance<.72*y.distance]
            if len(matches)<5:continue
            x1=np.array([a['points'][m.queryIdx] for m in matches]);x2=np.array([b['points'][m.trainIdx] for m in matches]);pts,valid=metric_triangulate(x1,x2,a['P'],b['P'])
            rays1=pts-Ca;rays2=pts-Cb;angle=np.degrees(np.arccos(np.clip(np.sum(rays1*rays2,axis=1)/(np.linalg.norm(rays1,axis=1)*np.linalg.norm(rays2,axis=1)),-1,1)))
            valid&=(angle>3)&(pts[:,2]>-.5)&(pts[:,2]<100)&(np.abs(pts[:,0])<150)&(np.abs(pts[:,1])<100)
            pts=pts[valid];xy=x1[valid].astype(int)
            if len(pts):points.append(pts);colors.append(a['image'][xy[:,1],xy[:,0]][:,::-1]/255.)
            pair_reports.append({'images':[a['name'],b['name']],'ratio_matches':len(matches),'geometrically_valid_points':len(pts)})
    # Densify the same observations; no family geometry is supplied to stereo.
    for i in range(len(data)-1):
        a,b=data[i],data[i+1]
        dp,dc=dense_pair(a,b)
        if len(dp):
            good=(dp[:,2]>-.5)&(dp[:,2]<100)&(np.abs(dp[:,0])<150)&(np.abs(dp[:,1])<100)
            dp,dc=dp[good],dc[good]
            if len(dp):points.append(dp[::4]);colors.append(dc[::4])
        pair_reports.append({'images':[a['name'],b['name']],'dense_stereo_valid_points':len(dp)})
    if not points:raise ValueError('NO_METRIC_STEREO_GEOMETRY')
    all_points=np.vstack(points);all_colors=np.vstack(colors)
    keep,agreement=silhouette_consistency(all_points,data)
    cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(all_points[keep]);cloud.colors=o3d.utility.Vector3dVector(all_colors[keep]);cloud=cloud.voxel_down_sample(.15)
    cloud,ix=cloud.remove_statistical_outlier(nb_neighbors=20,std_ratio=2.5);pts=np.asarray(cloud.points)
    write(out/'geometry_diagnostics.json',{'registered_views':len(data),'triangulated_points_before_visibility_filter':len(all_points),'visibility_consistent_points':int(keep.sum()),'filtered_foreground_points':len(pts),'required_foreground_points':300,'calibration_rmse_px':rms,'meaning':'Point count is an algorithm admission condition, not proof that holes are invisible. Geometry/acceptance thresholds are unchanged.'})
    if len(pts)<300:raise ValueError('INSUFFICIENT_FOREGROUND_GEOMETRY: filtered '+str(len(pts))+' points; minimum 300. This is an algorithm limitation, not a claim that all photo features are invisible.')
    o3d.io.write_point_cloud(str(out/'foreground.ply'),cloud);np.savez_compressed(out/'observed.npz',points=pts,colors=np.asarray(cloud.colors))
    write(out/'estimated_cameras.json',cameras)
    scale_report={'method':'external four-marker scale board, RGB-observed camera calibration and metric triangulation','marker_side_mm':scale['marker_side_mm'],'marker_corners_sfm':board[scale['marker_id']].astype(float).tolist(),'mm_per_sfm_unit':1.,'visible_marker_views':len(obj),'marker_reprojection_rmse_px':rms,'marker_side_cv':0.,'marker_side_cv_note':'known reference board specification; not measured scale accuracy','reference_measurement_uncertainty_mm':scale.get('measurement_uncertainty_mm',0)}
    r={'backend':'OpenCV 4.12 fiducial-assisted camera calibration + SIFT + metric multi-view triangulation','fallback_from':'official COLMAP free-camera reconstruction failed admission; negative runs retained','camera_input':'none; calibration estimated only from RGB observations of independent reference board','estimated_camera_K':K.tolist(),'camera_calibration_rmse_px':rms,'camera_model_assumption':'shared fixed-focus pinhole, square pixels, zero distortion; use calibrated photos/undistortion for other optics','truth_access':False,'geometry':'observed SIFT triangulation + CPU StereoSGBM dense stereo, no original part CAD/depth/size read','input_views':len(files),'registered_views':len(data),'foreground_points':len(pts),'scale':scale_report,'pair_reports':pair_reports,'input_hashes':{f.name:digest(f) for f in files},'elapsed_seconds':time.monotonic()-start,'scope':'textured saturated purple L bracket on independent reference-board plane','status':'RECONSTRUCTED'}
    r['silhouette_verification']={'input_points':len(all_points),'kept_points':int(keep.sum()),'minimum_view_fraction':.7,'method':'project each triangulated point into all RGB foreground masks; no truth access'}
    write(out/'reconstruction.json',r);return r

def dense_pair(a,b):
    """CPU rectified StereoSGBM. Cameras came from RGB reference-board calibration."""
    K=np.asarray(a['K']);size=(a['image'].shape[1],a['image'].shape[0]);R=b['R']@a['R'].T;T=b['T']-R@a['T']
    R1,R2,P1,P2,Q,_,_=cv2.stereoRectify(K,np.zeros(5),K,np.zeros(5),size,R,T,flags=cv2.CALIB_ZERO_DISPARITY,alpha=0)
    if abs(P2[1,3])>abs(P2[0,3]):return np.empty((0,3)),np.empty((0,3))
    if P2[0,3]>0:return dense_pair(b,a)
    map1=cv2.initUndistortRectifyMap(K,np.zeros(5),R1,P1,size,cv2.CV_32FC1);map2=cv2.initUndistortRectifyMap(K,np.zeros(5),R2,P2,size,cv2.CV_32FC1)
    im1=cv2.remap(a['image'],*map1,cv2.INTER_LINEAR);im2=cv2.remap(b['image'],*map2,cv2.INTER_LINEAR)
    mask1=cv2.remap(a['mask'],*map1,cv2.INTER_NEAREST);mask2=cv2.remap(b['mask'],*map2,cv2.INTER_NEAREST)
    nd=max(32,min(384,(size[0]//2//16)*16))
    solver=cv2.StereoSGBM_create(minDisparity=0,numDisparities=nd,blockSize=5,P1=8*25,P2=32*25,disp12MaxDiff=1,uniquenessRatio=12,speckleWindowSize=60,speckleRange=2,mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
    d=solver.compute(cv2.cvtColor(im1,cv2.COLOR_BGR2GRAY),cv2.cvtColor(im2,cv2.COLOR_BGR2GRAY)).astype(float)/16
    rows,cols=np.indices(d.shape);xr=np.rint(cols-d).astype(int);inside=(xr>=0)&(xr<size[0]);clipped=np.clip(xr,0,size[0]-1)
    good=(d>.5)&(mask1>0)&inside&(mask2[rows,clipped]>0)
    gray1=cv2.cvtColor(im1,cv2.COLOR_BGR2GRAY);gray2=cv2.cvtColor(im2,cv2.COLOR_BGR2GRAY)
    good&=np.abs(gray1.astype(float)-gray2[rows,clipped])<35
    rect=cv2.reprojectImageTo3D(d.astype(np.float32),Q);world=(rect[good]@R1-a['T'])@a['R']
    good3=np.isfinite(world).all(axis=1)
    return world[good3],(im1[good][:,::-1]/255.)[good3]
