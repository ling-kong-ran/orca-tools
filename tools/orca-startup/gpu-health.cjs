'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),net=require('node:net');

function tcpReady(host,port){return new Promise(resolve=>{
 const socket=net.createConnection({host,port});let done=false;
 const finish=value=>{if(done)return;done=true;socket.destroy();resolve(value);};
 socket.setTimeout(1500);socket.once('connect',()=>finish(true));socket.once('timeout',()=>finish(false));socket.once('error',()=>finish(false));
});}
function managerReady(port){return new Promise(resolve=>{
 let settled=false;const finish=value=>{if(settled)return;settled=true;resolve(value);};
 const request=http.get({host:'127.0.0.1',port,path:'/',timeout:1500},response=>{
  let body='';response.setEncoding('utf8');response.on('data',chunk=>{if(body.length<65536)body+=chunk;});
  response.on('end',()=>finish(response.statusCode===200&&body.includes('<title>GPU Workflows</title>')));response.on('error',()=>finish(false));
 });request.on('error',()=>finish(false));request.on('timeout',()=>{request.destroy();finish(false);});
});}
function configuration(local){
 const file=path.join(local,'LocalGpuBridge','config.json');if(!fs.existsSync(file))return null;
 const settings=path.join(local,'OrcaTools','settings.json');
 if(fs.existsSync(settings)&&JSON.parse(fs.readFileSync(settings,'utf8')).gpu?.enabled===false)return null;
 const value=JSON.parse(fs.readFileSync(file,'utf8'));
 const octets=typeof value.listen==='string'?value.listen.split('.').map(Number):[];
 if(net.isIP(value.listen)!==4||!(value.listen==='127.0.0.1'||octets[0]===100&&octets[1]>=64&&octets[1]<=127))throw Error('GPU health checks require a private local bridge address.');
 for(const port of [value.port,value.admin_port??18773])if(!Number.isInteger(port)||port<1||port>65535)throw Error('Invalid GPU health-check port.');
 return {host:value.listen,port:value.port,adminPort:value.admin_port??18773};
}
function createGpuRecovery({local,client,clock=Date.now,cooldownMs=60000,check}={}){
 let pending=null,lastAttempt=-Infinity;
 return async plugin=>{
  if(plugin.needsReconsent||['disabled','pending'].includes(plugin.status))return {status:'awaiting-approval'};
  let config;try{config=configuration(local);}catch{return {status:'configuration-error'};}
  if(!config)return {status:'disabled-or-not-installed'};
  const healthy=check||(()=>Promise.all([managerReady(config.adminPort),tcpReady(config.host,config.port)]).then(results=>results.every(Boolean)));
  if(await healthy())return {status:'online'};
  if(pending)return pending;
  if(clock()-lastAttempt<cooldownMs)return {status:'starting'};
  lastAttempt=clock();
  pending=(async()=>{
   try{
    const result=await client.call('plugins.invokeCommand',{pluginKey:plugin.pluginKey,commandId:'toolkit.gpu',args:{openBrowser:false}});
    if(!result.ok)return {status:'retrying'};
    return {status:await healthy()?'recovered':'starting'};
   }catch{return {status:'retrying'};}
  })();
  try{return await pending;}finally{pending=null;}
 };
}
module.exports={configuration,createGpuRecovery,managerReady,tcpReady};
