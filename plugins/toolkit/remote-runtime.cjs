'use strict';
const path=require('node:path');
function createRemoteClient(runtime,environment){
 const sdk=path.resolve(path.dirname(runtime.cli),'..','app.asar.unpacked','out','cli','runtime-client.js');
 const {RuntimeClient}=require(sdk);
 const dataDir=runtime.childEnv.ORCA_USER_DATA_PATH||path.join(runtime.childEnv.APPDATA,'orca');
 return new RuntimeClient(dataDir,30000,null,environment,runtime.cli);
}
module.exports={createRemoteClient};
