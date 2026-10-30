const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {DownloadManager,Semaphore,safeName,chunkSize}=require('./engine.cjs');
const {startServer}=require('./server.cjs');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
test('Orca filtered worker environment resolves CLI and Windows tools',async()=>{
 const {windowsRuntime,launch}=require('./runtime.cjs');
 const allowed=['PATH','HOME','USERPROFILE','LANG','LC_ALL','LC_CTYPE','TZ','TMPDIR','TEMP','TMP','SYSTEMROOT','SYSTEMDRIVE','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS'];
 const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>allowed.some(name=>name.toUpperCase()===key.toUpperCase())));
 env.ELECTRON_RUN_AS_NODE='1';env.NODE_CHANNEL_FD='99';
 const runtime=windowsRuntime(env);
 assert.ok(!env.LOCALAPPDATA&&!env.APPDATA);
 for(const executable of [runtime.cli,runtime.ssh,runtime.keygen,runtime.browser,runtime.explorer])assert.ok(fs.existsSync(executable),executable);
 assert.ok(path.isAbsolute(runtime.childEnv.LOCALAPPDATA));assert.ok(path.isAbsolute(runtime.childEnv.APPDATA));
 assert.equal(runtime.childEnv.ELECTRON_RUN_AS_NODE,undefined);assert.equal(runtime.childEnv.NODE_CHANNEL_FD,undefined);
 const execFile=require('node:util').promisify(require('node:child_process').execFile);
 const cli=await execFile(runtime.cli,['--version'],{env:runtime.childEnv,windowsHide:true,timeout:20000});
 assert.match(cli.stdout,/\d+\.\d+\.\d+/);
 const ssh=await execFile(runtime.ssh,['-V'],{env:runtime.childEnv,windowsHide:true,timeout:10000});
 assert.match(ssh.stderr,/OpenSSH/);
 await assert.rejects(launch(path.join(os.tmpdir(),'nonexistent-orca-download-executable.exe'),[],runtime.childEnv));
});
async function settled(manager,id){for(let i=0;i<2000;i++){if(!manager.runs.has(id))return manager.jobs.get(id);await sleep(10);}throw Error('Test timeout');}
function fixture(length=12*1024*1024){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'orca-download-test-')),source=crypto.randomBytes(length);
 const fake={reads:[],active:0,max:0,failOnce:false,delay:0,cleaned:0,
  async prepare(){return {size:source.length,sha256:crypto.createHash('sha256').update(source).digest('hex'),fingerprint:[1,2,length,3]};},
  async read(job,offset,length,signal,onData){this.active++;this.max=Math.max(this.max,this.active);this.reads.push(offset);
   try{for(let n=0;n<length;n+=65536){if(signal.aborted)throw Error('Paused');onData(source.subarray(offset+n,offset+Math.min(n+65536,length)),n);if(this.failOnce){this.failOnce=false;throw Error('Simulated interrupted connection');}await sleep(this.delay);}}
   finally{this.active--;}
  },async cleanup(){this.cleaned++;}
 };
 const options={dataDir:path.join(root,'state'),transport:fake,defaultFolder:path.join(root,'downloads'),environment:'Test'};
 return {root,source,fake,options,manager:new DownloadManager(options),folder:options.defaultFolder};
}
test('parallel writes survive a dropped range and verify the original bytes',async()=>{
 const f=fixture();f.fake.failOnce=true;
 try{const j=await f.manager.create({source:'/remote/sample.bin',folder:f.folder,concurrency:4});const job=await settled(f.manager,j.id);
  assert.equal(job.status,'complete');assert.ok(job.verified);assert.ok(f.fake.max>1&&f.fake.max<=4);assert.ok(job.retries>=1);
  assert.deepEqual(fs.readFileSync(job.destination),f.source);assert.equal(f.fake.cleaned,1);
 }finally{await f.manager.close();fs.rmSync(f.root,{recursive:true,force:true});}
});
test('small images use all requested streams and preserve their bytes',async()=>{
 const f=fixture(4852825);
 try{const j=await f.manager.create({source:'/remote/image.png',folder:f.folder,concurrency:12});const job=await settled(f.manager,j.id);
  assert.equal(job.status,'complete');assert.equal(f.fake.max,12);assert.equal(f.fake.reads.length,12);assert.ok(job.chunk<4*1024*1024);assert.deepEqual(fs.readFileSync(job.destination),f.source);
 }finally{await f.manager.close();fs.rmSync(f.root,{recursive:true,force:true});}
 assert.equal(chunkSize(4096,12),256*1024);assert.equal(chunkSize(1024*1024*1024,16),4*1024*1024);
});
test('legacy saved ranges keep their original 4 MB offsets after resume',async()=>{
 const f=fixture(4852825);let restored;
 try{const id='a'.repeat(32),chunk=4*1024*1024,partial=path.join(f.root,'legacy.part'),destination=path.join(f.root,'legacy.png');
  const bytes=Buffer.alloc(f.source.length);f.source.copy(bytes,chunk,chunk);fs.writeFileSync(partial,bytes);
  const meta=await f.fake.prepare();fs.writeFileSync(path.join(f.options.dataDir,'jobs',id+'.json'),JSON.stringify({id,source:'/remote/legacy.png',name:'legacy.png',destination,partial,concurrency:12,chunk,size:meta.size,sha256:meta.sha256,fingerprint:meta.fingerprint,status:'paused',done:[1],retries:0}));
  restored=new DownloadManager(f.options);await restored.action(id,'resume');const job=await settled(restored,id);
  assert.equal(job.status,'complete');assert.equal(job.chunk,chunk);assert.deepEqual(f.fake.reads,[0]);assert.deepEqual(fs.readFileSync(destination),f.source);
 }finally{await restored?.close();await f.manager.close();fs.rmSync(f.root,{recursive:true,force:true});}
});
test('pause, reopen and resume retain finished ranges',async()=>{
 const f=fixture(20*1024*1024);f.fake.delay=2;
 try{const j=await f.manager.create({source:'/remote/resume.bin',folder:f.folder,concurrency:2});
  while(f.manager.jobs.get(j.id).done.length<1)await sleep(10);
  await f.manager.action(j.id,'pause');const before=[...f.manager.jobs.get(j.id).done];assert.ok(before.length>0&&before.length<5);
  await f.manager.close();const restored=new DownloadManager(f.options);assert.equal(restored.jobs.get(j.id).status,'paused');
  const readCount=f.fake.reads.length;await restored.action(j.id,'resume');const done=await settled(restored,j.id);
  assert.equal(done.status,'complete');assert.deepEqual(fs.readFileSync(done.destination),f.source);
  for(const i of before)assert.ok(!f.fake.reads.slice(readCount).includes(i*done.chunk));await restored.close();
 }finally{await f.manager.close();fs.rmSync(f.root,{recursive:true,force:true});}
});
test('a file appearing at the destination is never overwritten',async()=>{
 const f=fixture(1024*1024);f.fake.delay=2;
 try{const j=await f.manager.create({source:'/remote/collision.bin',folder:f.folder,concurrency:1});fs.writeFileSync(j.destination,'KEEP');
  const done=await settled(f.manager,j.id);assert.equal(done.status,'error');assert.equal(fs.readFileSync(j.destination,'utf8'),'KEEP');assert.ok(fs.existsSync(done.partial));
 }finally{await f.manager.close();fs.rmSync(f.root,{recursive:true,force:true});}
});
test('empty files complete and Windows reserved names are sanitized',async()=>{
 const f=fixture(0);
 try{const j=await f.manager.create({source:'/remote/empty.bin',folder:f.folder});assert.equal((await settled(f.manager,j.id)).status,'complete');assert.equal(fs.statSync(j.destination).size,0);
  assert.ok(safeName('/a/CON.txt').startsWith('download_'));assert.ok(!safeName('/a/a:b.mp4').includes(':'));
 }finally{await f.manager.close();fs.rmSync(f.root,{recursive:true,force:true});}
});
test('HTTP requires session token, same origin and local Host',async()=>{
 const f=fixture(4096),service=await startServer({...f.options,port:0});
 try{const page=await fetch(service.url);const html=await page.text();const token=html.match(/const token='([a-f0-9]+)'/)[1];
  assert.equal((await fetch(service.url+'api/jobs')).status,403);
  const headers={'X-Download-Token':token,'Content-Type':'application/json','Origin':service.url.slice(0,-1)};
  const badHost=await new Promise((resolve,reject)=>{const r=require('node:http').get(service.url+'api/jobs',{headers:{...headers,Host:'foreign.invalid'}},response=>{response.resume();resolve(response.statusCode);});r.on('error',reject);});
  assert.equal(badHost,403);
  assert.equal((await fetch(service.url+'api/jobs',{method:'POST',headers:{...headers,Origin:'https://foreign.invalid'},body:'{}'})).status,403);
  const response=await fetch(service.url+'api/jobs',{method:'POST',headers,body:JSON.stringify({source:'/remote/http.bin',folder:f.folder,concurrency:2})});
  assert.equal(response.status,201);const body=await response.json();await settled(service.manager,body.job.id);
  const list=await (await fetch(service.url+'api/jobs',{headers})).json();assert.equal(list.jobs[0].status,'complete');assert.ok(!JSON.stringify(list).includes('publicKey'));
 }finally{await service.close();await f.manager.close();fs.rmSync(f.root,{recursive:true,force:true});}
});
test('global connection budget releases cancelled waiters',async()=>{
 const semaphore=new Semaphore(2),controller=new AbortController();let active=0,max=0;
 const operation=()=>semaphore.run(controller.signal,async()=>{active++;max=Math.max(max,active);await sleep(20);active--;});
 const first=operation(),second=operation(),queued=operation();controller.abort();
 await Promise.allSettled([first,second,queued]);assert.ok(max<=2);assert.equal(semaphore.active,0);assert.equal(semaphore.waiters.length,0);
 const next=new AbortController();await semaphore.run(next.signal,async()=>{});assert.equal(semaphore.active,0);
});
