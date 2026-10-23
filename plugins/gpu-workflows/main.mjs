import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';
import http from 'node:http';
import { spawn } from 'node:child_process';

const url = 'http://127.0.0.1:18773/';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function childEnvironment() {
  const home = os.homedir();
  const env = {...process.env, USERPROFILE:home, LOCALAPPDATA:process.env.LOCALAPPDATA||path.join(home,'AppData','Local'),
    SystemRoot:process.env.SystemRoot||'C:\\Windows'};
  for (const key of ['ELECTRON_RUN_AS_NODE','NODE_CHANNEL_FD','NODE_CHANNEL_SERIALIZATION_MODE','NODE_UNIQUE_ID']) delete env[key];
  return env;
}
function launch(executable,args,env) {
  return new Promise((resolve,reject) => {
    const child = spawn(executable,args,{env,windowsHide:true,stdio:'ignore',detached:true});
    child.once('error',reject);child.once('spawn',()=>{child.unref();resolve();});
  });
}
function available() {
  return new Promise(resolve => {
    const request = http.get(url,{timeout:1500},response=>{
      let body='';response.setEncoding('utf8');
      response.on('data',chunk=>{if(body.length<65536)body+=chunk;});
      response.on('end',()=>resolve(response.statusCode===200 && body.includes('<title>GPU Workflows</title>')));
    });
    request.on('error',()=>resolve(false));request.on('timeout',()=>{request.destroy();resolve(false);});
  });
}
export default async function activate(api) {
  api.commands.register('gpu-workflows.open',async(args={})=>{
    const env=childEnvironment();
    if (!await available()) {
      const root=path.join(env.LOCALAPPDATA,'LocalGpuBridge');
      const launchConfig=JSON.parse(fs.readFileSync(path.join(root,'launcher.json'),'utf8'));
      const python=launchConfig.pythonw;
      const script=path.join(root,'app','bridge.py'),config=path.join(root,'config.json');
      if (![python,script,config].every(file=>fs.existsSync(file))) throw Error('Local GPU Bridge is not installed on this computer.');
      await launch(python,[script,'--config',config],env);
      let ready=false;
      for(let attempt=0;attempt<15;attempt++){await pause(500);if(await available()){ready=true;break;}}
      if(!ready)throw Error('The workflow manager could not start. Check Tailscale and the local bridge log.');
    }
    if(args.openBrowser!==false)await launch(path.join(env.SystemRoot,'System32','rundll32.exe'),['url.dll,FileProtocolHandler',url],env);
    return {url,ready:true};
  });
  api.log('GPU Workflows is ready. Use GPU Workflows: Open Manager or Ctrl+Alt+G.');
}
