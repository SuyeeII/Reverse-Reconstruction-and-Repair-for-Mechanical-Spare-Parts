export function apply(ctx,config){
 let message='机械备件逆向重建与修复 · 等待当前会话';
 let off=ctx.slots.register('ui:sidebar',()=>message,{priority:-1});
 let disposed=false;
 const refresh=async()=>{if(disposed)return;try{const r=await ctx.agnes.services.call('repairforgevisionv3.summary',{});message='机械备件逆向重建与修复 · '+r.scope+'\n'+r.runs.map(x=>x.run_id+' · 状态 '+x.state_version+' · '+x.candidates.map(c=>c.candidate_id+': '+c.status+(c.evaluation?' / 位移 '+c.evaluation.max_displacement_mm.toFixed(3)+' mm / 应力 '+c.evaluation.max_von_mises_mpa.toFixed(2)+' MPa':'')).join(' → ')).join('\n')+'\n结果与刀路：http://127.0.0.1:48905';}catch{message='机械备件逆向重建与修复 · 当前会话服务尚未就绪';}};
 const update=async()=>{await refresh();if(disposed)return;if(typeof off==='function')off();const snapshot=message;off=ctx.slots.register('ui:sidebar',()=>snapshot,{priority:-1});};
 void update();const timer=setInterval(update,3000);ctx.effect(()=>()=>{disposed=true;clearInterval(timer);if(typeof off==='function')off();});
}
