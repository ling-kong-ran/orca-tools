'use strict';
// The toolkit ships the GPU fragment with its plugin. Keep the existing bridge
// page as the canonical module source; no runtime dependency on repo paths.
const fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'..');
fs.copyFileSync(path.join(root,'services/local-gpu-bridge/admin.html'),path.join(root,'plugins/toolkit/modules/gpu-panel.html'));
const deploy=path.join(root,'plugins/toolkit/modules/deploy-runtime');
fs.mkdirSync(deploy,{recursive:true});
for(const name of ['__init__.py','deploy.py','plan.py','engine.py','transport.py','linux_stage.py','local.py','ui.html','README.md','requirements.txt','requirements-windows.lock'])fs.copyFileSync(path.join(root,'services/deploy',name),path.join(deploy,name));
fs.copyFileSync(path.join(root,'plugins/toolkit/choose-directory.ps1'),path.join(deploy,'choose-directory.ps1'));
fs.copyFileSync(path.join(root,'services/deploy/ui.html'),path.join(root,'plugins/toolkit/modules/deploy.html'));
const broker=path.join(deploy,'git-broker');fs.mkdirSync(broker,{recursive:true});
for(const name of ['broker.py','client.py','install.py','README.md','isolated-launcher.py'])fs.copyFileSync(path.join(root,'services/git-broker',name),path.join(broker,name));
const docs=path.join(deploy,'docs');fs.mkdirSync(docs,{recursive:true});
for(const name of ['deployment-center.md','claude-code-guide.md','vps-orca.md','gpu-bridge.md','toolkit.md','operations.md']){
 const file=path.join(root,'docs',name);if(fs.existsSync(file))fs.copyFileSync(file,path.join(docs,name));
}
if(fs.existsSync(path.join(root,'docs/images')))fs.cpSync(path.join(root,'docs/images'),path.join(docs,'images'),{recursive:true});
if(process.env.ORCA_DEPLOY_DEPS)fs.cpSync(process.env.ORCA_DEPLOY_DEPS,path.join(deploy,'dependencies'),{recursive:true});
console.log('GPU management fragment synchronized.');
