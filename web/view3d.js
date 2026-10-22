import * as THREE from './vendor/three.module.js';
let renderer,camera,world,group,canvas,key=null,mesh;
export function drawScene(holder,data,candidate,tab,layer,yaw,pitch){
 if(!renderer){canvas=document.createElement('canvas');canvas.id='solidCanvas';canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';holder.append(canvas);renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true});renderer.setPixelRatio(window.devicePixelRatio||1);world=new THREE.Scene();camera=new THREE.PerspectiveCamera(35,1,.1,1000);camera.up.set(0,0,1);world.add(new THREE.HemisphereLight(0xf7fff5,0x49605c,2));const light=new THREE.DirectionalLight(0xffffff,2.7);light.position.set(80,-70,140);world.add(light);group=new THREE.Group();world.add(group);}
 canvas.style.display='block';const w=holder.clientWidth,h=holder.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();let p=candidate?.parameters||data.features?.parameters||{length_mm:50,height_mm:40,width_mm:40};let center=new THREE.Vector3(p.length_mm/2,0,p.height_mm/2);const next=data.run_id+'/'+candidate?.candidate_id+'/'+tab;
 if(next!==key){for(const child of [...group.children]){group.remove(child);child.geometry.dispose();child.material.dispose()}key=next;mesh=null;
  if(tab==='cloud'){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute((data.pointcloud||[]).flat(),3));mesh=new THREE.Points(g,new THREE.PointsMaterial({color:0x467aa0,size:.5}));}
  if(tab==='cad'||tab==='fem'){
   const source=tab==='fem'?candidate?.fem:candidate?.cad;
   if(source){const positions=[],colors=[];for(let i=0;i<source.faces.length;i++)for(const ix of source.faces[i]){positions.push(...source.vertices[ix]);if(tab==='fem'){let q=Math.max(0,Math.min(1,source.stress_mpa[i]/12));let c=new THREE.Color().setHSL(.57*(1-q),.68,.48);colors.push(c.r,c.g,c.b)}}const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));if(colors.length)g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));g.computeVertexNormals();mesh=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:tab==='fem'?0xffffff:0x438b76,vertexColors:tab==='fem',roughness:.75,metalness:.05,side:THREE.DoubleSide}));}
  }
  if(tab==='path'&&candidate?.paths){const positions=[],colors=[];for(const s of candidate.paths.segments){positions.push(...s.slice(0,6));for(let i=0;i<2;i++){const c=new THREE.Color(s[6]?0xddaa53:0x377d69);colors.push(c.r,c.g,c.b)}}const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));mesh=new THREE.LineSegments(g,new THREE.LineBasicMaterial({vertexColors:true}));}
  if(mesh)group.add(mesh);
 }
 if(tab==='path'){center.set(110,110,p.height_mm/2);if(mesh){let n=0;for(const s of candidate.paths.segments){if(s[7]<=layer)n+=2;else break}mesh.geometry.setDrawRange(0,n)}}
 group.position.copy(center).multiplyScalar(-1);const radius=Math.max(p.length_mm,p.height_mm,p.width_mm)*2.3;camera.position.set(radius*Math.cos(yaw)*Math.cos(pitch),radius*Math.sin(yaw)*Math.cos(pitch),radius*Math.sin(pitch));camera.lookAt(0,0,0);renderer.render(world,camera);
}
export function hide(){if(canvas)canvas.style.display='none'}
