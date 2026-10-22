import {viewerAddress} from './portable_address.js';
import {progressFromProjection,progressText} from './native_progress.js';
import {fontData} from './font_data.js';
export async function apply(ctx){
 const face=new FontFace('RepairForgeUI',Uint8Array.from(atob(fontData),c=>c.charCodeAt(0)));
 await face.load();document.fonts.add(face);ctx.effect(()=>()=>document.fonts.delete(face));
 const address=viewerAddress(window.location);let disposed=false,off,lastText='',revision=0;
 const render=projection=>{if(disposed)return;const text=progressText(progressFromProjection(projection),address);
  if(text===lastText)return;lastText=text;if(typeof off==='function')off();
  off=ctx.slots.register('ui:sidebar',()=>text,{priority:-2});
 };
 const refresh=async()=>{const serial=++revision;try{const p=await ctx.session.projection.read();if(serial===revision)render(p);}catch{if(serial===revision)render({status:'unavailable'});}};
 const unsubscribe=ctx.session.projection.subscribe(render),sessionOff=ctx.session.subscribe(()=>{void refresh();});
 void refresh();const timer=setInterval(refresh,3000);
 ctx.effect(()=>()=>{disposed=true;revision++;clearInterval(timer);unsubscribe();sessionOff();if(typeof off==='function')off();});
}
