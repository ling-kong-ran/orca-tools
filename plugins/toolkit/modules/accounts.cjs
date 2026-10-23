'use strict';
const {createRemoteClient}=require('../remote-runtime.cjs');
function maskedEmail(value){if(typeof value!=='string')return '***';const match=value.match(/^([^@\s]+)@([^@\s]+)$/);return match?match[1][0]+'***@'+match[2]:'***';}
function timestamp(value){if(typeof value==='number'&&Number.isFinite(value))return value;if(typeof value==='string'&&/^\d{4}-\d\d-\d\dT/.test(value)&&Number.isFinite(Date.parse(value)))return new Date(value).toISOString();return null;}
function safeUsage(result,id){
 const limits=result.rateLimits||{};let usage;
 if(id===result.claude.activeAccountId){const candidate=limits.claude;if(['managed:'+id,'profile:'+id].includes(candidate?.usageMetadata?.authProvenance))usage=candidate;}
 else usage=limits.inactiveClaudeAccounts?.find(a=>a.accountId===id)?.rateLimits;
 if(!usage)return null;
 const clean={updatedAt:timestamp(usage.updatedAt)};
 for(const key of ['session','weekly']){const w=usage[key];clean[key]=w?{usedPercent:typeof w.usedPercent==='number'&&Number.isFinite(w.usedPercent)?Math.max(0,Math.min(100,w.usedPercent)):null,resetsAt:timestamp(w.resetsAt)}:null;}
 return clean;
}
function publicState(result){
 if(!result?.claude||!Array.isArray(result.claude.accounts))throw Error('The remote account response is unavailable.');
 const active=result.claude.activeAccountId;
 return {activeAccountId:typeof active==='string'?active:null,accounts:result.claude.accounts.filter(a=>typeof a.id==='string').map(a=>({id:a.id,email:maskedEmail(a.email),current:a.id===active,needsSignIn:a.needsSignIn===true,usage:safeUsage(result,a.id)}))};
}
class Accounts {
 constructor(runtime,options={}){this.runtime=runtime;this.createClient=options.createClient||(env=>createRemoteClient(runtime,env));this.clients=new Map();this.switching=false;}
 async call(settings,method,params){
  if(!settings.environment)throw Error('Set the remote environment in Toolkit settings.');
  let client=this.clients.get(settings.environment);
  try{if(!client){client=this.createClient(settings.environment);if(!client.isRemote)throw Error();if(this.clients.size>=16)this.clients.clear();this.clients.set(settings.environment,client);}const r=await client.call(method,params);if(!r.ok||!r._meta?.runtimeId)throw Error();return r.result;}
  catch{throw Error('Unable to reach remote accounts. Check the Orca connection and refresh.');}
 }
 async list(settings,refreshUsage=false){return publicState(await this.call(settings,'accounts.list',{refreshUsage}));}
 async select(settings,body,isCurrent=()=>true){
  if(Object.keys(body).some(k=>!['accountId','expectedActiveAccountId'].includes(k))||typeof body.accountId!=='string'||body.accountId.length>200||!(typeof body.expectedActiveAccountId==='string'||body.expectedActiveAccountId===null))throw Error('Invalid account selection.');
  if(this.switching)throw Error('An account switch is in progress. Refresh shortly.');
  this.switching=true;
  try{
   const state=await this.list(settings);const account=state.accounts.find(a=>a.id===body.accountId);
   if(!isCurrent())throw Error('Remote connection changed. Refresh before switching.');
   if(!account)throw Error('Account not found. Refresh to try again.');
   if(account.needsSignIn)throw Error('Sign in again on the remote host to use this account.');
   if(account.current)return state;
   if(body.expectedActiveAccountId!==state.activeAccountId)throw Error('The active account has changed. Refresh before switching.');
   await this.call(settings,'accounts.selectClaude',{accountId:account.id});
   const after=await this.list(settings);
   if(!isCurrent())throw Error('Remote connection changed. Refresh to check the selected account.');
   if(after.activeAccountId!==account.id)throw Error('Switch not confirmed. Refresh to check the active account.');
   return after;
  }finally{this.switching=false;}
 }
}
module.exports={Accounts,publicState};
