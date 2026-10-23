'use strict';
const fs=require('node:fs'),path=require('node:path');
const {validate:validateDownload}=require('./modules/downloads/settings.cjs');
const defaults=()=>({accounts:{enabled:true,environment:'',worktree:''},downloads:{enabled:true,environment:'',sshHost:'',sshUser:'',sshPort:22},gpu:{enabled:true}});
function validate(value){
 if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Expected settings object.');
 if(Object.keys(value).some(k=>!['accounts','downloads','gpu'].includes(k)))throw Error('Unknown settings section.');
 const result=defaults();
 for(const key of Object.keys(result)){
  const input=value[key]||{};
  if(typeof input!=='object'||Array.isArray(input)||Object.keys(input).some(k=>!(k in result[key])))throw Error('Unknown module setting.');
  for(const [name,data] of Object.entries(input)){
   if(name==='enabled'){if(typeof data!=='boolean')throw Error('enabled must be boolean.');}
   else if(name==='sshPort'){if(!Number.isInteger(data)||data<1||data>65535)throw Error('Invalid SSH port.');}
   else if(typeof data!=='string'||data.length>4096||/[\x00-\x1f]/.test(data))throw Error('Invalid setting text.');
   result[key][name]=typeof data==='string'?data.trim():data;
  }
 }
 const d=result.downloads;
 if(d.environment||d.sshHost||d.sshUser)validateDownload(d);
 const a=result.accounts;
 if(a.worktree&&!/^path:\//.test(a.worktree))throw Error('Remote worktree must start with path:/');
 return result;
}
function load(root,local){
 fs.mkdirSync(root,{recursive:true});const file=path.join(root,'settings.json');
 if(fs.existsSync(file))return validate(JSON.parse(fs.readFileSync(file,'utf8').replace(/^\uFEFF/,'')));
 const result=defaults(),legacy=path.join(local,'OrcaParallelDownloads','settings.json');
 if(fs.existsSync(legacy)){
  try{const d=validateDownload(JSON.parse(fs.readFileSync(legacy,'utf8').replace(/^\uFEFF/,'')));Object.assign(result.downloads,d);result.accounts.environment=d.environment;}catch{}
 }
 return result;
}
function save(root,value){const clean=validate(value),file=path.join(root,'settings.json');fs.mkdirSync(root,{recursive:true});fs.writeFileSync(file+'.tmp',JSON.stringify(clean,null,2));fs.renameSync(file+'.tmp',file);return clean;}
module.exports={defaults,validate,load,save};
