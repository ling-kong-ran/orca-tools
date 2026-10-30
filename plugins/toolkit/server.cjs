'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {Controller}=require('./controller.cjs'),{launch}=require('./modules/downloads/runtime.cjs');
const {DirectoryPicker}=require('./directory-picker.cjs'),preferences=require('./download-preferences.cjs');
const {RemoteBrowser,validRemote}=require('./remote-browser.cjs');
const {GpuAdmin}=require('./gpu-admin.cjs'),{compose}=require('./compose-ui.cjs');
async function startServer(options){
 const controller=new Controller(options);await controller.initialize();const token=crypto.randomBytes(32).toString('hex');let port;
 const picker=options.directoryPicker||new DirectoryPicker(options.runtime);
 const remoteBrowser=options.remoteBrowser||new RemoteBrowser(options.runtime);
 const gpuAdmin=options.gpuAdmin||new GpuAdmin();
 const server=http.createServer(async(req,res)=>{
  const origin='http://127.0.0.1:'+port;
  const send=(code,body,type='application/json; charset=utf-8')=>{const bytes=Buffer.from(typeof body==='string'?body:JSON.stringify(body));res.writeHead(code,{'Content-Type':type,'Content-Length':bytes.length,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':`default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-${token}'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`});res.end(bytes);};
  try{
   if(req.headers.host!==`127.0.0.1:${port}`)return send(403,{error:'Invalid Host.'});
   if(req.method==='GET'&&req.url==='/favicon.ico')return send(204,'');
   if(req.method==='GET'&&['/','/downloads/','/accounts/'].includes(req.url)){
    const html=compose(req.url==='/accounts/'?'accounts':req.url==='/downloads/'?'downloads':'overview');
    return send(200,html.replaceAll('__TOKEN__',token),'text/html; charset=utf-8');
   }
   if(req.headers['x-toolkit-token']!==token&&req.headers['x-download-token']!==token)return send(403,{error:'Session changed. Reload this page.'});
   if(req.method==='GET'&&req.url==='/api/accounts')return send(200,await controller.accountState());
   if(req.method==='GET'&&req.url==='/api/status')return send(200,await controller.status());
   if(req.method==='GET'&&['/api/gpu/native','/api/gpu/workflows'].includes(req.url)){
    if(!controller.settings.gpu.enabled)throw Error('GPU module is disabled.');
    return send(200,await gpuAdmin.request(req.url.replace('/api/gpu/','/api/')));
   }
   if(req.method==='GET'&&req.url==='/api/downloads/jobs')return send(200,{jobs:controller.requireDownloads().list(),defaultFolder:preferences.defaultFolder(options.dataDir,options.runtime.home),remoteLocation:preferences.remoteLocation(options.dataDir,controller.settings.downloads.environment)});
   if(req.method!=='POST')return send(404,{error:'Not found.'});
   if(req.headers.origin!==origin)return send(403,{error:'Invalid Origin.'});
   if(req.headers['content-type']?.split(';')[0]!=='application/json')return send(415,{error:'Expected JSON.'});
   let size=0;const limit=req.url==='/api/gpu/import'?4*1024*1024:16384;const chunks=[];for await(const chunk of req){size+=chunk.length;if(size>limit)throw Error('Request too large.');chunks.push(chunk);}
   const body=JSON.parse(Buffer.concat(chunks).toString('utf8'));if(!body||typeof body!=='object'||Array.isArray(body))throw Error('Expected an object.');
   if(req.url==='/api/settings')return send(200,await controller.update(body));
   if(req.url==='/api/accounts/open')return send(200,await controller.openAccounts());
   if(req.url==='/api/accounts/refresh'){if(Object.keys(body).length)throw Error('Unexpected refresh option.');return send(200,await controller.accountState(true));}
   if(req.url==='/api/accounts/select')return send(200,await controller.selectAccount(body));
   if(req.url==='/api/accounts/disable')return send(200,await controller.setAccountDisabled(body));
   if(req.url==='/api/gpu/open')return send(200,await controller.openGpu());
   if(req.url.startsWith('/api/gpu/')){
    if(!controller.settings.gpu.enabled)throw Error('GPU module is disabled.');
    return send(200,await gpuAdmin.request(req.url.replace('/api/gpu/','/api/'),body));
   }
   if(req.url==='/api/downloads/remote-browse'){
    controller.requireDownloads();
    if(Object.keys(body).some(k=>!['directory','showHidden','query','offset'].includes(k)))throw Error('Unexpected remote browser option.');
    const environment=controller.settings.downloads.environment;
    const result=await remoteBrowser.list(environment,{...body,directory:body.directory??preferences.remoteLocation(options.dataDir,environment).directory});
    if(controller.settings.downloads.environment!==environment)throw Error('Remote connection changed. Reopen the file browser.');
    preferences.rememberRemote(options.dataDir,environment,{directory:result.directory});
    return send(200,result);
   }
   if(req.url==='/api/downloads/remote-location'){
    controller.requireDownloads();
    if(Object.keys(body).length!==1||!Object.hasOwn(body,'source')||typeof body.source!=='string'||(body.source!==''&&!validRemote(body.source)))throw Error('Use an absolute remote file path.');
    const changes={source:body.source};if(body.source)changes.directory=path.posix.dirname(body.source);
    const saved=preferences.rememberRemote(options.dataDir,controller.settings.downloads.environment,changes);
    return send(200,{saved});
   }
   if(req.url==='/api/downloads/choose-folder'){
    if(!controller.settings.downloads.enabled)throw Error('Downloads module is disabled.');
    if(Object.keys(body).some(k=>k!=='initialDirectory'))throw Error('Unexpected folder selection setting.');
    const result=await picker.choose(body.initialDirectory??preferences.defaultFolder(options.dataDir,options.runtime.home));
    if(!result.cancelled&&!preferences.rememberFolder(options.dataDir,result.path))result.warning='Folder selected, but the preference could not be saved.';
    return send(200,result);
   }
   if(req.url==='/api/downloads/jobs'){
    const job=await controller.requireDownloads().create(body);preferences.rememberFolder(options.dataDir,body.folder);
    preferences.rememberRemote(options.dataDir,controller.settings.downloads.environment,{source:body.source,directory:path.posix.dirname(body.source)});return send(201,{job});
   }
   if(req.url==='/api/downloads/action')return send(200,{job:await controller.requireDownloads().action(body.id,body.action)});
   if(req.url==='/api/downloads/pause-all'){await controller.requireDownloads().pauseAll();return send(200,{ok:true});}
   if(req.url==='/api/downloads/open-folder'){
    const job=controller.requireDownloads().jobs.get(body.id);if(!job)throw Error('Download not found.');
    await launch(options.runtime.explorer,[path.dirname(job.destination)],options.runtime.childEnv);return send(200,{ok:true});
   }
   return send(404,{error:'Not found.'});
  }catch(e){if(!res.headersSent)send(400,{error:String(e.message).slice(0,500)});else res.destroy();}
 });
 try{await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(options.port??18774,'127.0.0.1',resolve);});}catch(e){await controller.close();throw e;}
 port=server.address().port;return {url:`http://127.0.0.1:${port}/`,controller,async close(){picker.close?.();await controller.close();await new Promise(resolve=>server.close(resolve));}};
}
module.exports={startServer};
