// Test harness for the download engine HTTP checks. Toolkit production routes live in ../../server.cjs.
'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {DownloadManager}=require('./engine.cjs');
const {windowsRuntime,launch}=require('./runtime.cjs');

async function startServer(options) {
  const manager=new DownloadManager(options),token=crypto.randomBytes(32).toString('hex');
  let port;
  const server=http.createServer(async(req,res)=>{
    function send(code,body,type='application/json; charset=utf-8'){
      const data=Buffer.isBuffer(body)?body:Buffer.from(JSON.stringify(body));
      res.writeHead(code,{'Content-Type':type,'Content-Length':data.length,'Cache-Control':'no-store',
        'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
        'Content-Security-Policy':`default-src 'none'; connect-src 'self'; script-src 'nonce-${token}'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`});res.end(data);
    }
    try{
      if(req.headers.host!==`127.0.0.1:${port}`)return send(403,{error:'Invalid host'});
      if(req.url==='/'&&req.method==='GET')return send(200,Buffer.from(fs.readFileSync(path.join(__dirname,'index.html'),'utf8').replaceAll('__TOKEN__',token)),'text/html; charset=utf-8');
      if(req.url==='/favicon.ico')return send(204,Buffer.alloc(0));
      if(req.headers['x-download-token']!==token)return send(403,{error:'Session changed. Reload this page.'});
      if(req.method==='GET'&&req.url==='/api/jobs')return send(200,{jobs:manager.list(),defaultFolder:options.defaultFolder,environment:options.environment});
      if(req.method!=='POST')return send(404,{error:'Not found'});
      if(req.headers.origin!==`http://127.0.0.1:${port}`)return send(403,{error:'Invalid origin'});
      if(req.headers['content-type']?.split(';')[0]!=='application/json')return send(415,{error:'Expected JSON'});
      let data='';for await(const part of req){data+=part.toString('utf8');if(Buffer.byteLength(data)>16384)throw Error('Request too large');}
      const body=JSON.parse(data);
      if(!body||typeof body!=='object'||Array.isArray(body))throw Error('Invalid request');
      if(req.url==='/api/jobs')return send(201,{job:await manager.create(body)});
      if(req.url==='/api/action')return send(200,{job:await manager.action(body.id,body.action)});
      if(req.url==='/api/pause-all'){await manager.pauseAll();return send(200,{ok:true});}
      if(req.url==='/api/open-folder'){
        const job=manager.jobs.get(body.id);if(!job)throw Error('Download not found');
        const runtime=options.runtime||windowsRuntime();
        await launch(runtime.explorer,[path.dirname(job.destination)],runtime.childEnv);
        return send(200,{ok:true});
      }
      return send(404,{error:'Not found'});
    }catch(error){if(!res.headersSent)send(400,{error:String(error.message).slice(0,500)});else res.destroy();}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(options.port??18770,'127.0.0.1',resolve);});
  port=server.address().port;
  return {manager,server,url:`http://127.0.0.1:${port}/`,async close(){await manager.close();await new Promise(resolve=>server.close(resolve));}};
}
module.exports={startServer};
