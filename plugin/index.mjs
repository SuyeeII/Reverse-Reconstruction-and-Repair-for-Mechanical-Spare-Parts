import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const Kind=Symbol.for('TypeBox.Kind');
const str={type:'string',[Kind]:'String',minLength:1,maxLength:100};
const integer={type:'integer',[Kind]:'Integer',minimum:0};
const num={type:'number',[Kind]:'Number'};
const obj=(properties,required=Object.keys(properties))=>({type:'object',[Kind]:'Object',properties,required,additionalProperties:false});
const base={run_id:str,decision_id:str,state_version:integer};
const specs=[
 ['view_photos',obj({run_id:str,frame_ids:{type:'array',[Kind]:'Array',items:str,minItems:1,maxItems:1}}),'查看已绑定输入的一张原生图像，例如 view_00.png。每次只能取1张，底座保留最近3条图像工具结果；可以逐次选择其他视角。返回原图、哈希、来源与独立尺度；视觉猜测不能作为毫米尺寸或验收。'],
 ['reconstruct_views',obj(base),'从原始RGB多视角图像及独立尺度板重建真实几何；不读取原CAD、真值尺寸、真值相机。'],
 ['inspect_features',obj(base),'拟合可观测平面、孔距与厚度；返回残差、不确定性、模板先验及缺失关键视角。'],
 ['propose_cad',obj(base),'按当前图像特征提议并生成第一个参数实体STEP/STL；不得自填未知接口。'],
 ['evaluate_design',obj({...base,candidate_id:str}),'运行真实Gmsh/scikit-fem两档网格有限元、反力和冻结约束验收，返回失败原因。'],
 ['list_candidates',obj({run_id:str}),'读取run当前状态版本、全部候选、结果及冻结约束。每个后续动作必须使用当前版本。'],
 ['revise_cad',obj({...base,parent_candidate_id:str,changes:obj({thickness_mm:num,fillet_mm:num},[])}),'根据真实失败只修改厚度（2..8 mm）和内角圆角（0..6 mm）；保留已测接口，候选总预算4。'],
 ['export_manufacturing',obj({...base,candidate_id:str}),'仅对物理约束通过的候选运行真实PrusaSlicer CLI，保存配置、非空G-code和运动刀路；时间/耗材为估计。']
];
function call(tool,args){return new Promise((resolve,reject)=>{
 const root=process.env.REPAIRFORGE_ROOT;if(!root) return reject(Error('REPAIRFORGE_ROOT required'));
 const proc=execFile(root+'/.venv/bin/python',['-m','repairforge.cli'],{cwd:root,env:process.env,timeout:300000,maxBuffer:2*1024*1024},(err,stdout,stderr)=>{
  try{const result=JSON.parse(stdout.trim());resolve(result)}catch{reject(Error('机械备件逆向重建与修复 executor did not return structured result'))}
 });proc.stdin.end(JSON.stringify({tool,args}));
});}
export const repairforge={inject:['extension'],apply(ctx){
 const domainTools=new Set(specs.map(([name])=>name));
 ctx.extension().registerHook('tool_call',p=>domainTools.has(p.name)?{allow:true}:{allow:false,reason:'机械备件逆向重建与修复 domain boundary: only the eight registered domain tools are permitted. Bound images are available through view_photos; independent numeric tools decide acceptance.'});
 ctx.extension().registerHook('context',()=>({additionalContext:'机械备件逆向重建与修复原生多模态领域会话：查看任务图像及必要时调用view_photos，判断零件族、尺度参考、遮挡和观测缺失。图像为仿真渲染，来源与独立尺度已按run_id绑定。专业工具以真实数值量测、有限元和切片验收；视觉估计不能覆盖真实量测或降低冻结阈值。自主选择合法修复分支；没有预定修复顺序。禁止read/ls/find/shell/todo等通用工具及oracle访问。'}));

 for(const [name,parameters,description] of specs)ctx.extension().registerTool({name,parameters,description,meta:{isReadOnly:['list_candidates','view_photos'].includes(name),isDestructive:false,isConcurrencySafe:false,isOpenWorld:false,replay:['list_candidates','view_photos'].includes(name)?'safe':'never',costHint:undefined,requiresApproval:'never',deferLoading:false,...(name==='view_photos'?{returnsImages:true}:{})},async execute(args,context){
  const result=await call(name,args),content=[{type:'text',text:JSON.stringify(result)}];
  if(name==='view_photos' && result.ok){
   for(const image of result.data.images){
    const bytes=await readFile(process.env.REPAIRFORGE_ROOT+'/'+image.path);
    if(createHash('sha256').update(bytes).digest('hex')!==image.sha256)throw Error('INPUT_CHANGED');
    const ref=await context.artifacts.put(bytes,{mime:image.mime,name:image.frame_id});
    content.push({type:'image',ref,mime:image.mime});
   }
  }
  return {content,structured:result,isError:!result.ok};
 }});
 ctx.services.register({name:'repairforgevisionv3.summary',kind:'query',inputSchema:{type:'object',properties:{},additionalProperties:false},outputSchema:{type:'object'},timeoutMs:10000,maxResultBytes:262144,async handler(){const r=await call('summary',{});if(!r.ok)throw Error('Summary unavailable');return r.data;}});
}};
