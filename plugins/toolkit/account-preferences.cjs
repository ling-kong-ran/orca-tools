'use strict';
const fs=require('node:fs'),path=require('node:path');
class AccountPreferences {
 constructor(root){this.file=path.join(root,'account-preferences.json');this.value={};if(fs.existsSync(this.file)){this.value=JSON.parse(fs.readFileSync(this.file,'utf8'));if(!this.value||typeof this.value!=='object'||Array.isArray(this.value)||Object.values(this.value).some(ids=>!Array.isArray(ids)||ids.some(id=>typeof id!=='string')))throw Error('Invalid account preferences.');}}
 disabled(environment,id){return Object.hasOwn(this.value,environment)&&this.value[environment].includes(id);}
 set(environment,id,disabled){const ids=new Set(Object.hasOwn(this.value,environment)?this.value[environment]:[]);if(disabled)ids.add(id);else ids.delete(id);const next={...this.value,[environment]:[...ids]};fs.mkdirSync(path.dirname(this.file),{recursive:true});fs.writeFileSync(this.file+'.tmp',JSON.stringify(next,null,2));fs.renameSync(this.file+'.tmp',this.file);this.value=next;}
 apply(environment,state){return {...state,accounts:state.accounts.map(a=>({...a,disabled:this.disabled(environment,a.id)}))};}
}
module.exports={AccountPreferences};
