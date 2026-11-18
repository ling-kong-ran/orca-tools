'use strict';
const path=require('node:path'),fs=require('node:fs');
function createRemoteClient(runtime,environment){
 const root=path.resolve(path.dirname(runtime.cli),'..','app.asar.unpacked','out','cli');
 const sdk=[path.join(root,'runtime','client.js'),path.join(root,'runtime-client.js')].find(file=>fs.existsSync(file));
 if(!sdk)throw Error('The installed Orca runtime client is unavailable.');
 const {RuntimeClient}=require(sdk);
 const dataDir=runtime.childEnv.ORCA_USER_DATA_PATH||path.join(runtime.childEnv.APPDATA,'orca');
 return new RuntimeClient(dataDir,30000,null,environment,runtime.cli);
}
module.exports={createRemoteClient};
