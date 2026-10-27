'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const runtime=require('./modules/downloads/runtime.cjs'),hub=require('./server.cjs');

test('activation starts the complete GPU bridge without opening a browser',async()=>{
 const previousRuntime=runtime.windowsRuntime,previousServer=hub.startServer,previousLaunch=runtime.launch;
 let starts=0,browserLaunches=0;const logs=[];
 runtime.windowsRuntime=()=>({local:'fixture'});
 runtime.launch=async()=>{browserLaunches++;};
 const service={url:'http://127.0.0.1:0/',controller:{settings:{gpu:{enabled:true}},gpu:{async open(){starts++;}}},async close(){}};
 hub.startServer=async()=>service;
 try{
  const plugin=await import('./main.mjs');
  await plugin.default({commands:{register(){}},log(value){logs.push(value);}});
  assert.equal(starts,1);assert.equal(browserLaunches,0);
  assert.ok(logs.some(line=>line.includes('ready')));
  await plugin.deactivate();
 }finally{runtime.windowsRuntime=previousRuntime;hub.startServer=previousServer;runtime.launch=previousLaunch;}
});

test('disabled GPU module does not start services and startup failure keeps Toolkit usable',async()=>{
 const previousRuntime=runtime.windowsRuntime,previousServer=hub.startServer;
 let starts=0;const logs=[];const commands=[];
 runtime.windowsRuntime=()=>({local:'fixture'});
 const service={url:'http://127.0.0.1:0/',controller:{settings:{gpu:{enabled:false}},gpu:{async open(){starts++;throw Error('not installed');}}},async close(){}};
 hub.startServer=async()=>service;
 try{
  const plugin=await import('./main.mjs');const api={commands:{register(name){commands.push(name);}},log(value){logs.push(value);}};
  await plugin.default(api);assert.equal(starts,0);await plugin.deactivate();
  service.controller.settings.gpu.enabled=true;await plugin.default(api);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(starts,1);assert.ok(commands.includes('toolkit.open'));
  assert.ok(logs.some(line=>line.includes('GPU bridge startup failed')));
  await plugin.deactivate();
 }finally{runtime.windowsRuntime=previousRuntime;hub.startServer=previousServer;}
});
