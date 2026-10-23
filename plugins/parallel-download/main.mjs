import path from 'node:path';
import fs from 'node:fs';
import settingsModule from './settings.cjs';
import serverModule from './server.cjs';
import runtimeModule from './runtime.cjs';

let service;
export default async function activate(api) {
  const runtime=runtimeModule.windowsRuntime();
  const dataDir=path.join(runtime.local,'OrcaParallelDownloads');
  const configPath=path.join(dataDir,'settings.json');
  if(!fs.existsSync(configPath))throw Error('Configure Parallel Downloads settings.json first; see the deployment guide.');
  const settings=settingsModule.validate(JSON.parse(fs.readFileSync(configPath,'utf8')));
  service=await serverModule.startServer({dataDir,cli:runtime.cli,runtime,...settings,
    defaultFolder:path.join(runtime.home,'Downloads','Orca'),
    async onComplete(job){await api.host.call('notifications.show',{title:'Download complete',body:job.name+' · SHA-256 verified'});}});
  api.commands.register('parallel-download.open',async(args={})=>{
    if(args.openBrowser!==false)await runtimeModule.launch(runtime.browser,['url.dll,FileProtocolHandler',service.url],runtime.childEnv);
    return {url:service.url};
  });
  api.commands.register('parallel-download.pause-all',async()=>{await service.manager.pauseAll();return {ok:true};});
  api.log('Parallel Downloads is ready. Use Parallel Downloads: Open Manager.');
}
export async function deactivate(){if(service){await service.close();service=null;}}
