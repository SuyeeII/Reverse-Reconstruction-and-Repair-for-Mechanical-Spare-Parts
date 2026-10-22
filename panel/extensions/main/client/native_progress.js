export function progressFromProjection(projection){
 const value=projection?.status==='available'?projection.value:null;
 const tools=(value?.nodes||[]).filter(n=>n.kind==='tool');
 let runId=null;
 for(const tool of tools){try{const args=JSON.parse(tool.argsPreview||'{}');if(typeof args.run_id==='string')runId=args.run_id;}catch{}}
 const turns=value?.turns||[],last=tools.at(-1);
 return {available:!!value,sessionId:value?.sessionId||null,runId,toolCount:tools.length,
  completed:tools.filter(n=>n.status==='completed').length,failed:tools.filter(n=>n.status==='failed').length,
  running:tools.filter(n=>!['completed','failed','cancelled'].includes(n.status)).length,
  lastTool:last?.name||null,lastStatus:last?.status||null,turnStatus:turns.at(-1)?.status||null};
}
export function progressText(state,address){
 return ['机械备件逆向重建与修复 · 当前会话真实进度',state.runId||'等待任务输入',
  state.available?'工具 '+state.toolCount+' 次 · 完成 '+state.completed+' · 失败 '+state.failed+' · 运行 '+state.running:'当前未选择会话',
  state.lastTool?'最近工具：'+state.lastTool+' · '+state.lastStatus:'',
  state.turnStatus?'会话状态：'+state.turnStatus:'',
  '工具完成不代表设计通过；独立验收、云图与刀路：'+address].filter(Boolean).join('\n');
}
