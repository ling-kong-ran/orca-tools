'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {RemoteBrowser}=require('./remote-browser.cjs'),preferences=require('./download-preferences.cjs'),{startServer}=require('./server.cjs');
test('remote browser uses a read-only RPC, filters hidden entries and sorts folders first',async()=>{
 const calls=[];const browser=new RemoteBrowser({}, {createClient:()=>({isRemote:true,async call(method,params){calls.push({method,params});return {ok:true,_meta:{runtimeId:'remote'},result:{pathFlavor:'posix',resolvedPath:'/home/worker',entries:[{name:'file.mp4',isDirectory:false},{name:'中文目录',isDirectory:true},{name:'.private',isDirectory:false},{name:'../bad',isDirectory:false}]}};}})});
 const value=await browser.list('Server',{directory:'/home/worker'});assert.equal(value.entries.length,2);assert.equal(value.entries[0].isDirectory,true);assert.equal(value.entries[1].path,'/home/worker/file.mp4');assert.deepEqual(calls,[{method:'files.browseServerDir',params:{path:'/home/worker'}}]);assert.equal(value.parent,'/home');
 const hidden=await browser.list('Server',{showHidden:true,query:'.private'});assert.equal(hidden.entries[0].name,'.private');
 await assert.rejects(browser.list('Server',{directory:'relative'}),/absolute/);await assert.rejects(browser.list('Server',{offset:-1}),/options/);
});
test('large remote directories paginate and root has no parent',async()=>{
 const entries=Array.from({length:205},(_,i)=>({name:'file-'+String(i).padStart(3,'0'),isDirectory:false}));
 const browser=new RemoteBrowser({}, {createClient:()=>({isRemote:true,async call(){return {ok:true,_meta:{runtimeId:'remote'},result:{resolvedPath:'/',pathFlavor:'posix',entries}};}})});
 const first=await browser.list('s');assert.equal(first.entries.length,200);assert.equal(first.hasMore,true);assert.equal(first.parent,null);
 const last=await browser.list('s',{offset:200});assert.equal(last.entries.length,5);assert.equal(last.hasMore,false);
});
test('browser refuses local fallback and does not return sensitive connection errors',async()=>{
 const local=new RemoteBrowser({}, {createClient:()=>({isRemote:false})});await assert.rejects(local.list('s'),/not remote/);
 const failed=new RemoteBrowser({}, {createClient:()=>({isRemote:true,async call(){throw Error('private pairing credential');}})});await assert.rejects(failed.list('s'),e=>!e.message.includes('credential')&&e.message.includes('Unable to list'));
});
test('local folder, remote source and directory preferences merge and remain server-specific',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'toolkit-address-'));try{
  const folder=path.join(root,'saved');assert.ok(preferences.rememberFolder(root,folder));
  assert.ok(preferences.rememberRemote(root,'one',{source:'/a/file.mp4',directory:'/a'}));
  assert.ok(preferences.rememberRemote(root,'two',{source:'/b/file.mp4',directory:'/b'}));
  assert.ok(preferences.rememberFolder(root,path.join(root,'new')));
  assert.deepEqual(preferences.remoteLocation(root,'one'),{source:'/a/file.mp4',directory:'/a'});
  assert.deepEqual(preferences.remoteLocation(root,'two'),{source:'/b/file.mp4',directory:'/b'});
  assert.equal(preferences.defaultFolder(root,root),path.join(root,'new'));
  assert.equal(preferences.rememberRemote(root,'one',{source:'relative'}),false);
  assert.ok(preferences.rememberRemote(root,'__proto__',{source:'/safe',directory:'/'}));assert.equal({}.source,undefined);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('authenticated UI restores manual remote addresses and browsed directories after restart',async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'toolkit-remote-http-'));let service;const options={port:0,dataDir:path.join(root,'settings'),runtime:{home:root,local:root,childEnv:{}},
  createDownloads:()=>({list:()=>[],close:async()=>{}}),gpu:{async status(){return {online:false};}},remoteBrowser:{async list(environment,{directory}){assert.equal(environment,'Server');return {directory:directory||'/home/worker',parent:'/',entries:[],offset:0,total:0,hasMore:false};}}};
 try{
  fs.mkdirSync(options.dataDir,{recursive:true});fs.writeFileSync(path.join(options.dataDir,'settings.json'),JSON.stringify({downloads:{enabled:true,environment:'Server',sshHost:'100.64.0.20',sshUser:'worker',sshPort:22}}));
  service=await startServer(options);
  async function headers(){const html=await (await fetch(service.url)).text();return {'X-Toolkit-Token':html.match(/const token='([a-f0-9]+)'/)[1],'Content-Type':'application/json',Origin:service.url.slice(0,-1)};}
  let h=await headers();const post=(route,body)=>fetch(service.url+'api/downloads/'+route,{method:'POST',headers:h,body:JSON.stringify(body)});
  assert.equal((await fetch(service.url+'api/downloads/remote-browse',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status,403);
  assert.equal((await post('remote-location',{source:'/home/worker/out/video.mp4'})).status,200);
  assert.equal((await post('remote-location',{source:'../invalid'})).status,400);
  assert.equal((await post('remote-browse',{directory:'/home/worker/other'})).status,200);
  assert.equal((await post('remote-browse',{command:'arbitrary'})).status,400);
  await service.close();service=await startServer(options);h=await headers();
  const value=await (await fetch(service.url+'api/downloads/jobs',{headers:h})).json();assert.deepEqual(value.remoteLocation,{source:'/home/worker/out/video.mp4',directory:'/home/worker/other'});
  const page=await (await fetch(service.url+'downloads/')).text();assert.ok(page.includes('Browse remote files'));assert.ok(page.includes("'/api/downloads/remote-browse'"));
 }finally{if(service)await service.close();fs.rmSync(root,{recursive:true,force:true});}
});
