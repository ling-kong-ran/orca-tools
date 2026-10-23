'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {startServer}=require('./server.cjs'),{Controller}=require('./controller.cjs'),settings=require('./settings.cjs');
function fixture(){const root=fs.mkdtempSync(path.join(os.tmpdir(),'orca-toolkit-'));const runtime={local:root,home:root,cli:'unused',childEnv:{}};
 const fake={rows:[],closed:0,jobs:new Map(),list(){return [...this.rows];},async close(){this.closed++;},async pauseAll(){this.paused=true;},async create(v){this.rows.push({id:'a',...v});return this.rows.at(-1);},async action(id,action){return {id,action};}};
 const options={dataDir:path.join(root,'OrcaTools'),runtime,port:0,createDownloads:()=>fake,gpu:{async status(){return {online:true};},async open(){return {url:'http://127.0.0.1:18773/',ready:true};}},accounts:{async open(v){return {opened:true,environment:v.environment};}}};
 return {root,options,fake,clean:()=>fs.rmSync(root,{recursive:true,force:true})};}
test('one failing/unconfigured module does not prevent Toolkit startup',async()=>{const f=fixture();const s=await startServer(f.options);try{const state=await s.controller.status();assert.equal(state.modules.downloads.status,'needs-setup');assert.equal(state.modules.gpu.status,'ready');assert.equal(state.modules.accounts.status,'needs-setup');}finally{await s.close();f.clean();}});
test('legacy download settings migrate without importing credentials',async()=>{const f=fixture();try{const old=path.join(f.root,'OrcaParallelDownloads');fs.mkdirSync(old);fs.writeFileSync(path.join(old,'settings.json'),JSON.stringify({environment:'Server',sshHost:'100.64.0.20',sshUser:'worker',sshPort:22,token:'not-copied'}));const c=new Controller(f.options);await c.initialize();assert.equal(c.settings.downloads.sshUser,'worker');assert.equal(c.settings.accounts.environment,'Server');assert.equal(c.settings.downloads.token,undefined);assert.ok(c.downloads);await c.close();}finally{f.clean();}});
test('settings reject public targets and unknown credential fields',()=>{assert.throws(()=>settings.validate({gpu:{token:'x'}}));assert.throws(()=>settings.validate({accounts:{worktree:'/missing-prefix'}}));assert.throws(()=>settings.validate({downloads:{environment:'s',sshHost:'8.8.8.8',sshUser:'worker'}}));});
test('target change is blocked for persisted tasks even with module disabled',async()=>{const f=fixture();try{const c=new Controller(f.options);const folder=path.join(f.root,'OrcaParallelDownloads','jobs');fs.mkdirSync(folder,{recursive:true});fs.writeFileSync(path.join(folder,'a'.repeat(32)+'.json'),JSON.stringify({status:'paused'}));const next=settings.defaults();next.downloads={enabled:false,environment:'Server',sshHost:'100.64.0.20',sshUser:'worker',sshPort:22};await assert.rejects(c.update(next),/pending downloads/);}finally{f.clean();}});
test('shared server authenticates actions, persists settings and serves scoped downloads',async()=>{const f=fixture();const s=await startServer(f.options);try{
 const html=await (await fetch(s.url)).text();assert.ok(html.includes('Orca Toolkit'));const token=html.match(/const token='([a-f0-9]+)'/)[1];
 const headers={'X-Toolkit-Token':token,'Content-Type':'application/json',Origin:s.url.slice(0,-1)};
 assert.equal((await fetch(s.url+'api/status')).status,403);
 const bad=await new Promise((resolve,reject)=>{const q=require('node:http').get(s.url,{headers:{Host:'evil.invalid'}},r=>{r.resume();resolve(r.statusCode);});q.on('error',reject);});assert.equal(bad,403);
 assert.equal((await fetch(s.url+'api/settings',{method:'POST',headers:{...headers,Origin:'https://evil.invalid'},body:'{}'})).status,403);
 const value=settings.defaults();value.accounts.environment='Server';value.downloads={enabled:true,environment:'Server',sshHost:'100.64.0.20',sshUser:'worker',sshPort:22};
 const saved=await fetch(s.url+'api/settings',{method:'POST',headers,body:JSON.stringify(value)});assert.equal(saved.status,200);assert.equal((await saved.json()).modules.downloads.status,'ready');assert.ok(fs.existsSync(path.join(f.options.dataDir,'settings.json')));
 const opened=await fetch(s.url+'api/accounts/open',{method:'POST',headers,body:'{}'});assert.equal((await opened.json()).opened,true);
 const dl=await (await fetch(s.url+'downloads/')).text();assert.ok(dl.includes("'/api/downloads/jobs'"));assert.ok(!dl.includes('__TOKEN__'));
 const job=await fetch(s.url+'api/downloads/jobs',{method:'POST',headers,body:JSON.stringify({source:'/a',folder:'local'})});assert.equal(job.status,201);
 const paused=await fetch(s.url+'api/downloads/pause-all',{method:'POST',headers,body:'{}'});assert.equal(paused.status,200);assert.ok(f.fake.paused);
 const gpu=await fetch(s.url+'api/gpu/open',{method:'POST',headers,body:'{}'});assert.equal((await gpu.json()).url,'http://127.0.0.1:18773/');
 value.downloads.enabled=false;value.accounts.enabled=false;await s.controller.update(value);assert.ok(f.fake.closed);await assert.rejects(s.controller.openAccounts(),/disabled/);
 }finally{await s.close();f.clean();}});
