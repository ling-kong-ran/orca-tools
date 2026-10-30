'use strict';
const fs=require('node:fs'),path=require('node:path');
// Local UI only. Project roots come from the authenticated bridge's approvals,
// never from a browser-supplied filesystem path.
function projectTypes(project){
 try{
  const root=fs.realpathSync(project.root);
  function candidate(subdir){
   const folder=fs.realpathSync(path.resolve(root,subdir||'')),relative=path.relative(root,folder);
   if(relative==='..'||relative.startsWith('..'+path.sep)||path.isAbsolute(relative))return null;
   return folder;
  }
  function unity(){try{const folder=candidate(project.unity_subdir);return folder&&['Assets','Packages','ProjectSettings'].every(name=>fs.statSync(path.join(folder,name)).isDirectory());}catch{return false;}}
  function godot(){for(const subdir of [project.godot_subdir||'client',''])try{const folder=candidate(subdir);if(folder&&fs.statSync(path.join(folder,'project.godot')).isFile())return true;}catch{}return false;}
  return [...godot()?['godot']:[],...unity()?['unity']:[]];
 }catch{return [];}
}
module.exports={projectTypes};
