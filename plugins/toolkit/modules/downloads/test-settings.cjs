'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {validate}=require('./settings.cjs');
test('download settings accept private targets and configurable users',()=>{
 assert.deepEqual(validate({environment:'My Server',sshHost:'100.64.0.20',sshUser:'worker'}),
  {environment:'My Server',sshHost:'100.64.0.20',sshUser:'worker',sshPort:22});
});
test('download settings reject public, malformed and option-like targets',()=>{
 for(const sshHost of ['8.8.8.8','127.0.0.1','100.63.0.1','100.128.0.1','100.64.999.1','--proxy-command=x'])
  assert.throws(()=>validate({environment:'Server',sshHost,sshUser:'worker'}));
 assert.throws(()=>validate({environment:'Server',sshHost:'100.64.0.20',sshUser:'user@host'}));
 assert.throws(()=>validate({environment:'Server',sshHost:'100.64.0.20',sshUser:'worker',sshPort:0}));
});
