'use strict';
const path=require('node:path'),os=require('node:os'),fs=require('node:fs'),cp=require('node:child_process');

// Orca intentionally omits APPDATA and LOCALAPPDATA from its worker environment.
// Resolve user folders without relying on those variables; do not alter the host environment.
function windowsRuntime(env=process.env,execPath=process.execPath,home=os.homedir()) {
  const local=env.LOCALAPPDATA||path.join(home,'AppData','Local');
  const roaming=env.APPDATA||path.join(home,'AppData','Roaming');
  const windows=env.SystemRoot||env.SYSTEMROOT||env.WINDIR||'C:\\Windows';
  const system=path.join(windows,'System32');
  const candidates=[path.join(path.dirname(execPath),'resources','bin','orca.exe'),
    path.join(local,'Programs','orca','resources','bin','orca.exe')];
  const cli=candidates.find(file=>fs.existsSync(file));
  if(!cli)throw Error('Cannot locate the Orca CLI. Reinstall Orca with its command-line tools.');
  const childEnv={...env,USERPROFILE:env.USERPROFILE||home,HOME:env.HOME||home,
    LOCALAPPDATA:local,APPDATA:roaming,SystemRoot:windows,
    // Windows OpenSSH exits with code 255 even for -V if PROGRAMDATA is absent.
    PROGRAMDATA:env.PROGRAMDATA||path.join(path.parse(windows).root,'ProgramData')};
  // These belong to the plugin IPC/Electron worker, not the spawned CLI or OS tools.
  for(const key of ['ELECTRON_RUN_AS_NODE','NODE_CHANNEL_FD','NODE_CHANNEL_SERIALIZATION_MODE','NODE_UNIQUE_ID'])delete childEnv[key];
  return {home,local,cli,childEnv,ssh:path.join(system,'OpenSSH','ssh.exe'),
    keygen:path.join(system,'OpenSSH','ssh-keygen.exe'),browser:path.join(system,'rundll32.exe'),
    explorer:path.join(windows,'explorer.exe')};
}
async function launch(executable,args,env) {
  const child=cp.spawn(executable,args,{env,windowsHide:true,stdio:'ignore',detached:true});
  await new Promise((resolve,reject)=>{child.once('error',reject);child.once('spawn',resolve);});
  child.unref();
}
module.exports={windowsRuntime,launch};
