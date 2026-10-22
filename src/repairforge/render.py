"""Independent synthetic INPUT AUTHOR, never imported by reconstruction/service.
Ground truth CAD/cameras/parameters remain in oracle. CPU perspective rasterization.
"""
from pathlib import Path
import numpy as np,cv2,trimesh
from .physics import make_cad
from .authority import write,digest

def look_at(camera,target):
    z=(target-camera);z/=np.linalg.norm(z);x=np.cross(z,np.array([0.,0.,1.]));x/=np.linalg.norm(x);y=np.cross(z,x)
    R=np.array([x,y,z]);return R,-R@camera

def raster(vertices,faces,R,T,K,res,seed,texture,labels):
    cam=vertices@R.T+T;projected=cam@K.T;uv=projected[:,:2]/projected[:,2:]
    image=np.full((res,res,3),235,np.uint8);depth=np.full((res,res),np.inf);mask=np.zeros((res,res),np.uint8)
    rng=np.random.default_rng(seed);noise=rng.integers(0,256,(7,512,512),dtype=np.uint8)
    markers=[(7,-35.,0.),(8,75.,0.),(9,20.,-45.),(10,20.,45.)]
    marker_images={i:cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),i,120) for i,_,_ in markers}
    # Each face's perspective-correct world position drives a stationary surface texture.
    for idx,face in enumerate(faces):
        if np.any(cam[face,2]<=0):continue
        tri=uv[face];xmin=max(0,int(np.floor(tri[:,0].min())));xmax=min(res-1,int(np.ceil(tri[:,0].max())))
        ymin=max(0,int(np.floor(tri[:,1].min())));ymax=min(res-1,int(np.ceil(tri[:,1].max())))
        if xmin>xmax or ymin>ymax:continue
        xs,ys=np.meshgrid(np.arange(xmin,xmax+1)+.5,np.arange(ymin,ymax+1)+.5)
        a,b,c=tri;det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(det)<1e-8:continue
        w0=((b[1]-c[1])*(xs-c[0])+(c[0]-b[0])*(ys-c[1]))/det
        w1=((c[1]-a[1])*(xs-c[0])+(a[0]-c[0])*(ys-c[1]))/det;w2=1-w0-w1
        wi=np.stack([w0,w1,w2],-1)/cam[face,2];di=wi.sum(axis=-1);z=1/np.maximum(di,1e-9)
        region=depth[ymin:ymax+1,xmin:xmax+1];valid=(w0>=-1e-6)&(w1>=-1e-6)&(w2>=-1e-6)&(z<region)
        if not valid.any():continue
        world=(wi@vertices[face])*z[:,:,None]
        normal=np.cross(vertices[face[1]]-vertices[face[0]],vertices[face[2]]-vertices[face[0]]);axis=np.argmax(np.abs(normal));coords=world[...,[(axis+1)%3,(axis+2)%3]]
        ix=np.floor(coords[...,0]/2.2).astype(int)%512;iy=np.floor(coords[...,1]/2.2).astype(int)%512
        surface=6 if labels[idx]==0 else axis*2+int(normal[axis]>0)
        n=noise[surface,ix,iy].astype(float)/255
        n2=noise[surface,(ix+137)%512,(iy+71)%512].astype(float)/255
        fraction=(coords/2.2)%1
        dot=((fraction[...,0]-(.2+.6*n))**2+(fraction[...,1]-(.2+.6*n2))**2)<(.10+.12*n2)**2
        pattern=np.where(dot,.22,.95)
        if labels[idx]==1:
            val=pattern if texture=='normal' else (.78+.10*pattern if texture=='weak' else np.full(n.shape,.85))
            color=val[...,None]*np.array([230,75,140.]) # BGR: saturated blue/purple object.
        else:
            val=pattern;color=np.repeat((val*205)[...,None],3,axis=2)
            # Ground reference independent of bracket. White quiet zone around the 20 mm marker.
            for mid,cx,cy in markers:
                quiet=(np.abs(world[...,0]-cx)<=13)&(np.abs(world[...,1]-cy)<=13)
                color[quiet]=255
                mk=(np.abs(world[...,0]-cx)<10)&(np.abs(world[...,1]-cy)<10)
                mx=np.clip(((world[...,0]-cx+10)*6).astype(int),0,119)
                my=np.clip(((cy+10-world[...,1])*6).astype(int),0,119)
                color[mk]=marker_images[mid][my[mk],mx[mk]][:,None]
        image[ymin:ymax+1,xmin:xmax+1][valid]=np.clip(color[valid],0,255).astype(np.uint8)
        region[valid]=z[valid];mask[ymin:ymax+1,xmin:xmax+1][valid]=labels[idx]
    return image,mask

def generate_case(case_id,p,input_root,oracle_root,seed=42,views=18,texture='normal',damage=0.,camera_mode='orbit'):
    inp=Path(input_root)/case_id;truth=Path(oracle_root)/case_id;inp.mkdir(parents=True,exist_ok=False);truth.mkdir(parents=True,exist_ok=False);(inp/'images').mkdir()
    make_cad(p,truth/'cad')
    mesh=trimesh.load(truth/'cad/part.stl',force='mesh')
    # Optional missing corner is a declared input defect, while the intended family is template prior.
    if damage:
        center=mesh.triangles_center;keep=~((center[:,0]>p['length_mm']-damage)&(center[:,1]>p['width_mm']/2-damage));mesh.update_faces(keep)
    ground=np.array([[-70.,-70.,-.05],[95.,-70.,-.05],[95.,70.,-.05],[-70.,70.,-.05]])
    vertices=np.vstack([mesh.vertices,ground]);faces=np.vstack([mesh.faces,np.array([[0,1,2],[0,2,3]])+len(mesh.vertices)]);labels=np.r_[np.ones(len(mesh.faces),int),np.zeros(2,int)]
    centers=mesh.triangles_center
    for yy in [-p['hole_pitch_mm']/2,p['hole_pitch_mm']/2]:
        bore_base=(np.abs(np.sqrt((centers[:,0]-p['base_hole_x_mm'])**2+(centers[:,1]-yy)**2)-p['hole_radius_mm'])<.03)&(centers[:,2]>0)&(centers[:,2]<p['thickness_mm'])
        bore_wall=(np.abs(np.sqrt((centers[:,2]-p['wall_hole_z_mm'])**2+(centers[:,1]-yy)**2)-p['hole_radius_mm'])<.03)&(centers[:,0]>0)&(centers[:,0]<p['thickness_mm'])
        labels[:len(mesh.faces)][bore_base|bore_wall]=2
    res=720;K=np.array([[820.,0,res/2],[0,820.,res/2],[0,0,1.]])
    rng=np.random.default_rng(seed);target=np.array([12.,0.,16.]);cameras=[]
    for i in range(views):
        a=2*np.pi*i/views+.12;radius=150.+rng.normal(0,3);elevation=(50. if i%3 else 180.)
        if camera_mode=='one_side':a=.1+.8*i/views
        pos=target+np.array([radius*np.cos(a),radius*np.sin(a),elevation+20])
        R,T=look_at(pos,target);im,mask=raster(vertices,faces,R,T,K,res,seed,texture,labels)
        cv2.imwrite(str(inp/'images'/f'view_{i:02d}.png'),im)
        # Diagnostic masks are oracle only. Reconstruction must segment from RGB.
        (truth/'masks').mkdir(exist_ok=True);cv2.imwrite(str(truth/'masks'/f'view_{i:02d}.png'),mask*255)
        cameras.append({'image':f'view_{i:02d}.png','K':K.tolist(),'R':R.tolist(),'T':T.tolist()})
    write(inp/'scale.json',{'marker_dictionary':'DICT_4X4_50','marker_id':7,'marker_side_mm':20.,'measurement_uncertainty_mm':.1,'source':'separately supplied four-marker reference board, not part CAD','markers':[{'id':i,'corners_mm':[[cx-10,cy+10,0],[cx+10,cy+10,0],[cx+10,cy-10,0],[cx-10,cy-10,0]]} for i,cx,cy in [(7,-35.,0.),(8,75.,0.),(9,20.,-45.),(10,20.,45.)]]})
    write(inp/'source.json',{'kind':'synthetic_render','views':views,'texture':texture,'bore_appearance':'dark contrasting bores; image-only color segmentation, no masks supplied','camera_coverage':camera_mode,'disclosed_prior':'equal-thickness L bracket, two circular holes in each plate; missing surfaces are prior, not measured','scale_input':'scale.json','masks':'computed from RGB by reconstruction; author masks withheld'})
    write(truth/'truth.json',{'parameters':p,'cameras':cameras,'seed':seed,'damage_mm':damage,'input_hashes':{f.name:digest(f) for f in (inp/'images').glob('*.png')}})
    return inp
