// One-use local helper. Credential input arrives only on stdin, never argv or a file.
let raw='';for await (const data of process.stdin)raw+=data;
const input=JSON.parse(raw);raw='';
let socket;
try {
  if(input.cdp_port!==9223 || typeof input.cookie!=='string')throw new Error('INVALID_INPUT');
  let endpoint;
  for(let i=0;i<150;i++) {
    try {const r=await fetch(`http://127.0.0.1:${input.cdp_port}/json/version`,{signal:AbortSignal.timeout(500)});endpoint=(await r.json()).webSocketDebuggerUrl;if(endpoint)break;}catch{}
    await new Promise(r=>setTimeout(r,200));
  }
  if(!endpoint?.startsWith(`ws://127.0.0.1:${input.cdp_port}/`))throw new Error('BROWSER_UNAVAILABLE');
  socket=new WebSocket(endpoint);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',()=>reject(new Error('CDP_UNAVAILABLE')),{once:true});});
  let next=0;const pending=new Map();
  socket.addEventListener('message',e=>{const m=JSON.parse(e.data);const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error('CDP_FAILED')):p.resolve(m.result);}});
  function call(method,params={}) {return new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});}
  const expires=Date.parse(input.expires_at)/1000;
  if(!Number.isFinite(expires)||expires<Date.now()/1000)throw new Error('SESSION_EXPIRED');
  await call('Storage.setCookies',{cookies:[{name:'ory_kratos_session',value:input.cookie,domain:'auth-cn.tripo3d.com',path:'/',secure:true,httpOnly:true,sameSite:'Lax',expires}]});
  input.cookie='';
  await call('Browser.close');
  socket.close();
  process.stdout.write(JSON.stringify({stored:true})+'\n');
} catch {
  input.cookie='';socket?.close();process.stderr.write('Local Cookie import failed. No credential details are logged.\n');process.exitCode=1;
}
