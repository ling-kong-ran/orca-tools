'use strict';
const net=require('node:net');
function validate(settings){
 if(typeof settings.environment!=='string'||!settings.environment.trim())throw Error('Set the exact Orca remote environment name.');
 if(net.isIP(settings.sshHost)!==4)throw Error('Set a literal Tailscale IPv4 address.');
 const octets=settings.sshHost.split('.').map(Number);
 if(octets[0]!==100||octets[1]<64||octets[1]>127)throw Error('SSH target must be a Tailscale address.');
 if(typeof settings.sshUser!=='string'||!/^[-a-z_][-a-z0-9_]*[$]?$/i.test(settings.sshUser))throw Error('Set the remote SSH user.');
 const sshPort=settings.sshPort??22;
 if(!Number.isInteger(sshPort)||sshPort<1||sshPort>65535)throw Error('Invalid SSH port.');
 return {environment:settings.environment,sshHost:settings.sshHost,sshUser:settings.sshUser,sshPort};
}
module.exports={validate};
