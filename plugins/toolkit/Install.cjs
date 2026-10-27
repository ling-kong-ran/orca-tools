'use strict';
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
(async()=>{
 const resources=path.join(process.env.LOCALAPPDATA,'Programs','orca','resources');
 const chunks=path.join(resources,'app.asar.unpacked','out','main','chunks');
 const moduleName=fs.readdirSync(chunks).find(name=>/^orcad-migration-source-retention-.*\.js$/.test(name));
 if(!moduleName)throw Error('This Orca version has a different installer. Import this folder from Orca Settings → Plugins.');
 const installer=require(path.join(chunks,moduleName));
 // Orca's bundled installer export names change between desktop builds. Select
 // only its local-path installer, never the Git or protected bundled installer.
 const install=Object.values(installer).find(value=>typeof value==='function'&&String(value).includes('.sourcePath')&&String(value).includes('local-path'));
 if(typeof install!=='function')throw Error('Use Orca Settings → Plugins to install this folder.');
 const hostVersion=cp.execFileSync(path.join(resources,'bin','orca.exe'),['--version'],{encoding:'utf8',windowsHide:true}).trim();
 const pluginsDir=path.join(process.env.APPDATA,'orca','plugins');
 const result=await install({pluginsDir,pluginsDataDir:path.join(process.env.APPDATA,'orca','plugins-data'),sourcePath:__dirname,hostVersion});
 console.log(JSON.stringify(result));
 if(!result.ok)process.exitCode=1;
 else console.log('Installed. Review and enable Orca Toolkit in Orca Settings → Plugins.');
})().catch(error=>{console.error(error.message);process.exitCode=1;});
