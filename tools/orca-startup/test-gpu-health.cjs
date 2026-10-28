'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http');
const {createGpuRecovery,configuration,managerReady,tcpReady}=require('./gpu-health.cjs');
const approved={pluginKey:'local-tools.toolkit',status:'running',needsReconsent:false};
function fixture(){
 const local=fs.mkdtempSync(path.join(os.tmpdir(),'orca-recovery-'));
 fs.mkdirSync(path.join(local,'LocalGpuBridge'));fs.mkdirSync(path.join(local,'OrcaTools'));
 fs.writeFileSync(path.join(local,'LocalGpuBridge','config.json'),JSON.stringify({listen:'127.0.0.1',port:18772,admin_port:18773}));
 return {local,clean(){assert.ok(path.resolve(local).startsWith(path.resolve(os.tmpdir())+path.sep));fs.rmSync(local,{recursive:true,force:true});}};
}
test('bridge failure is recovered even when the Toolkit hub is already online',async()=>{
 const f=fixture();try{let online=false,calls=0;
 const recover=createGpuRecovery({local:f.local,check:async()=>online,client:{async call(method,args){calls++;assert.equal(method,'plugins.invokeCommand');assert.equal(args.commandId,'toolkit.gpu');assert.equal(args.args.openBrowser,false);online=true;return {ok:true};}}});
 assert.deepEqual(await recover(approved),{status:'recovered'});assert.equal(calls,1);
 assert.deepEqual(await recover(approved),{status:'online'});assert.equal(calls,1);
 }finally{f.clean();}
});
test('pending consent and disabled modules never launch or probe GPU services',async()=>{
 const f=fixture();try{let calls=0,probes=0;const recover=createGpuRecovery({local:f.local,check:async()=>{probes++;return false;},client:{async call(){calls++;return {ok:true};}}});
 for(const plugin of [{...approved,status:'pending'},{...approved,needsReconsent:true},{...approved,status:'disabled'}])assert.equal((await recover(plugin)).status,'awaiting-approval');
 fs.writeFileSync(path.join(f.local,'OrcaTools','settings.json'),JSON.stringify({gpu:{enabled:false}}));
 assert.equal((await recover(approved)).status,'disabled-or-not-installed');assert.equal(calls,0);assert.equal(probes,0);
 }finally{f.clean();}
});
test('failed startup retries use a cooldown without submitting render tasks',async()=>{
 const f=fixture();try{let now=1000,calls=0;const recover=createGpuRecovery({local:f.local,clock:()=>now,check:async()=>false,client:{async call(method,args){calls++;assert.equal(args.commandId,'toolkit.gpu');return {ok:false};}}});
 assert.equal((await recover(approved)).status,'retrying');assert.equal((await recover(approved)).status,'starting');assert.equal(calls,1);
 now+=60000;await recover(approved);assert.equal(calls,2);
 }finally{f.clean();}
});
test('concurrent checks share one recovery attempt',async()=>{
 const f=fixture();try{let finish,calls=0;const recover=createGpuRecovery({local:f.local,check:async()=>false,client:{call(){calls++;return new Promise(resolve=>{finish=resolve;});}}});
 const first=recover(approved);await new Promise(resolve=>setImmediate(resolve));const second=recover(approved);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls,1);finish({ok:true});assert.deepEqual(await Promise.all([first,second]),[{status:'starting'},{status:'starting'}]);
 }finally{f.clean();}
});
test('health checks reject public endpoints and require both manager content and a live listener',async()=>{
 const f=fixture();let server;try{
 fs.writeFileSync(path.join(f.local,'LocalGpuBridge','config.json'),JSON.stringify({listen:'8.8.8.8',port:18772}));assert.throws(()=>configuration(f.local),/private/);
 server=http.createServer((req,res)=>res.end('<title>GPU Workflows</title>'));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;
 assert.equal(await managerReady(port),true);assert.equal(await tcpReady('127.0.0.1',port),true);
 await new Promise(resolve=>server.close(resolve));server=null;
 assert.equal(await tcpReady('127.0.0.1',port),false);assert.equal(await managerReady(port),false);
 }finally{if(server)await new Promise(resolve=>server.close(resolve));f.clean();}
});
