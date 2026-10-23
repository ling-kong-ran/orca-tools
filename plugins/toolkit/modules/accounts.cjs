'use strict';
const cp=require('node:child_process'),{promisify}=require('node:util');
const execFile=promisify(cp.execFile);
class Accounts {
 constructor(runtime){this.runtime=runtime;}
 async call(settings,args){
  const {stdout}=await execFile(this.runtime.cli,[...args,'--environment',settings.environment,'--json'],
   {env:this.runtime.childEnv,windowsHide:true,timeout:30000,maxBuffer:2*1024*1024});
  const response=JSON.parse(stdout);if(!response.ok||!response._meta?.runtimeId)throw Error('Remote Orca is unavailable. Check the selected environment.');return response.result;
 }
 async open(settings){
  if(!settings.environment)throw Error('Set the remote environment in Toolkit settings.');
  const url='http://127.0.0.1:18766/';
  const current=await this.call(settings,['tab','list']);const page=current.tabs?.find(p=>p.url===url);
  let browserPageId=page?.browserPageId;
  if(!browserPageId){
   let worktree=settings.worktree;
   if(!worktree){const {repos=[]}=await this.call(settings,['repo','list']);const repo=repos.find(r=>typeof r.path==='string'&&r.path.startsWith('/'));if(repo)worktree='path:'+repo.path;}
   if(!worktree)throw Error('Open a remote project or set its worktree in Toolkit settings.');
   const created=await this.call(settings,['tab','create','--worktree',worktree,'--url',url]);browserPageId=created.browserPageId;
  }
  if(!browserPageId)throw Error('Orca did not return a remote browser page.');
  await this.call(settings,['tab','switch','--page',browserPageId,'--focus']);
  return {opened:true,location:'remote-browser'};
 }
}
module.exports={Accounts};
