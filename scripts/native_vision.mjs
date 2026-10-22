import {readFile,writeFile,appendFile,mkdir} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {createClient,memoryJournal} from '../runtime/sdk-bundle.mjs';
const root=process.env.REPAIRFORGE_ROOT,home=process.env.AGH_HOME,profile='local-dev';
if(!root||home!==root+'/.agh')throw Error('Independent home required');
const owner=JSON.parse(await readFile(home+'/data/daemon/owner.json','utf8'));
const client=createClient({transport:{kind:'unix',path:owner.socketPath},auth:{kind:'local'},journal:memoryJournal()});
await client.initialize();
let activeOut,activeSession,startedAt,activeEvents=[];
async function settle(r){for(let n=0;n<240;n++){const o=await client.packages.operation.get({profile,operationId:r.operationId});if(o.state==='completed')return o;if(['failed','cancelled','rolled-back'].includes(o.state))throw Error(JSON.stringify(o.error||o));await new Promise(r=>setTimeout(r,250));}throw Error('Operation timeout');}
const common=async()=>({profile,clientId:await client.clientId(),commandId:'repairforge-v3-'+randomUUID()});
try{
 if(process.argv[2]==='activate'){
  const id='@repairforge/vision-domain-v3',source={type:'file',ref:'file:./plugin'};
  const p=(await settle(await client.packages.inspect({...await common(),source}))).preview;
  if(!p||p.id!==id||p.blockers.length)throw Error(JSON.stringify(p));
  const installed=(await client.packages.list({profile})).packages.find(q=>q.id===id);
  if(!installed)await settle(await client.packages.install({...await common(),source,expectedIntegrity:p.integrity}));
  else if(installed.integrity!==p.integrity)await settle(await client.packages.update({...await common(),id,source,expectedIntegrity:p.integrity}));
  await settle(await client.packages.trust({...await common(),id,expectedIntegrity:p.integrity,capabilityHash:p.capabilityHash}));
  await settle(await client.packages.enable({...await common(),id}));
  const status=(await client.packages.list({profile})).packages.find(p=>p.id===id);
  await writeFile(root+'/reports/native-plugin-status.json',JSON.stringify(status,null,2)+'\n');
  console.log(JSON.stringify({id:status.id,actual:status.actual,version:status.version,trusted:status.trusted}));
 }else if(process.argv[2]==='run'){
  const rid=process.argv[3];if(!/^[A-Za-z0-9_-]{1,100}$/.test(rid))throw Error('INVALID_RUN_ID');
  const out=root+'/runs/'+rid;
  activeOut=out;
  const input=JSON.parse(await readFile(out+'/user_task.json','utf8'));
  const status=(await client.packages.list({profile})).packages.find(p=>p.id==='@repairforge/vision-domain-v3');
  const expected=JSON.parse(await readFile(root+'/plugin/package.json','utf8'));
  if(status?.actual!=='running'||status.version!==expected.version||!status.trusted)throw Error('DOMAIN_PLUGIN_NOT_READY');
  await client.workspace.add(out);
  const session=await client.session.new({cwd:out});
  activeSession=session.id;
  await session.setModel({slot:'primary',route:'repairforge-vision-v3',model:'mimo-v2.6-pro',thinking:'off'});
  await session.attach({filter:{acpUpdates:false}});
  await writeFile(out+'/session.json',JSON.stringify({session_id:session.id,run_id:rid,external_task_inputs:1,plugin_status:status},null,2)+'\n');
  const events=activeEvents;
  const collect=(async()=>{for await(const e of session.events()){events.push(e);await appendFile(out+'/native-events.jsonl',JSON.stringify(e)+'\n');if(e.type==='turn/end')break;}})();
  const content=[{type:'text',text:input.first_input},{type:'text',text:'附件来源与独立尺度：'+JSON.stringify(input.attachment_metadata)}];
  for(const name of input.initial_frames)content.push({type:'image',mimeType:name.endsWith('.png')?'image/png':'image/jpeg',data:(await readFile(root+'/inputs/'+input.case_id+'/images/'+name)).toString('base64')});
  const started=Date.now();startedAt=started;
  // Exactly one user prompt. No external corrective or continuation prompts.
  const result=await session.prompt(content);
  await Promise.race([collect,new Promise(r=>setTimeout(r,1000))]);
  const report={session_id:session.id,run_id:rid,result,elapsed_seconds:(Date.now()-started)/1000,event_count:events.length,tool_calls:events.filter(e=>e.type==='tool/call').map(e=>e.data),external_task_inputs:1,initial_image_count:input.initial_frames.length};
  await writeFile(out+'/native-report.json',JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({session_id:session.id,elapsed_seconds:report.elapsed_seconds,result,tool_calls:report.tool_calls.map(c=>c.name),external_task_inputs:1}));
 }else throw Error('activate|run RUN_ID');
}catch(e){
 if(activeOut)await writeFile(activeOut+'/native-report.json',JSON.stringify({session_id:activeSession,run_id:process.argv[3],result:{reason:'error',error_type:e.name,error:String(e)},elapsed_seconds:startedAt?(Date.now()-startedAt)/1000:null,tool_calls:activeEvents.filter(e=>e.type==='tool/call').map(e=>e.data),initial_image_count:3,external_task_inputs:1},null,2)+'\n');
 console.error(String(e));process.exitCode=1;
}finally{await client.close();}
