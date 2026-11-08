'use strict';
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),http=require('node:http');
// A private, lazily-started child process. Startup credentials stay on its pipe;
// the browser only sees the existing Toolkit session, not this child token.
class DeployControl {
 constructor(runtime,root,{python}={}){this.runtime=runtime;this.root=root;this.python=python;this.child=null;this.pending=null;this.endpoint=null;this.closed=false;}
 interpreter(){
  if(this.python)return this.python;
  const local=this.runtime.local;
  for(const config of [path.join(local,'OrcaDeploy','launcher.json'),path.join(local,'LocalGpuBridge','launcher.json')]){
   try{const value=JSON.parse(fs.readFileSync(config,'utf8').replace(/^\uFEFF/,''));const exe=value.python||value.pythonw?.replace(/pythonw\.exe$/i,'python.exe');if(exe&&fs.existsSync(exe))return exe;}catch{}
  }
  for(const exe of ['python.exe','python']){
   try{const version=cp.spawnSync(exe,['-c','import sys;print(sys.executable);assert sys.version_info>=(3,10)'],{encoding:'utf8',timeout:5000,windowsHide:true,env:this.runtime.childEnv});if(version.status===0)return version.stdout.trim();}catch{}
  }
  throw Error('部署中心需要 Python 3.10+。新机器可运行包含独立运行时的 Orca Deploy 安装包，不需要 Codex。');
 }
 async ensure(){
  if(this.closed)throw Error('安装助手已关闭。');if(this.endpoint)return this.endpoint;if(this.pending)return this.pending;
  this.pending=(async()=>{
   const script=path.join(__dirname,'modules','deploy-runtime','deploy.py');
   if(!fs.existsSync(script))throw Error('部署运行时未打包；先运行 scripts/build-toolkit-ui.cjs。');
   const child=cp.spawn(this.interpreter(),['-B',script,'--data-dir',path.join(this.root,'deploy'),'serve','--parent-stdio'],{env:this.runtime.childEnv,windowsHide:true,stdio:['pipe','pipe','pipe']});this.child=child;
   // Raw errors and dependency diagnostics never go to the browser or plugin logs.
   child.stderr.on('data',()=>{});
   const endpoint=await new Promise((resolve,reject)=>{
    let buffer='';const timeout=setTimeout(()=>{child.kill();reject(Error('安装助手启动超时。检查本机 Python 和安装包。'));},12000);
    const finish=(error,value)=>{clearTimeout(timeout);child.stdout.off('data',read);error?reject(error):resolve(value);};
    const read=chunk=>{buffer+=chunk.toString('utf8');if(buffer.length>4096)return finish(Error('安装助手启动响应无效。'));if(!buffer.includes('\n'))return;try{const v=JSON.parse(buffer.split('\n')[0]);if(!/^http:\/\/127\.0\.0\.1:\d+\/$/.test(v.url)||! /^[a-f0-9]{64}$/.test(v.token))throw Error();finish(null,v);}catch{finish(Error('安装助手未返回有效本机会话。'));}};
    child.stdout.on('data',read);child.once('error',()=>finish(Error('无法启动本机部署运行时。')));child.once('exit',()=>finish(Error('部署运行时已退出。')));
   });
   child.once('exit',()=>{this.endpoint=null;this.child=null;});child.stdout.on('data',()=>{});
   this.endpoint=endpoint;return endpoint;
  })();try{return await this.pending;}finally{this.pending=null;}
 }
 async request(route,body){
  if(!['/api/deploy/state','/api/deploy/create','/api/deploy/probe','/api/deploy/connect','/api/deploy/run','/api/deploy/get','/api/deploy/export','/api/deploy-local/choose-folder','/api/deploy-local/verify-client','/api/deploy-local/install','/api/deploy-local/gpu-install'].includes(route))throw Error('部署接口未开放。');
  const endpoint=await this.ensure(),url=new URL(route,endpoint.url),bytes=body===undefined?null:Buffer.from(JSON.stringify(body));
  return new Promise((resolve,reject)=>{
   const req=http.request(url,{method:bytes?'POST':'GET',timeout:65000,headers:{'X-Toolkit-Token':endpoint.token,Origin:endpoint.url.slice(0,-1),...(bytes?{'Content-Type':'application/json','Content-Length':bytes.length}:{})}},res=>{
    let text='',size=0;res.setEncoding('utf8');res.on('data',chunk=>{size+=Buffer.byteLength(chunk);if(size>12*1024*1024){res.destroy();reject(Error('部署响应超过大小限制。'));return;}text+=chunk;});res.on('error',()=>reject(Error('安装助手连接中断。先检查已有任务状态再重试。')));res.on('end',()=>{try{const value=JSON.parse(text);if(res.statusCode<200||res.statusCode>=300)throw Error(value.error||'部署请求未完成。');resolve(value);}catch(e){reject(e);}});
   });req.on('timeout',()=>{req.destroy();reject(Error('部署请求等待超时。请查询原任务，避免重复安装。'));});req.on('error',()=>reject(Error('本机安装助手不可达。刷新任务状态后继续。')));if(bytes)req.write(bytes);req.end();
  });
 }
 async close(){this.closed=true;if(this.child)this.child.stdin.end();if(this.pending)await this.pending.catch(()=>{});}
}
module.exports={DeployControl};
