'use strict';
const fs=require('node:fs'),path=require('node:path');
const settings=require('./settings.cjs'),{DownloadManager}=require('./modules/downloads/engine.cjs');
const {validate:validateDownload}=require('./modules/downloads/settings.cjs');
const {Accounts}=require('./modules/accounts.cjs'),{Gpu}=require('./modules/gpu.cjs');
class Controller {
 constructor(options){
  this.options=options;this.runtime=options.runtime;this.root=options.dataDir;this.downloads=null;this.downloadError='';this.settingsError='';
  this.accounts=options.accounts||new Accounts(this.runtime);this.gpu=options.gpu||new Gpu(this.runtime);this.loading=null;
  try{this.settings=settings.load(this.root,this.runtime.local);}catch{this.settings=settings.defaults();this.settingsError='Settings could not be loaded. Save valid settings to repair them.';}
 }
 async initialize(){await this.configureDownloads();}
 async configureDownloads(){
  if(this.downloads){await this.downloads.close();this.downloads=null;}
  this.downloadError='';if(!this.settings.downloads.enabled)return;
  try{
   const config=validateDownload(this.settings.downloads);
   const create=this.options.createDownloads||(opts=>new DownloadManager(opts));
   this.downloads=create({dataDir:path.join(this.runtime.local,'OrcaParallelDownloads'),cli:this.runtime.cli,runtime:this.runtime,...config,
    defaultFolder:path.join(this.runtime.home,'Downloads','Orca'),onComplete:this.options.onComplete});
  }catch(e){this.downloadError=String(e.message);}
 }
 async update(value){
  if(this.loading)throw Error('Settings update is in progress.');
  const next=settings.validate(value);
  this.loading=(async()=>{
   const changed=JSON.stringify(next.downloads)!==JSON.stringify(this.settings.downloads);
   // Never silently move a live/resumable task to another server.
   const old=this.settings.downloads;
   const changedTarget=['environment','sshHost','sshUser','sshPort'].some(k=>old[k]!==next.downloads[k]);
   if(changedTarget){
    const folder=path.join(this.runtime.local,'OrcaParallelDownloads','jobs');
    const jobs=this.downloads?.list()||[];
    if(fs.existsSync(folder))for(const name of fs.readdirSync(folder)){
     if(!/^[a-f0-9]{32}\.json$/.test(name))continue;
     try{jobs.push(JSON.parse(fs.readFileSync(path.join(folder,name),'utf8')));}catch{throw Error('A saved download could not be read. Repair it before changing the target.');}
    }
    if(jobs.some(j=>!['complete','cancelled'].includes(j.status)||j.cleanupWarning))throw Error('Finish or cancel pending downloads and clear temporary access before changing the remote target.');
   }
   this.settings=settings.save(this.root,next);this.settingsError='';if(changed)await this.configureDownloads();
  })();
  try{await this.loading;}finally{this.loading=null;}
  return this.status();
 }
 async status(){
  let gpu={online:false};try{gpu=await this.gpu.status();}catch{}
  return {settings:this.settings,error:this.settingsError,modules:{
   accounts:{enabled:this.settings.accounts.enabled,status:!this.settings.accounts.enabled?'disabled':this.settings.accounts.environment?'configured':'needs-setup'},
   downloads:{enabled:this.settings.downloads.enabled,status:!this.settings.downloads.enabled?'disabled':this.downloads?'ready':'needs-setup',error:this.downloadError,jobs:this.downloads?.list().length||0},
   gpu:{enabled:this.settings.gpu.enabled,status:!this.settings.gpu.enabled?'disabled':gpu.online?'ready':'offline'}
  }};
 }
 requireDownloads(){if(!this.downloads||!this.settings.downloads.enabled)throw Error(this.downloadError||'Downloads module is disabled.');return this.downloads;}
 requireAccounts(){if(!this.settings.accounts.enabled)throw Error('Accounts module is disabled.');return this.settings.accounts;}
 async openAccounts(){this.requireAccounts();return {opened:true,url:'/accounts/'};}
 async accountState(refreshUsage=false){const settings=this.requireAccounts();const state=await this.accounts.list(settings,refreshUsage);if(this.settings.accounts!==settings)throw Error('Remote connection changed. Refresh accounts.');return state;}
 async selectAccount(body){const settings=this.requireAccounts();return this.accounts.select(settings,body,()=>this.settings.accounts===settings&&settings.enabled);}
 async openGpu(){if(!this.settings.gpu.enabled)throw Error('GPU module is disabled.');return this.gpu.open();}
 async close(){if(this.loading)await this.loading.catch(()=>{});if(this.downloads)await this.downloads.close();}
}
module.exports={Controller};
