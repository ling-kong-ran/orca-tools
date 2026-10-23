'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {DirectoryPicker}=require('./directory-picker.cjs'),{startServer}=require('./server.cjs'),preferences=require('./download-preferences.cjs');
function fixture(){const root=fs.mkdtempSync(path.join(os.tmpdir(),'toolkit-folder-'));const selected=path.join(root,"中文 folder's name");fs.mkdirSync(selected);return {root,selected,clean:()=>fs.rmSync(root,{recursive:true,force:true})};}
test('native picker passes paths as encoded data and returns Unicode directory',async()=>{const f=fixture();try{
 const initial="C:\\User's files\\中文;$untrusted";let called=false;
 const picker=new DirectoryPicker({childEnv:{SystemRoot:'C:\\Windows',API_TOKEN:'not-forwarded'}},{platform:'win32',execute:async(exe,args,options)=>{
  called=true;assert.ok(exe.endsWith('powershell.exe'));assert.ok(args.includes('-STA'));assert.ok(args.includes('-File'));assert.ok(!args.join(' ').includes(initial));assert.equal(Buffer.from(options.env.ORCA_TOOLKIT_FOLDER_BASE64,'base64').toString('utf8'),initial);assert.equal(options.env.API_TOKEN,undefined);assert.equal(options.windowsHide,true);return {stdout:JSON.stringify({cancelled:false,path:f.selected})};
 }});
 assert.deepEqual(await picker.choose(initial),{cancelled:false,path:f.selected});assert.ok(called);
 }finally{f.clean();}});
test('cancel and overlapping dialog requests are handled without changing path',async()=>{
 let complete;const picker=new DirectoryPicker({childEnv:{}},{platform:'win32',execute:()=>new Promise(r=>{complete=r;})});
 const first=picker.choose('');await assert.rejects(picker.choose(''),/already open/);complete({stdout:'{"cancelled":true}'});assert.deepEqual(await first,{cancelled:true});assert.equal(picker.pending,null);
});
test('picker rejects invalid responses and preferences failures remain nonfatal',async()=>{const f=fixture();try{
 const picker=new DirectoryPicker({childEnv:{}},{platform:'win32',execute:async()=>({stdout:'{"cancelled":false,"path":"relative"}'})});await assert.rejects(picker.choose(''),/absolute folder/);
 const bad=path.join(f.root,'not-a-directory');fs.writeFileSync(bad,'x');assert.equal(preferences.rememberFolder(bad,f.selected),false);assert.equal(preferences.defaultFolder(bad,f.root),path.join(f.root,'Downloads','Orca'));
 }finally{f.clean();}});
test('HTTP directory picker requires local authorization and remembers selection across restart',async()=>{const f=fixture();let service;try{
 let cancelled=false,calls=0;
 const options={port:0,dataDir:path.join(f.root,'settings'),runtime:{home:f.root,local:f.root,childEnv:{}},
  directoryPicker:{async choose(){calls++;return cancelled?{cancelled:true}:{cancelled:false,path:f.selected};}},
  gpu:{async status(){return {online:false};}},createDownloads:()=>({list:()=>[],close:async()=>{}})};
 service=await startServer(options);
 async function session(){const html=await (await fetch(service.url)).text();const token=html.match(/const token='([a-f0-9]+)'/)[1];return {'X-Toolkit-Token':token,'Content-Type':'application/json',Origin:service.url.slice(0,-1)};}
 const headers=await session(),endpoint=service.url+'api/downloads/choose-folder';
 assert.equal((await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status,403);
 assert.equal((await fetch(endpoint,{method:'POST',headers:{...headers,Origin:'https://evil.invalid'},body:'{}'})).status,403);assert.equal(calls,0);
 const response=await fetch(endpoint,{method:'POST',headers,body:JSON.stringify({initialDirectory:''})});assert.equal(response.status,200);assert.equal((await response.json()).path,f.selected);
 cancelled=true;assert.deepEqual(await (await fetch(endpoint,{method:'POST',headers,body:'{}'})).json(),{cancelled:true});assert.equal(preferences.defaultFolder(options.dataDir,f.root),f.selected);
 assert.equal((await fetch(endpoint,{method:'POST',headers,body:'{"command":"arbitrary"}'})).status,400);
 await service.close();service=await startServer(options);assert.equal(preferences.defaultFolder(options.dataDir,f.root),f.selected);
 const page=await (await fetch(service.url+'downloads/')).text();assert.ok(page.includes('Choose download folder'));assert.ok(page.includes("'/api/downloads/choose-folder'"));
 }finally{if(service)await service.close();f.clean();}});
