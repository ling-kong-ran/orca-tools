import path from 'node:path';
import runtimeModule from './modules/downloads/runtime.cjs';
import hub from './server.cjs';

let service;
export default async function activate(api) {
  const runtime=runtimeModule.windowsRuntime();
  service=await hub.startServer({runtime,dataDir:path.join(runtime.local,'OrcaTools'),
    async onComplete(job){try{await api.host.call('notifications.show',{title:'Download complete',body:job.name+' · SHA-256 verified'});}catch{}}});
  const open=async(url,args={})=>{
    if(args.openBrowser!==false)await runtimeModule.launch(runtime.browser,['url.dll,FileProtocolHandler',url],runtime.childEnv);
    return {url,ready:true};
  };
  api.commands.register('toolkit.open',args=>open(service.url,args));
  api.commands.register('toolkit.downloads',args=>open(service.url+'#downloads',args));
  api.commands.register('toolkit.accounts',args=>open(service.url+'#accounts',args));
  api.commands.register('toolkit.gpu',async(args={})=>{await service.controller.openGpu();return open(service.url+'#workflows',args);});
  api.commands.register('toolkit.pause-downloads',async()=>{await service.controller.downloads?.pauseAll();return {ok:true};});
  api.log('Orca Toolkit is ready. Ctrl+Alt+T opens the control center.');
  // open() starts both ComfyUI and the authenticated GPU bridge; it does not
  // open a browser. Starting only ComfyUI leaves every remote MCP offline.
  if(service.controller.settings.gpu.enabled)service.controller.gpu.open().catch(()=>api.log('GPU bridge startup failed. Check the local GPU bridge log.'));
}
export async function deactivate(){if(service){await service.close();service=null;}}
