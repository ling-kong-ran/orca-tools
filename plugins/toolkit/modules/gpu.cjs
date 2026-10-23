'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const {launch}=require('./downloads/runtime.cjs');
const url='http://127.0.0.1:18773/';
function available(){return new Promise(resolve=>{
 const request=http.get(url,{timeout:1500},response=>{let body='';response.setEncoding('utf8');response.on('data',v=>{if(body.length<65536)body+=v;});response.on('end',()=>resolve(response.statusCode===200&&body.includes('<title>GPU Workflows</title>')));});
 request.on('error',()=>resolve(false));request.on('timeout',()=>{request.destroy();resolve(false);});
});}
class Gpu {
 constructor(runtime){this.runtime=runtime;this.pending=null;}
 async status(){return {online:await available()};}
 async open(){
  if(this.pending)return this.pending;
  this.pending=this.ensure();try{return await this.pending;}finally{this.pending=null;}
 }
 async ensure(){
  if(await available())return {url,ready:true};
  const root=path.join(this.runtime.local,'LocalGpuBridge'),launcher=path.join(root,'launcher.json');
  if(!fs.existsSync(launcher))throw Error('Install Local GPU Bridge first. Its launcher.json is missing.');
  const {pythonw}=JSON.parse(fs.readFileSync(launcher,'utf8'));
  const script=path.join(root,'app','bridge.py'),config=path.join(root,'config.json');
  if(typeof pythonw!=='string'||![pythonw,script,config].every(p=>fs.existsSync(p)))throw Error('Local GPU Bridge installation is incomplete.');
  await launch(pythonw,[script,'--config',config],this.runtime.childEnv);
  for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,500));if(await available())return {url,ready:true};}
  throw Error('GPU service is starting or unavailable. Check the local bridge log.');
 }
}
module.exports={Gpu};
