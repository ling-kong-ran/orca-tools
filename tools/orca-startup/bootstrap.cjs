'use strict';
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),os=require('node:os'),http=require('node:http');
const root=path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local'),'OrcaLocalTools');
fs.mkdirSync(root,{recursive:true});
const lock=path.join(root,'bootstrap.pid');
try{const pid=Number(fs.readFileSync(lock,'utf8'));if(pid>0){try{process.kill(pid,0);process.exit(0);}catch{}}}catch{}
fs.writeFileSync(lock,String(process.pid));
process.on('exit',()=>{try{if(fs.readFileSync(lock,'utf8')===String(process.pid))fs.unlinkSync(lock);}catch{}});
const reviewed={
 'local-tools.gpu-workflows':{command:'gpu-workflows.open',port:18773},
 'local-tools.parallel-download':{command:'parallel-download.open',port:18770}
};
let client,lastState='',activated=new Set();
function log(state){const text=JSON.stringify(state);if(text===lastState)return;lastState=text;fs.appendFileSync(path.join(root,'startup.log'),new Date().toISOString()+' '+text+'\n');}
function healthy(port){return new Promise(resolve=>{const request=http.get('http://127.0.0.1:'+port+'/',{timeout:1500},response=>{response.resume();resolve(response.statusCode===200);});request.on('error',()=>resolve(false));request.on('timeout',()=>{request.destroy();resolve(false);});});}
async function tick(){
 const exe=path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local'),'Programs','orca','Orca.exe');
 const script="$p=Get-CimInstance Win32_Process -Filter \"Name='Orca.exe'\" -ErrorAction SilentlyContinue; if(@($p | Where-Object {$_.ExecutablePath -eq '"+exe.replaceAll("'","''")+"'}).Count -gt 0){exit 0}else{exit 1}";
 const app=cp.spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true,timeout:8000,stdio:'ignore'});
 if(app.status!==0){activated.clear();return;}
 if(!client){const {RuntimeClient}=require(path.join(path.dirname(exe),'resources','app.asar.unpacked','out','cli','runtime-client.js'));client=new RuntimeClient(undefined,10000);}
 const response=await client.call('plugins.list',{});if(!response.ok)throw Error('Orca plugin service is unavailable');
 const runtime=response._meta?.runtimeId||'local';const states=[];
 for(const [key,review] of Object.entries(reviewed)){
  const plugin=response.result.find(p=>p.pluginKey===key);
  if(!plugin){states.push({key,status:'available after Orca reload'});continue;}
  const mark=runtime+':'+key;
  if(activated.has(mark)&&await healthy(review.port)){states.push({key,status:'activated'});continue;}
  if(plugin.needsReconsent||['disabled','pending'].includes(plugin.status)){states.push({key,status:'review and enable in Orca'});continue;}
  const enabled=await client.call('plugins.setEnabled',{pluginKey:key,enabled:true});if(!enabled.ok)throw Error('Orca could not enable '+key);
  const started=await client.call('plugins.invokeCommand',{pluginKey:key,commandId:review.command,args:{openBrowser:false}});
  if(!started.ok)throw Error('Orca could not activate '+key);
  activated.add(mark);states.push({key,status:'activated'});
 }
 log({plugins:states});
}
(async()=>{for(;;){try{await tick();}catch(e){log({error:String(e.message).slice(0,300)});}if(process.argv.includes('--once'))break;await new Promise(r=>setTimeout(r,15000));}})();
