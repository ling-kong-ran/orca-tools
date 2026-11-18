'use strict';
const http=require('node:http');
function readLocal(port,route,headers={}){
 return new Promise((resolve,reject)=>{
  const req=http.get({host:'127.0.0.1',port,path:route,headers,timeout:2000},res=>{
   let body='';res.setEncoding('utf8');res.on('data',chunk=>{body+=chunk;if(body.length>2*1024*1024)req.destroy(Error('Response too large'));});
   res.on('error',reject);res.on('end',()=>res.statusCode===200?resolve(body):reject(Error('Toolkit unavailable')));
  });req.on('error',reject);req.on('timeout',()=>req.destroy(Error('Toolkit timeout')));
 });
}
async function downloadsActive(port=18774){
 const page=await readLocal(port,'/'),token=page.match(/const token='([a-f0-9]{64})'/)?.[1];
 if(!token)return false;
 const result=JSON.parse(await readLocal(port,'/api/downloads/jobs',{'X-Toolkit-Token':token}));
 return Array.isArray(result.jobs)&&result.jobs.some(job=>['preparing','downloading','verifying'].includes(job.status));
}
function createDownloadKeepAlive({client,check=downloadsActive,clock=Date.now}){
 let next=0;
 return async plugin=>{
  if(!plugin||plugin.needsReconsent||['pending','disabled'].includes(plugin.status))return;
  if(clock()<next)return;
  next=clock()+60000;
  if(!await check())return;
  // A host command counts as worker activity. Loopback HTTP traffic does not.
  // Never re-enable a disabled plugin or keep an idle download worker alive.
  const reply=await client.call('plugins.invokeCommand',{pluginKey:'local-tools.toolkit',commandId:'toolkit.open',args:{openBrowser:false}});
  if(!reply.ok)throw Error('Unable to keep the active download worker available');
 };
}
module.exports={downloadsActive,createDownloadKeepAlive};
