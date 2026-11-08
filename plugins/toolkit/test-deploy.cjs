'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {startServer}=require('./server.cjs'),{DeployControl}=require('./deploy-control.cjs'),{compose}=require('./compose-ui.cjs');
test('deployment is integrated into the same shell without another manager page',()=>{
 const html=compose();for(const fragment of ['data-view="deploy"','id="deploy-module"',"toolkitModules.deploy",'/api/deploy/'])assert.ok(html.includes(fragment));
 assert.ok(!html.includes('<iframe'));assert.ok(!html.includes('window.open('));
});
test('deployment proxy routes retain toolkit origin and session guards',async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'orca-deploy-test-')),calls=[];
 const service=await startServer({port:0,dataDir:folder,runtime:{local:folder,home:folder},gpu:{status:async()=>({online:false})},
  deployment:{request:async(route,body)=>{calls.push({route,body});return {plans:[]};},close:async()=>{}}});
 try{
  const html=await(await fetch(service.url)).text(),token=html.match(/const token='([a-f0-9]+)'/)[1];
  assert.equal((await fetch(service.url+'api/deploy/state')).status,403);
  const headers={'X-Toolkit-Token':token,'Content-Type':'application/json',Origin:service.url.slice(0,-1)};
  assert.equal((await fetch(service.url+'api/deploy/state',{headers})).status,200);
  assert.equal((await fetch(service.url+'api/deploy/create',{method:'POST',headers:{...headers,Origin:'https://foreign.invalid'},body:'{}'})).status,403);
  assert.equal(calls.length,1);
  assert.equal((await fetch(service.url+'api/deploy/create',{method:'POST',headers,body:'{"plan":{}}'})).status,200);
  assert.equal(calls[1].route,'/api/deploy/create');
 }finally{await service.close();fs.rmSync(folder,{recursive:true,force:true});}
});
test('adapter refuses arbitrary helper routes before starting a child',async()=>{
 const adapter=new DeployControl({local:'unused'},'unused');
 await assert.rejects(adapter.request('/api/exec',{command:'bad'}),/未开放/);
 await adapter.close();
});
test('portable runtime pointer accepts Windows PowerShell UTF-8 BOM',()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'orca-deploy-pointer-'));
 try{
  fs.mkdirSync(path.join(folder,'OrcaDeploy'));
  fs.writeFileSync(path.join(folder,'OrcaDeploy','launcher.json'),'\uFEFF'+JSON.stringify({python:process.execPath}));
  assert.equal(new DeployControl({local:folder},folder).interpreter(),process.execPath);
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
});
