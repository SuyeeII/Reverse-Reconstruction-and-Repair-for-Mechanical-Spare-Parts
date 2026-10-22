export async function loadScene(file,fetcher=fetch){
 const response=await fetcher(file);
 if(response.status===404&&!file.endsWith('.gz'))return loadScene(file+'.gz',fetcher);
 if(!response.ok)throw new Error('结果文件读取失败：HTTP '+response.status);
 if(file.endsWith('.gz')){
  if(typeof DecompressionStream==='undefined')throw new Error('当前浏览器不支持压缩结果回放，请使用现代浏览器。');
  return new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).json();
 }
 return response.json();
}
