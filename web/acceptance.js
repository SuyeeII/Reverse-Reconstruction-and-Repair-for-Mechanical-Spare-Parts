export function verdict(scene){
 const audit=scene.independent_acceptance;
 if(!audit)return {accepted:false,label:'独立验收待完成',reason:'当前展示已保存的计算结果，完整验收尚未完成。'};
 if(audit.full_vision_delivery_pass===true)return {accepted:true,label:'完整独立验收通过',reason:'单次任务、模型身份、图像传输、尺度量测、CAD、有限元和切片均已核对。'};
 if(audit.protocol_pass===false)return {accepted:false,label:'会话运行失败 · 负结果保留',reason:'查看原始会话和错误反馈。没有补提示把中断会话记为成功。'};
 if(audit.independent_geometry_pass===false&&audit.input_geometry_errors==null)return {accepted:false,label:'几何精度待核对 · 完整验收未完成',reason:'没有独立几何真值，不宣称尺寸合格或超限。真实FEM与切片结果分别保留。'};
 if(audit.independent_geometry_pass===false)return {accepted:false,label:'完整验收失败 · 几何量测未通过',reason:'保留全部计算与切片结果；孔距、厚度或尺度未满足冻结限值，或缺少有效量测。'};
 return {accepted:false,label:'完整验收未通过',reason:'真实候选结果可回放；完整独立验收尚有未满足条件。'};
}
export function candidateVerdict(scene,candidate){
 const overall=verdict(scene);
 if(!overall.accepted||!candidate)return overall;
 if(candidate.summary?.accepted_physics===false)return {accepted:false,label:'当前候选失败 · 本次会话最终验收通过',reason:'这是首次真实失败；修复后的最终候选另有独立验收结果。'};
 if(candidate.status!=='ACCEPTED_COMPUTATIONAL_DELIVERY')return {accepted:false,label:'当前候选尚未完成交付 · 本次会话最终验收通过',reason:'验收结果对应最终候选，当前历史候选仍须核对。'};
 return overall;
}
