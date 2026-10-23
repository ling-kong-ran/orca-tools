'use strict';
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),{promisify}=require('node:util');
const execFile=promisify(cp.execFile);
class DirectoryPicker {
 constructor(runtime,options={}){this.runtime=runtime;this.execute=options.execute||execFile;this.platform=options.platform||process.platform;this.pending=null;}
 async choose(initialDirectory=''){
  if(this.platform!=='win32')throw Error('Folder selection currently requires Windows. Enter a folder path manually.');
  if(this.pending)throw Error('A folder selection window is already open.');
  if(typeof initialDirectory!=='string'||initialDirectory.length>4096||/[\x00-\x1f]/.test(initialDirectory))throw Error('Invalid initial folder.');
  const source=this.runtime.childEnv||{},env={};
  for(const key of ['SystemRoot','WINDIR','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','HOMEDRIVE','HOMEPATH'])if(source[key])env[key]=source[key];
  env.SystemRoot=env.SystemRoot||'C:\\Windows';
  // Pass user text as data, never as part of a PowerShell command.
  env.ORCA_TOOLKIT_FOLDER_BASE64=Buffer.from(initialDirectory,'utf8').toString('base64');
  const executable=path.win32.join(env.SystemRoot,'System32','WindowsPowerShell','v1.0','powershell.exe');
  const args=['-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',path.join(__dirname,'choose-directory.ps1')];
  this.pending=this.execute(executable,args,{env,windowsHide:true,encoding:'utf8',timeout:600000,maxBuffer:65536});
  try{
   let result;
   try{const {stdout}=await this.pending;result=JSON.parse(stdout.replace(/^\uFEFF/,''));}
   catch{throw Error('The folder selection window could not finish. Try again or enter a folder path manually.');}
   if(result.cancelled===true)return {cancelled:true};
   if(result.cancelled!==false||typeof result.path!=='string'||!path.isAbsolute(result.path)||result.path.length>220||/[\x00-\x1f]/.test(result.path))throw Error('Choose an absolute folder path shorter than 221 characters.');
   if(!fs.statSync(result.path).isDirectory())throw Error('The selected folder is unavailable.');
   return {cancelled:false,path:result.path};
  }finally{this.pending=null;}
 }
 close(){this.pending?.child?.kill();}
}
module.exports={DirectoryPicker};
