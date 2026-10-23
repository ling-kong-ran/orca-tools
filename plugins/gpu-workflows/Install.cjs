const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
(async()=>{
 const resources=path.join(process.env.LOCALAPPDATA,'Programs','orca','resources');
 const chunks=path.join(resources,'app.asar.unpacked','out','main','chunks');
 const name=fs.readdirSync(chunks).find(n=>/^orcad-migration-source-retention-.*\.js$/.test(n));
 if(!name)throw Error('Import this folder from Orca Settings > Plugins.');
 const installer=require(path.join(chunks,name));
 if(typeof installer.gr!=='function'||typeof installer.Fr!=='function')throw Error('Import this folder from Orca Settings > Plugins.');
 const hostVersion=cp.execFileSync(path.join(resources,'bin','orca.exe'),['--version'],{encoding:'utf8',windowsHide:true}).trim();
 const result=await installer.gr({pluginsDir:installer.Fr(path.join(process.env.APPDATA,'orca')),sourcePath:__dirname,hostVersion});
 console.log(JSON.stringify(result));
 if(!result.ok)process.exitCode=1;
 else console.log('Installed. Review and enable GPU Workflows in Orca Settings > Plugins.');
})().catch(e=>{console.error(e.message);process.exitCode=1;});
