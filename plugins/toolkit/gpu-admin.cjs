'use strict';
const http=require('node:http');
const {projectTypes}=require('./project-types.cjs');
const GET=new Set(['/api/native','/api/workflows']);
const POST=new Set(['/api/native/project','/api/native/stop-blender','/api/native/setup','/api/native/git','/api/native/unity-start','/api/native/unity-stop','/api/import']);
class GpuAdmin {
 constructor(){this.token=null;}
 exchange(route,body,token){return new Promise((resolve,reject)=>{
  const bytes=body===undefined?null:Buffer.from(JSON.stringify(body));
  const req=http.request({hostname:'127.0.0.1',port:18773,path:route,method:bytes?'POST':'GET',timeout:65000,
   headers:{...(token?{'X-Admin-Token':token}:{}),...(bytes?{'Content-Type':'application/json','Content-Length':bytes.length,Origin:'http://127.0.0.1:18773'}:{})}},res=>{
   const chunks=[];let size=0;res.on('data',chunk=>{size+=chunk.length;if(size>8*1024*1024){res.destroy(Error('GPU response is too large.'));return;}chunks.push(chunk);});
   res.on('error',reject);res.on('end',()=>resolve({status:res.statusCode,text:Buffer.concat(chunks).toString('utf8')}));
  });req.on('error',()=>reject(Error('GPU bridge is unavailable. Use Connect GPU in the toolbar.')));req.on('timeout',()=>{req.destroy();reject(Error('GPU request timed out. Check task status before retrying.'));});if(bytes)req.write(bytes);req.end();
 });}
 async request(route,body){
  if(!(body===undefined?GET:POST).has(route))throw Error('GPU management route is not exposed.');
  if(!this.token){const page=await this.exchange('/');this.token=page.text.match(/const token='([a-f0-9]{64})'/)?.[1];if(page.status!==200||!this.token)throw Error('GPU management session is unavailable.');}
  const reply=await this.exchange(route,body,this.token);
  if(reply.status===403){this.token=null;throw Error('GPU session changed. Refresh this view before retrying.');}
  let data;try{data=JSON.parse(reply.text);}catch{throw Error('GPU bridge returned an invalid response.');}
  if(reply.status!==200&&reply.status!==201)throw Error(data.error||'GPU request failed.');
  if(route==='/api/native'&&Array.isArray(data.projects))data.projects=data.projects.map(p=>({...p,project_types:projectTypes(p)}));
  return data;
 }
}
module.exports={GpuAdmin};
