'use strict';
const fs=require('node:fs'),path=require('node:path');
function valid(folder){return typeof folder==='string'&&path.isAbsolute(folder)&&folder.length<=220&&!/[\x00-\x1f]/.test(folder);}
function defaultFolder(root,home){
 try{const value=JSON.parse(fs.readFileSync(path.join(root,'downloads-preferences.json'),'utf8'));if(valid(value.folder))return value.folder;}catch{}
 return path.join(home,'Downloads','Orca');
}
function rememberFolder(root,folder){
 if(!valid(folder))return false;
 try{fs.mkdirSync(root,{recursive:true});const file=path.join(root,'downloads-preferences.json');fs.writeFileSync(file+'.tmp',JSON.stringify({folder},null,2));fs.renameSync(file+'.tmp',file);return true;}catch{return false;}
}
module.exports={defaultFolder,rememberFolder};
