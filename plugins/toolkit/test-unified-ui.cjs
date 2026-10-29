'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),vm=require('node:vm');
const {compose}=require('./compose-ui.cjs'),{GpuAdmin}=require('./gpu-admin.cjs'),{startServer}=require('./server.cjs');
test('all views share one shell with isolated modules and no nested pages',()=>{
 const html=compose();assert.ok(!html.includes('<iframe'));assert.ok(!html.includes('window.open('));
 for(const name of ['overview','accounts','downloads','projects','workflows','settings'])assert.ok(html.includes('data-view="'+name+'"'));
 assert.ok(html.includes("'/api/gpu/native'"));assert.ok(html.includes("'/api/downloads/jobs'"));
 new vm.Script(html.match(/<script nonce="[^"]+">([\s\S]*)<\/script>/)[1]);
 assert.equal(fs.readFileSync(path.join(__dirname,'modules/gpu-panel.html'),'utf8'),fs.readFileSync(path.join(__dirname,'../../services/local-gpu-bridge/admin.html'),'utf8'));
});
test('GPU adapter only calls fixed routes and never exposes the upstream token',async()=>{
 const g=new GpuAdmin(),calls=[];g.exchange=async(route,body,token)=>{calls.push({route,body,token});return route==='/'?{status:200,text:"const token='"+'a'.repeat(64)+"'"}:{status:200,text:'{"projects":[]}'};};
 await assert.rejects(g.request('/api/config'),/not exposed/);assert.equal(calls.length,0);
 assert.deepEqual(await g.request('/api/native'),{projects:[]});assert.equal(calls[1].token,'a'.repeat(64));
 g.exchange=async()=>({status:403,text:'{}'});await assert.rejects(g.request('/api/native/git',{operation:'pull'}),/session changed/);assert.equal(g.token,null);
});
test('unified GPU routes enforce session Origin and module access',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'toolkit-unified-')),calls=[];
 const s=await startServer({port:0,dataDir:root,runtime:{local:root,home:root},gpu:{status:async()=>({online:true})},
  gpuAdmin:{async request(route,body){calls.push({route,body});return {projects:[]};}}});
 try{
  const html=await(await fetch(s.url)).text(),token=html.match(/const token='([a-f0-9]+)'/)[1],headers={'X-Toolkit-Token':token,Origin:s.url.slice(0,-1),'Content-Type':'application/json'};
  assert.equal((await fetch(s.url+'api/gpu/native')).status,403);
  assert.equal((await fetch(s.url+'api/gpu/native',{headers})).status,200);assert.equal(calls[0].route,'/api/native');
  assert.equal((await fetch(s.url+'api/gpu/native/project',{method:'POST',headers:{...headers,Origin:'https://foreign.invalid'},body:'{}'})).status,403);
  assert.equal(calls.length,1);
  assert.equal((await fetch(s.url+'api/gpu/native/project',{method:'POST',headers,body:'{"id":"game"}'})).status,200);assert.equal(calls[1].route,'/api/native/project');
  s.controller.settings.gpu.enabled=false;
  assert.equal((await fetch(s.url+'api/gpu/native',{headers})).status,400);assert.equal(calls.length,2);
 }finally{await s.close();fs.rmSync(root,{recursive:true,force:true});}
});
