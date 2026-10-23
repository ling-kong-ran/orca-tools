'use strict';
const path=require('node:path');
function validRemote(value){return typeof value==='string'&&value.startsWith('/')&&value.length<=4096&&!/[\x00-\x1f]/.test(value);}
class RemoteBrowser {
 constructor(runtime,options={}){this.runtime=runtime;this.clients=new Map();this.createClient=options.createClient||(environment=>require('./remote-runtime.cjs').createRemoteClient(runtime,environment));}
 async list(environment,{directory='',showHidden=false,query='',offset=0}={}){
  if(typeof environment!=='string'||!environment.trim())throw Error('Configure the remote Orca environment first.');
  if(directory!==''&&!validRemote(directory))throw Error('Use an absolute Linux directory path.');
  if(typeof showHidden!=='boolean'||typeof query!=='string'||query.length>200||!Number.isInteger(offset)||offset<0||offset>1000000)throw Error('Invalid remote browser options.');
  let client=this.clients.get(environment);
  if(!client){client=this.createClient(environment);if(!client.isRemote)throw Error('The selected Orca connection is not remote.');if(this.clients.size>=16)this.clients.clear();this.clients.set(environment,client);}
  let response;try{response=await client.call('files.browseServerDir',{path:directory});}catch{throw Error('Unable to list this remote directory. Check its path, permissions and the Orca connection.');}
  if(!response.ok||!response._meta?.runtimeId)throw Error('The remote directory request was not confirmed.');
  const value=response.result;
  if(value?.pathFlavor!=='posix'||!validRemote(value.resolvedPath)||!Array.isArray(value.entries))throw Error('The server did not return a supported Linux directory listing.');
  const current=path.posix.normalize(value.resolvedPath),needle=query.toLocaleLowerCase();
  const entries=value.entries.filter(e=>e&&typeof e.name==='string'&&e.name&&e.name!=='.'&&e.name!=='..'&&!e.name.includes('/')&&!/[\x00-\x1f]/.test(e.name)&&typeof e.isDirectory==='boolean')
   .filter(e=>(showHidden||!e.name.startsWith('.'))&&e.name.toLocaleLowerCase().includes(needle))
   .sort((a,b)=>Number(b.isDirectory)-Number(a.isDirectory)||a.name.localeCompare(b.name));
  const limit=200;
  return {directory:current,parent:current==='/'?null:path.posix.dirname(current),offset,total:entries.length,hasMore:offset+limit<entries.length,
   entries:entries.slice(offset,offset+limit).map(e=>({name:e.name,path:path.posix.join(current,e.name),isDirectory:e.isDirectory,isSymlink:e.isSymlink===true}))};
 }
}
module.exports={RemoteBrowser,validRemote};
