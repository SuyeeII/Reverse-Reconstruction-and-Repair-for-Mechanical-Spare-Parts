export function viewerAddress(location){
 const url=new URL(location.href),nativePort=Number(url.port);
 if(!Number.isInteger(nativePort)||nativePort<3||nativePort>65535)throw Error('Native UI port unavailable');
 url.port=String(nativePort-2);return url.origin;
}
export function relocateOwnedProgress(text,address){
 if(['机械备件逆向重建与修复 · 等待当前会话','机械备件逆向重建与修复 · 当前会话服务尚未就绪'].includes(text))return text+'\n结果与刀路：'+address;
 if(!text.startsWith('机械备件逆向重建与修复 ·')||!text.includes('结果与刀路：http://127.0.0.1:48905'))return text;
 return text.replace('结果与刀路：http://127.0.0.1:48905','结果与刀路：'+address);
}
