'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {projectTypes}=require('./project-types.cjs');
test('project controls follow actual Godot and Unity files, including configured subfolders',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'toolkit-project-kind-'));
 try{
  fs.mkdirSync(path.join(root,'client'));fs.writeFileSync(path.join(root,'client/project.godot'),'config_version=5');
  assert.deepEqual(projectTypes({root}),['godot']);
  for(const name of ['Assets','Packages','ProjectSettings'])fs.mkdirSync(path.join(root,name));
  assert.deepEqual(projectTypes({root}),['godot','unity']);
  assert.deepEqual(projectTypes({root,unity_subdir:'missing'}),['godot']);
  assert.deepEqual(projectTypes({root:path.join(root,'missing')}),[]);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
test('project type detection refuses a selected subfolder outside the approved root',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'toolkit-project-scope-'));
 try{const approved=path.join(root,'approved');fs.mkdirSync(approved);for(const n of ['Assets','Packages','ProjectSettings'])fs.mkdirSync(path.join(root,n));assert.deepEqual(projectTypes({root:approved,unity_subdir:'..'}),[]);}finally{fs.rmSync(root,{recursive:true,force:true});}
});
