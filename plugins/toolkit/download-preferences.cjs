'use strict';
const fs=require('node:fs'),path=require('node:path');
const {validRemote}=require('./remote-browser.cjs');
function valid(folder){return typeof folder==='string'&&path.isAbsolute(folder)&&folder.length<=220&&!/[\x00-\x1f]/.test(folder);}
function read(root){try{const value=JSON.parse(fs.readFileSync(path.join(root,'downloads-preferences.json'),'utf8'));return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}catch{return {};}}
function write(root,value){try{fs.mkdirSync(root,{recursive:true});const file=path.join(root,'downloads-preferences.json');fs.writeFileSync(file+'.tmp',JSON.stringify(value,null,2));fs.renameSync(file+'.tmp',file);return true;}catch{return false;}}
function defaultFolder(root,home){
 const value=read(root);if(valid(value.folder))return value.folder;
 return path.join(home,'Downloads','Orca');
}
function rememberFolder(root,folder){
 if(!valid(folder))return false;
 return write(root,{...read(root),folder});
}
function remoteLocation(root,environment){
 const locations=read(root).remoteLocations;
 const value=locations&&Object.hasOwn(locations,environment)?locations[environment]:{};
 return {directory:validRemote(value?.directory)?value.directory:'',source:validRemote(value?.source)?value.source:''};
}
function rememberRemote(root,environment,changes){
 if(typeof environment!=='string'||!environment||!changes||Object.keys(changes).some(k=>!['source','directory'].includes(k)))return false;
 if(Object.values(changes).some(v=>v!==''&&!validRemote(v)))return false;
 const current=read(root),previous=remoteLocation(root,environment);
 const locations=current.remoteLocations&&typeof current.remoteLocations==='object'&&!Array.isArray(current.remoteLocations)?current.remoteLocations:{};
 return write(root,{...current,remoteLocations:{...locations,[environment]:{...previous,...changes}}});
}
module.exports={defaultFolder,rememberFolder,remoteLocation,rememberRemote};
