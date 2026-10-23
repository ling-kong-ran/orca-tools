'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {SshTransport} = require('./transport.cjs');

class Semaphore {
  constructor(limit) { this.limit = limit; this.active = 0; this.waiters = []; }
  async run(signal, operation) {
    await new Promise((resolve, reject) => {
      const ticket = {resolve, reject, signal, abort: null};
      ticket.abort = () => { this.waiters = this.waiters.filter(t => t !== ticket); reject(Error('Paused')); };
      if (signal.aborted) return reject(Error('Paused'));
      if (this.active < this.limit) { this.active++; resolve(); }
      else { this.waiters.push(ticket); signal.addEventListener('abort', ticket.abort, {once: true}); }
    });
    try { if (signal.aborted) throw Error('Paused'); return await operation(); }
    finally {
      this.active--;
      while (this.waiters.length) {
        const next = this.waiters.shift();
        next.signal.removeEventListener('abort', next.abort);
        if (!next.signal.aborted) { this.active++; next.resolve(); break; }
      }
    }
  }
}
function writeJson(file, value) {
  fs.writeFileSync(file + '.tmp', JSON.stringify(value, null, 2));
  fs.renameSync(file + '.tmp', file);
}
function safeName(source) {
  let name = path.posix.basename(source).replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/[. ]+$/, '');
  if (!name || /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name)) name = 'download_' + name;
  return name.slice(0, 180);
}
class DownloadManager {
  constructor(options) {
    this.options = options; this.root = options.dataDir; this.jobs = new Map(); this.runs = new Map();
    this.live = new Map(); this.slots = new Semaphore(16); this.closed = false;
    this.transport = options.transport || new SshTransport(options);
    fs.mkdirSync(path.join(this.root, 'jobs'), {recursive: true});
    for (const name of fs.readdirSync(path.join(this.root, 'jobs'))) {
      if (!/^[a-f0-9]{32}\.json$/.test(name)) continue;
      try {
        const job = JSON.parse(fs.readFileSync(path.join(this.root, 'jobs', name), 'utf8'));
        if (!['complete','cancelled'].includes(job.status)) job.status = 'paused';
        this.jobs.set(job.id, job);
      } catch {}
    }
  }
  save(job) { writeJson(path.join(this.root, 'jobs', job.id + '.json'), job); }
  list() {
    return [...this.jobs.values()].reverse().map(job => {
      const live = this.live.get(job.id), done = new Set(job.done);
      let bytes = [...done].reduce((n,i) => n + Math.min(job.chunk, job.size - i * job.chunk), 0);
      if (live) bytes += [...live.ranges.values()].reduce((a,b) => a+b, 0);
      const speed = live ? Math.max(0, (bytes-live.initialBytes) / Math.max(1,(Date.now()-live.start)/1000)) : 0;
      return {id:job.id, source:job.source, name:job.name, destination:job.destination, status:job.status,
        size:job.size || 0, bytes, speed, percent:job.status==='complete'?100:job.size?Math.min(100,bytes/job.size*100):0,
        concurrency:job.concurrency, connections:live?.ranges.size||0, retries:job.retries||0,
        error:job.error||null, verified:job.verified||false, cleanupWarning:job.cleanupWarning||null};
    });
  }
  async create({source, folder, concurrency=12}) {
    if (this.closed) throw Error('Download manager is closing');
    if (typeof source!=='string' || !source.startsWith('/') || source.length>4096 || /[\x00-\x1f]/.test(source))
      throw Error('Enter an absolute remote file path');
    if (typeof folder!=='string' || !path.isAbsolute(folder) || folder.length>220) throw Error('Enter an absolute local folder path');
    if (!Number.isInteger(concurrency) || concurrency<1 || concurrency>16) throw Error('Choose 1 to 16 connections');
    if ([...this.jobs.values()].filter(j=>!['complete','cancelled'].includes(j.status)).length>=20) throw Error('Pause or finish an existing download first');
    folder=path.resolve(folder); fs.mkdirSync(folder,{recursive:true});
    const id=crypto.randomUUID().replaceAll('-',''), name=safeName(source), ext=path.extname(name), stem=name.slice(0,name.length-ext.length);
    let destination=path.join(folder,name), suffix=1;
    while(fs.existsSync(destination)||[...this.jobs.values()].some(j=>j.destination===destination&&j.status!=='cancelled')) destination=path.join(folder,`${stem} (${++suffix})${ext}`);
    const job={id,source,name:path.basename(destination),destination,partial:path.join(folder,`.${name}.${id}.part`),
      concurrency,chunk:4*1024*1024,status:'preparing',size:0,done:[],retries:0};
    this.jobs.set(id,job); this.save(job);
    this.start(job); return this.list().find(j=>j.id===id);
  }
  start(job) {
    if (this.runs.has(job.id)) throw Error('This download is already running');
    const controller=new AbortController();
    const promise=this.run(job,controller.signal).catch(error=>{
      job.status=controller.signal.aborted?'paused':'error';job.error=controller.signal.aborted?null:String(error.message).slice(0,500);this.save(job);
    }).finally(()=>{this.live.delete(job.id);this.runs.delete(job.id);});
    this.runs.set(job.id,{controller,promise});
  }
  async run(job,signal) {
    job.error=null;
    if (!job.sha256) {
      job.status='preparing';this.save(job);
      const meta=await this.transport.prepare(job);job.size=meta.size;job.sha256=meta.sha256;job.fingerprint=meta.fingerprint;
      const handle=fs.openSync(job.partial,'wx');try{fs.ftruncateSync(handle,job.size);}finally{fs.closeSync(handle);}
      this.save(job);
    }
    if(signal.aborted)throw Error('Paused');
    if(!fs.existsSync(job.partial))throw Error('Partial file is missing. Create a new download.');
    const fd=fs.openSync(job.partial,'r+'), done=new Set(job.done);
    if(fs.fstatSync(fd).size!==job.size){fs.closeSync(fd);throw Error('Partial file size changed. Create a new download.');}
    const live={ranges:new Map(),start:Date.now(),initialBytes:[...done].reduce((n,i)=>n+Math.min(job.chunk,job.size-i*job.chunk),0)};
    this.live.set(job.id,live);job.status='downloading';job.error=null;this.save(job);
    const queue=Array.from({length:Math.ceil(job.size/job.chunk)},(_,i)=>i).filter(i=>!done.has(i));let cursor=0,failed=false;
    const worker=async()=>{
      while(!signal.aborted&&!failed&&cursor<queue.length){const index=queue[cursor++],offset=index*job.chunk,length=Math.min(job.chunk,job.size-offset);let success=false,lastError;
        for(let attempt=0;attempt<6&&!signal.aborted;attempt++){
          try{
            await this.slots.run(signal,async()=>{
              live.ranges.set(index,0);
              try{await this.transport.read(job,offset,length,signal,(data,position)=>{
                if(position<0||position+data.length>length)throw Error('Invalid byte range');
                fs.writeSync(fd,data,0,data.length,offset+position);live.ranges.set(index,position+data.length);
              });}finally{live.ranges.delete(index);}
            });success=true;break;
          }catch(error){lastError=error;if(signal.aborted)break;job.retries++;this.save(job);
            await new Promise(resolve=>{const timer=setTimeout(finish,Math.min(10000,1000*(attempt+1)));function finish(){clearTimeout(timer);signal.removeEventListener('abort',finish);resolve();}signal.addEventListener('abort',finish,{once:true});});
          }
        }
        if(signal.aborted)return;
        if(!success){failed=true;throw lastError||Error('Transfer interrupted');}
        fs.fsyncSync(fd);done.add(index);job.done=[...done];this.save(job);
      }
    };
    let results;
    try{results=await Promise.allSettled(Array.from({length:job.concurrency},worker));}finally{fs.closeSync(fd);}
    if(signal.aborted)throw Error('Paused');
    const error=results.find(r=>r.status==='rejected');if(error)throw error.reason;
    job.status='verifying';this.save(job);
    const digest=crypto.createHash('sha256');for await(const block of fs.createReadStream(job.partial)){if(signal.aborted)throw Error('Paused');digest.update(block);}
    if(digest.digest('hex')!==job.sha256)throw Error('Checksum failed. The partial file has been retained. Start a new download.');
    // Hard-link with exclusive destination semantics: never overwrite a file which appeared during transfer.
    try{fs.linkSync(job.partial,job.destination);}catch(error){
      if(!['EPERM','ENOTSUP','EACCES'].includes(error.code))throw error;
      fs.copyFileSync(job.partial,job.destination,fs.constants.COPYFILE_EXCL);
    }
    fs.unlinkSync(job.partial);job.verified=true;job.status='complete';this.save(job);
    try{await this.transport.cleanup(job);}catch{job.cleanupWarning='Transfer access cleanup pending; use Clear access.';this.save(job);}
    await this.options.onComplete?.(job).catch(()=>{});
  }
  async action(id,action) {
    const job=this.jobs.get(id);if(!job)throw Error('Download not found');
    if(action==='pause'){
      const run=this.runs.get(id);if(run){run.controller.abort();await run.promise;}
    }else if(action==='resume'){
      if(!['paused','error'].includes(job.status))throw Error('This download cannot be resumed');
      if(this.runs.has(id))throw Error('Wait for the current operation to finish');
      this.start(job);
    }else if(action==='cancel'){
      if(job.status==='complete')throw Error('Completed files are kept');
      await this.action(id,'pause');
      try{await this.transport.cleanup(job);job.cleanupWarning=null;}catch{job.cleanupWarning='Transfer access cleanup pending; use Clear access.';}
      fs.rmSync(job.partial,{force:true});job.status='cancelled';this.save(job);
    }else if(action==='cleanup'){
      if(this.runs.has(id))throw Error('Pause the download before clearing access');
      await this.transport.cleanup(job);job.cleanupWarning=null;this.save(job);
      if(!['complete','cancelled'].includes(job.status)){job.status='cancelled';fs.rmSync(job.partial,{force:true});this.save(job);}
    }else throw Error('Unknown action');
    return this.list().find(j=>j.id===id);
  }
  async pauseAll(){await Promise.all([...this.runs.keys()].map(id=>this.action(id,'pause')));}
  async close(){this.closed=true;await this.pauseAll();}
}
module.exports={DownloadManager,Semaphore,safeName};
