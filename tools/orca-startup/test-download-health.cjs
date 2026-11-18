'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),http=require('node:http');
const {downloadsActive,createDownloadKeepAlive}=require('./download-health.cjs');
const approved={status:'running',needsReconsent:false};
test('only active downloads touch the reviewed worker, at most once a minute',async()=>{
 let now=0,active=true,calls=0;
 const keep=createDownloadKeepAlive({clock:()=>now,check:async()=>active,client:{async call(method,args){
  calls++;assert.equal(method,'plugins.invokeCommand');assert.equal(args.commandId,'toolkit.open');assert.deepEqual(args.args,{openBrowser:false});return {ok:true};
 }}});
 await keep(approved);await keep(approved);assert.equal(calls,1);
 now+=60000;await keep(approved);assert.equal(calls,2);
 now+=60000;active=false;await keep(approved);assert.equal(calls,2);
});
test('disabled or unreviewed plugins are neither probed nor re-enabled',async()=>{
 const keep=createDownloadKeepAlive({check:async()=>{assert.fail('probe');},client:{call(){assert.fail('activation');}}});
 for(const p of [null,{status:'disabled'},{status:'pending'},{...approved,needsReconsent:true}])await keep(p);
});
test('HTTP activity probe uses local session auth and ignores paused/completed tasks',async()=>{
 let status='paused';const token='b'.repeat(64);
 const server=http.createServer((req,res)=>{
  if(req.url==='/')return res.end(`const token='${token}';`);
  assert.equal(req.url,'/api/downloads/jobs');assert.equal(req.headers['x-toolkit-token'],token);
  res.end(JSON.stringify({jobs:[{status}]}));
 });await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  for(const s of ['paused','complete','error','cancelled']){status=s;assert.equal(await downloadsActive(server.address().port),false);}
  for(const s of ['preparing','downloading','verifying']){status=s;assert.equal(await downloadsActive(server.address().port),true);}
 }finally{await new Promise(resolve=>server.close(resolve));}
});
