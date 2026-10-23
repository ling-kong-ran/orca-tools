"""Project-scoped synchronization and typed native MCP operations; no shell API."""
import base64,copy,hashlib,ipaddress,json,math,os,pathlib,re,shutil,socket,subprocess,threading,time,uuid
from native_process import EgressGuard,ManagedProcess

HEX=re.compile(r'^[a-f0-9]{32}$');SHA=re.compile(r'^[a-f0-9]{64}$')
DENY_PARTS={'.git','.godot','.svn','node_modules','__pycache__','.ssh','.codex','.claude','.agent_bridge','saves'}
DENY_SUFFIX={'.exe','.dll','.bat','.cmd','.ps1','.sh','.vbs','.com','.scr','.lnk','.pem','.key','.pfx','.p12','.log'}
DENY_NAMES={'credentials.json','config.json','settings.json','secrets.json','id_rsa','id_ed25519'}
def atomic(file,value):
    file.parent.mkdir(parents=True,exist_ok=True);temp=file.with_name(file.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');os.replace(temp,file)
def digest(file):
    if not file.is_file():return None
    h=hashlib.sha256()
    with file.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def clean_relative(value):
    if not isinstance(value,str) or not value or len(value)>500 or '\\' in value or ':' in value or value.startswith('/') or '\x00' in value:raise ValueError('Use a project-relative path.')
    parts=value.split('/')
    if any(p in ('','.','..') or p.endswith(('.', ' ')) or p.lower() in DENY_PARTS or p.lower() in DENY_NAMES or p.lower().startswith('.env') or re.match(r'^(con|nul|prn|aux|com[1-9]|lpt[1-9])(\.|$)',p,re.I) for p in parts):raise ValueError('This project path is not exposed.')
    if pathlib.PurePosixPath(value).suffix.lower() in DENY_SUFFIX:raise ValueError('Executable/system/credential files are not exposed.')
    return value
def inside(root,relative):
    clean_relative(relative);file=root/relative
    for part in [file,*file.parents]:
        if part==root:break
        if part.exists() and (part.is_symlink() or getattr(part.stat(),'st_file_attributes',0)&0x400):raise ValueError('Links and reparse points are not exposed.')
    if not file.resolve().is_relative_to(root.resolve()):raise ValueError('Path is outside the project.')
    return file
PRIVATE_KEYS={'path_absolute','filepath','device','devices','gpu','gpus','cpu','cpus','vram','ram','hostname','computername','username','ip','ipv4','ipv6','public_ip','private_ip','address','mac','mac_address','network','networks','interfaces','adapters','hardware','hardware_info','hardware_model','device_name','adapter_name','environment','system_info','system','platform','os','version','driver','driver_version','serial','serial_number','log','logs','stdout','stderr'}
def private_text(value):
    value=re.sub(r'(?i)\b[A-Z]:[\\/][^\n\r\"\']*','[local path]',value)
    value=re.sub(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])','[address]',value)
    value=re.sub(r'(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b','[network identifier]',value)
    def ipv6(match):
        try:ipaddress.IPv6Address(match[0].split('%')[0]);return '[address]'
        except ValueError:return match[0]
    value=re.sub(r'(?<!\w)(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.%]*(?!\w)',ipv6,value)
    for name in {socket.gethostname(),os.environ.get('COMPUTERNAME',''),os.environ.get('USERNAME','')}:
        if len(name)>=3:value=re.sub(r'(?i)(?<!\w)'+re.escape(name)+r'(?!\w)','[local identity]',value)
    value=re.sub(r'(?i)\b(?:NVIDIA\s+(?:GeForce\s+)?(?:RTX|GTX|Tesla|Quadro)[^\n\r\"\',;]*|AMD\s+Radeon[^\n\r\"\',;]*|Intel\s+(?:Arc|Core|Xeon)[^\n\r\"\',;]*)','[hardware]',value)
    return value
def private_result(value):
    # Results never include app logs, executable paths, system versions or arbitrary tool output.
    if isinstance(value,dict):return {k:private_result(v) for k,v in value.items() if k.lower() not in PRIVATE_KEYS}
    if isinstance(value,list):return [private_result(v) for v in value[:1000]]
    if isinstance(value,str):
        return private_text(value)[:16000]
    return value

BLENDER_FIELDS={
 'scene_info':set(),'open':{'path'},'save':{'path','replace'},'import_asset':{'path'},'export_asset':{'path','replace'},
 'create_primitive':{'kind','name','location','rotation','scale'},'set_transform':{'name','location','rotation','scale'},
 'set_material':{'name','color','roughness','metallic'},'set_camera':{'location','target','lens'},
 'delete_object':{'name'},'render':{'engine','width','height','samples'}
 ,'execute_code':{'code','parameters','timeout_seconds'},'run_script':{'path','user_args','parameters','timeout_seconds'}
}

class NativeControl:
    def __init__(self,config,save_config=None,guard=None,process_factory=ManagedProcess):
        self.config=config;self.root=pathlib.Path(config['data_dir'])/'native';self.root.mkdir(parents=True,exist_ok=True)
        self.save_config=save_config;self.guard=guard or EgressGuard(config.get('native',{}));self.process_factory=process_factory
        self.lock=threading.RLock();self.execute_lock=threading.Lock();self.blender=None;self.blender_project=None
        self.jobs={};self.plans={}
        self.privacy_setup={'status':'idle'}
        for f in (self.root/'jobs').glob('*.json'):
            try:
                value=json.loads(f.read_text(encoding='utf-8'))
                if value.get('status') in ('queued','running'):value.update(status='unknown',message='Bridge restarted; inspect local app before repeating this operation.')
                self.jobs[value['id']]=value
            except (ValueError,KeyError):pass
        for f in (self.root/'plans').glob('*.json'):
            try:value=json.loads(f.read_text(encoding='utf-8'));self.plans[value['id']]=value
            except (ValueError,KeyError):pass
    def projects(self,local=False):
        values=[]
        for p in self.config.get('native',{}).get('projects',[]):
            row={k:p[k] for k in ('id','name','enabled')}
            row['sync_policy']=p.get('sync_policy','local_review')
            row['allow_scripts']=p.get('allow_scripts',False)
            row['git']={k:p.get('git',{}).get(k,d) for k,d in [('enabled',False),('remote','origin'),('branch','main'),('auto_pull_before_render',False)]}
            row['sync_method']='git' if row['git']['enabled'] else 'disabled'
            if local:row.update(root=p['root'],godot_subdir=p.get('godot_subdir','client'))
            values.append(row)
        return values
    def project(self,ident):
        item=next((p for p in self.config.get('native',{}).get('projects',[]) if p['id']==ident and p.get('enabled')),None)
        if not item:raise ValueError('Project access is disabled or unknown.')
        root=pathlib.Path(item['root']).resolve()
        if not root.is_dir():raise ValueError('The approved project directory is unavailable.')
        return item,root
    def manage_project(self,value):
        if set(value)-{'id','name','root','godot_subdir','enabled','sync_policy','allow_scripts','git'}:raise ValueError('Unexpected project settings.')
        if not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}',value.get('id','')):raise ValueError('Invalid project id.')
        if not isinstance(value.get('root'),str) or not pathlib.Path(value['root']).is_absolute():raise ValueError('Use an absolute local project directory.')
        root=pathlib.Path(value['root']).resolve()
        if not root.is_dir() or root.parent==root or len(root.parts)<3:raise ValueError('Select a specific existing project folder.')
        sub=clean_relative(value.get('godot_subdir','client'))
        item={'id':value['id'],'name':str(value.get('name') or value['id'])[:100],'root':str(root),'godot_subdir':sub,'enabled':bool(value.get('enabled',True))}
        with self.lock:
            projects=self.config.setdefault('native',{}).setdefault('projects',[])
            previous=next((p for p in projects if p['id']==item['id']),None)
            item['sync_policy']=value.get('sync_policy',(previous or {}).get('sync_policy','local_review'))
            if item['sync_policy'] not in ('remote_wins','local_review'):raise ValueError('Invalid sync policy.')
            if 'allow_scripts' in value and type(value['allow_scripts'])is not bool:raise ValueError('allow_scripts must be boolean.')
            item['allow_scripts']=value.get('allow_scripts',(previous or {}).get('allow_scripts',False))
            item['git']=copy.deepcopy(value.get('git',(previous or {}).get('git',{})))
            git=item['git']
            if not isinstance(git,dict) or set(git)-{'enabled','remote','branch','auto_pull_before_render'}:raise ValueError('Invalid Git settings.')
            if any(k in git and type(git[k])is not bool for k in ('enabled','auto_pull_before_render')):raise ValueError('Git switches must be boolean.')
            if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,63}',git.get('remote','origin')):raise ValueError('Invalid Git remote name.')
            branch=git.get('branch','main')
            if not isinstance(branch,str) or not branch or len(branch)>200 or branch.startswith('-') or '..' in branch or any(c in branch for c in '\\:~^?*['):raise ValueError('Invalid Git branch.')
            if previous:projects.remove(previous)
            projects.append(item)
            if self.save_config:self.save_config()
        return {'saved':True}
    def status(self,local=False):
        native=self.config.get('native',{});engines=[]
        for engine in ('godot','blender'):
            configured=pathlib.Path(native.get(engine+'_executable','')).is_file()
            row={'engine':engine,'installed':configured,'network_isolated':configured and self.guard.ready(engine)}
            if engine=='blender':row['connected']=self.blender is not None and self.blender.poll() is None
            engines.append(row)
        result={'engines':engines,'projects':self.projects(local),'shell_exposed':False,'raw_code_tool_exposed':any(p.get('allow_scripts') for p in self.projects()),'project_code_executes_locally':True}
        if local:
            result['setup_script']=str(pathlib.Path(__file__).parent/'Setup-Native-Privacy.ps1')
            result['privacy_setup']=dict(self.privacy_setup)
        return result
    def setup_privacy(self):
        with self.lock:
            if self.privacy_setup['status'] in ('checking','awaiting_permission'):return {'requested':True,'message':'Windows network privacy setup is already running.'}
            self.privacy_setup={'status':'checking'}
        def setup():
            try:
                engines=[engine for engine in ('godot','blender') if self.config.get('native',{}).get(engine+'_executable')]
                if self.config.get('native',{}).get('go_executable'):engines.append('go')
                engines+=['server-'+key for key in self.config.get('native',{}).get('server_executables',{})]
                if all(self.guard.ready(engine) for engine in engines):
                    self.privacy_setup={'status':'ready'};return
                self.privacy_setup={'status':'awaiting_permission'}
                script=str(pathlib.Path(__file__).parent/'Setup-Native-Privacy.ps1')
                command="$ErrorActionPreference='Stop'; try { $nativeSetup = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','\""+script.replace("'","''")+"\"') -WindowStyle Hidden -Wait -PassThru; exit $nativeSetup.ExitCode } catch { exit 1 }"
                p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000,timeout=600)
                ready=p.returncode==0 and all(self.guard.ready(engine) for engine in engines)
                self.privacy_setup={'status':'ready' if ready else 'failed','message':'Network privacy is ready.' if ready else 'Windows administrator permission was not granted or setup failed. Select Set up network privacy to retry.'}
            except Exception:
                import logging;logging.exception('Automatic native privacy setup failed')
                self.privacy_setup={'status':'failed','message':'Windows network privacy setup did not finish. Select Set up network privacy to retry.'}
        threading.Thread(target=setup,daemon=True).start()
        return {'requested':True,'message':'Network privacy setup runs automatically. Approve the Windows administrator prompt if shown.'}
    def files(self,project_id,prefix='',offset=0,limit=100):
        _,root=self.project(project_id)
        if prefix:folder=inside(root,prefix)
        else:folder=root
        if not folder.is_dir():raise ValueError('Folder is unavailable.')
        if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=300:raise ValueError('Invalid page.')
        rows=[]
        for current,dirs,files in os.walk(folder,followlinks=False):
            dirs[:]=[d for d in sorted(dirs) if d.lower() not in DENY_PARTS and not (pathlib.Path(current)/d).is_symlink() and not getattr((pathlib.Path(current)/d).stat(),'st_file_attributes',0)&0x400]
            for name in sorted(files):
                f=pathlib.Path(current)/name;relative=f.relative_to(root).as_posix()
                try:inside(root,relative)
                except ValueError:continue
                rows.append({'path':relative,'bytes':f.stat().st_size})
                if len(rows)>=10000:break
            if len(rows)>=10000:break
        return {'files':rows[offset:offset+limit],'next_offset':offset+limit if offset+limit<len(rows) else None,'total':len(rows)}
    def read_file(self,project_id,path):
        _,root=self.project(project_id);file=inside(root,path)
        if not file.is_file() or file.stat().st_size>256*1024:raise ValueError('Text file is unavailable or exceeds 256 KB.')
        try:text=file.read_text(encoding='utf-8-sig')
        except UnicodeError:raise ValueError('Use artifact download for binary files.') from None
        # File transfer must not become a way to query local secrets or network records.
        if file.suffix.lower()=='.json':
            try:text=json.dumps(private_result(json.loads(text)),ensure_ascii=False,indent=2)
            except ValueError:pass
        return {'path':path,'sha256':digest(file),'text':private_text(text)}
    def project_download(self,project_id,path):
        _,root=self.project(project_id);file=inside(root,path)
        if not file.is_file() or file.stat().st_size>2*1024**3:raise ValueError('Project file is unavailable or exceeds the transfer limit.')
        if file.suffix.lower() in {'.json','.txt','.md','.csv','.yaml','.yml','.toml','.ini','.gd','.py','.go','.cfg','.godot','.tscn','.tres','.html','.js','.css'}:
            if file.stat().st_size>8*1024**2:raise ValueError('Text files exceeding 8 MB require a smaller export for privacy filtering.')
            try:text=file.read_text(encoding='utf-8-sig')
            except UnicodeError:raise ValueError('This text file cannot be privacy-filtered.') from None
            if file.suffix.lower()=='.json':
                try:text=json.dumps(private_result(json.loads(text)),ensure_ascii=False,indent=2)
                except ValueError:pass
            data=private_text(text).encode('utf-8');folder=self.root/'filtered-downloads';folder.mkdir(exist_ok=True)
            target=folder/(hashlib.sha256(data).hexdigest()+file.suffix.lower())
            if not target.exists():target.write_bytes(data)
            return target
        return file
    def sync_plan(self,body):
        ident=body.get('project_id');_,root=self.project(ident);files=body.get('files')
        if self.config.get('native',{}).get('git_only_sync'):raise ValueError('Project sync now uses Git. Commit and push on the VPS, then call project_git(operation="pull").')
        if not isinstance(files,list) or not 1<=len(files)<=10000:raise ValueError('Provide 1 to 10000 files.')
        state_file=self.root/'sync-state'/(ident+'.json')
        state=json.loads(state_file.read_text()) if state_file.exists() else {}
        rows=[];seen=set()
        for item in files:
            relative=clean_relative(item.get('path'));file=inside(root,relative);sha=item.get('sha256');size=item.get('bytes')
            if relative.casefold() in seen or not isinstance(sha,str) or not SHA.fullmatch(sha) or type(size)is not int or not 0<=size<=512*1024**2:raise ValueError('Invalid or duplicate file manifest.')
            if file.exists() and not file.is_file():raise ValueError('A sync destination is not a file.')
            seen.add(relative.casefold());current=digest(file)
            status='same' if current==sha else 'add' if current is None else 'update' if state.get(relative)==current else 'conflict'
            rows.append({'path':relative,'sha256':sha,'bytes':size,'previous_sha256':current,'status':status})
        plan={'id':uuid.uuid4().hex,'project_id':ident,'created_at':time.time(),'status':'planned','files':rows,'conflicts_approved':False}
        with self.lock:self.plans[plan['id']]=plan;atomic(self.root/'plans'/(plan['id']+'.json'),plan)
        return self.public_plan(plan)
    def public_plan(self,plan):
        result={k:copy.deepcopy(plan[k]) for k in ('id','project_id','created_at','status','files','conflicts_approved')}
        project=next((p for p in self.config.get('native',{}).get('projects',[]) if p['id']==plan['project_id']),{})
        result['sync_policy']=project.get('sync_policy','local_review')
        return result
    def upload_chunk(self,body):
        if self.config.get('native',{}).get('git_only_sync'):raise ValueError('Project sync now uses Git. Commit and push on the VPS, then call project_git(operation="pull").')
        sha=body.get('sha256');size=body.get('bytes');offset=body.get('offset')
        if not isinstance(sha,str) or not SHA.fullmatch(sha) or type(size)is not int or not 0<=size<=512*1024**2 or type(offset)is not int or offset<0:raise ValueError('Invalid upload.')
        try:data=base64.b64decode(body.get('data',''),validate=True)
        except Exception:raise ValueError('Invalid upload encoding.') from None
        if len(data)>4*1024**2 or offset+len(data)>size:raise ValueError('Invalid upload chunk size.')
        with self.lock:
            allowed=any(p['status']=='planned' and any(f['sha256']==sha and f['bytes']==size and f['status']!='same' for f in p['files']) for p in self.plans.values())
            if not allowed:raise ValueError('Create a sync plan before uploading files.')
            folder=self.root/'blobs';folder.mkdir(exist_ok=True);target=folder/sha
            if target.exists():
                if target.stat().st_size!=size:raise ValueError('Upload manifest size does not match its hash.')
                return {'offset':target.stat().st_size,'complete':True}
            part=folder/(sha+'.part');current=part.stat().st_size if part.exists() else 0
            if offset!=current:return {'offset':current,'complete':False}
            with part.open('ab') as stream:stream.write(data)
            current+=len(data)
            if current==size:
                if digest(part)!=sha:part.unlink();raise ValueError('Upload hash mismatch; resend the file.')
                part.replace(target)
            return {'offset':current,'complete':current==size}
    def apply_sync(self,ident,approve_conflicts=False):
        if self.config.get('native',{}).get('git_only_sync'):raise ValueError('Project sync now uses Git. Commit and push on the VPS, then call project_git(operation="pull").')
        with self.lock:
            plan=self.plans.get(ident)
            if not plan:raise ValueError('Unknown sync plan.')
            if plan['status']=='applied':return self.public_plan(plan)
            if plan['status']!='planned':raise ValueError('This plan is no longer applicable.')
            project,root=self.project(plan['project_id']);remote_wins=project.get('sync_policy','local_review')=='remote_wins'
            if any(j['project_id']==plan['project_id'] and j['status'] in ('queued','running') for j in self.jobs.values()):raise ValueError('Wait for active native tasks before applying sync.')
            if approve_conflicts:plan['conflicts_approved']=True
            if not remote_wins and any(f['status']=='conflict' for f in plan['files']) and not plan['conflicts_approved']:raise ValueError('Local files differ. Review this sync plan and approve conflicts on the local management page.')
            changed=[f for f in plan['files'] if f['status']!='same']
            for f in plan['files']:
                target=inside(root,f['path'])
                if target.exists() and not target.is_file():raise ValueError('A sync destination is not a file.')
                if digest(target)!=f['previous_sha256'] and (not remote_wins or f['status']=='same'):raise ValueError('A local file changed after preview. Create a new sync plan.')
                if f['status']!='same':
                    blob=self.root/'blobs'/f['sha256']
                    if not blob.is_file() or digest(blob)!=f['sha256']:raise ValueError('Some files have not finished uploading.')
            applied=[];backup=self.root/'backups'/plan['id']
            try:
                for f in changed:
                    target=inside(root,f['path']);target.parent.mkdir(parents=True,exist_ok=True)
                    saved=backup/f['path']
                    if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
                    temp=target.with_name('.'+target.name+'.'+plan['id']+'.part');shutil.copyfile(self.root/'blobs'/f['sha256'],temp);os.replace(temp,target);applied.append((target,saved))
            except Exception:
                for target,saved in reversed(applied):
                    if saved.exists():os.replace(saved,target)
                    elif target.exists():target.unlink()
                raise ValueError('Sync failed and written files were rolled back. Check the local log.') from None
            state_file=self.root/'sync-state'/(plan['project_id']+'.json');state=json.loads(state_file.read_text()) if state_file.exists() else {}
            state.update({f['path']:f['sha256'] for f in plan['files']});atomic(state_file,state)
            plan['status']='applied';atomic(self.root/'plans'/(ident+'.json'),plan)
            return self.public_plan(plan)
    def public_job(self,job):return private_result({k:copy.deepcopy(job[k]) for k in ('id','project_id','engine','operation','status','created_at','updated_at','result','error','artifacts') if k in job})
    def save_job(self,job):job['updated_at']=time.time();atomic(self.root/'jobs'/(job['id']+'.json'),job)
    def project_git(self,project_id,operation='status',request_id=None):
        project,root=self.project(project_id)
        if operation=='status':
            from native_git import git_for
            return git_for(self,project,root).status()
        if operation not in ('pull','fetch'):raise ValueError('Only Git status, fetch and pull are exposed.')
        return self.queue({'project_id':project_id,'engine':'git','operation':operation,'arguments':{},'request_id':request_id or uuid.uuid4().hex})
    def queue(self,body):
        project_id=body.get('project_id');project,root=self.project(project_id);engine=body.get('engine');operation=body.get('operation');args=body.get('arguments',{})
        pulls_first=bool(project.get('git',{}).get('enabled') and project.get('git',{}).get('auto_pull_before_render'))
        if engine not in ('godot','blender','git') or not isinstance(args,dict):raise ValueError('Invalid native task.')
        if engine=='git':
            if operation not in ('pull','fetch') or args or not project.get('git',{}).get('enabled'):raise ValueError('Git operation is unavailable for this project.')
        elif engine=='blender':
            self.validate_blender(operation,args,root,allow_missing=pulls_first)
            if operation in ('execute_code','run_script') and not project.get('allow_scripts'):raise ValueError('Project script access is disabled on the local management page.')
        elif operation=='script':
            from native_script import script_request
            script_request(self,project,root,operation,args,allow_missing=pulls_first)
        elif operation!='capture':raise ValueError('Godot operation is not exposed.')
        else:self.validate_godot(project,root,args,allow_missing=pulls_first)
        if engine!='git':self.guard.require(engine)
        request_id=body.get('request_id')
        if not isinstance(request_id,str) or not HEX.fullmatch(request_id):raise ValueError('Provide a 32-character request_id.')
        fingerprint=hashlib.sha256(json.dumps({'project_id':project_id,'engine':engine,'operation':operation,'arguments':args},sort_keys=True).encode()).hexdigest()
        with self.lock:
            previous=next((j for j in self.jobs.values() if j.get('request_id')==request_id),None)
            if previous:
                if previous['fingerprint']!=fingerprint:raise ValueError('Request id already used with different parameters.')
                return self.public_job(previous)
            if sum(j['status'] in ('queued','running') for j in self.jobs.values())>=8:raise ValueError('Native task queue is full.')
            job={'id':uuid.uuid4().hex,'request_id':request_id,'fingerprint':fingerprint,'project_id':project_id,'engine':engine,'operation':operation,'arguments':args,'status':'queued','created_at':time.time(),'artifacts':[]}
            self.jobs[job['id']]=job;self.save_job(job)
            threading.Thread(target=self.run,args=(job,),daemon=True).start()
            return self.public_job(job)
    def validate_godot(self,project,root,args,allow_missing=False):
        if set(args)-{'scene','width','height','wait_seconds','renderer','user_args'}:raise ValueError('Unexpected Godot capture fields.')
        from native_script import arguments
        arguments(args.get('user_args',[]))
        client=inside(root,project.get('godot_subdir','client'))
        scene=args.get('scene','scenes/main.tscn')
        file=inside(client,scene)
        if file.suffix!='.tscn' or (not file.is_file() and not allow_missing) or file.is_dir():raise ValueError('Select an existing project scene.')
        for key,default in [('width',1280),('height',720)]:
            if type(args.get(key,default))is not int or not 64<=args.get(key,default)<=4096:raise ValueError('Capture dimensions must be 64 to 4096.')
        delay=args.get('wait_seconds',3)
        if type(delay)not in (int,float) or not math.isfinite(delay) or not 0.1<=delay<=60:raise ValueError('Capture delay must be 0.1 to 60 seconds.')
        if args.get('renderer','forward_plus') not in ('forward_plus','mobile','gl_compatibility'):raise ValueError('Unknown renderer.')
    def validate_blender(self,operation,args,root,allow_missing=False):
        fields=BLENDER_FIELDS.get(operation)
        if fields is None or set(args)-fields:raise ValueError('Blender operation or argument is not exposed.')
        required={'open':{'path'},'save':{'path'},'import_asset':{'path'},'export_asset':{'path'},'create_primitive':{'kind'},'set_transform':{'name'},'set_material':{'name','color'},'set_camera':{'location'},'delete_object':{'name'},'execute_code':{'code'},'run_script':{'path'}}.get(operation,set())
        if not required.issubset(args):raise ValueError('Required Blender fields are missing.')
        if 'path' in args:inside(root,args['path'])
        if operation=='run_script':
            file=inside(root,args['path'])
            if file.suffix!='.py' or (not file.is_file() and not allow_missing) or file.is_dir():raise ValueError('Select an existing project .py script.')
            from native_script import arguments
            arguments(args.get('user_args',[]))
        if operation=='execute_code' and (not isinstance(args['code'],str) or not 1<=len(args['code'])<=256000):raise ValueError('Provide Python code of at most 256 KB.')
        if 'parameters' in args and not isinstance(args['parameters'],dict):raise ValueError('parameters must be an object.')
        if 'timeout_seconds' in args and (type(args['timeout_seconds'])is not int or not 10<=args['timeout_seconds']<=7200):raise ValueError('Script timeout must be 10 to 7200 seconds.')
        if operation in ('open','save') and pathlib.PurePosixPath(args['path']).suffix.lower()!='.blend':raise ValueError('Select a .blend file.')
        for key in ('name',):
            if key in args and (not isinstance(args[key],str) or not 1<=len(args[key])<=120):raise ValueError('Invalid object name.')
        for key in ('location','rotation','scale','target'):
            if key in args and (not isinstance(args[key],list) or len(args[key])!=3 or not all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=1e6 for v in args[key])):raise ValueError('Invalid transform vector.')
        for key,default,minimum,maximum in [('width',1280,64,4096),('height',720,64,4096),('samples',32,1,512)]:
            if key in args and (type(args[key])is not int or not minimum<=args[key]<=maximum):raise ValueError('Invalid render dimensions or sample count.')
        if operation=='render' and args.get('engine','cycles') not in ('cycles','eevee'):raise ValueError('Only GPU render engines are exposed.')
        if 'lens' in args and (type(args['lens'])not in (int,float) or not 1<=args['lens']<=500):raise ValueError('Invalid camera lens.')
        if 'replace' in args and type(args['replace'])is not bool:raise ValueError('replace must be boolean.')
    def run(self,job):
        with self.execute_lock:
            try:
                project,root=self.project(job['project_id'])
                if job['engine']!='git':self.guard.require(job['engine'])
                with self.lock:job['status']='running';self.save_job(job)
                output_dir=self.root/'artifacts';output_dir.mkdir(exist_ok=True)
                git_update=None
                if job['engine']=='git':
                    from native_git import git_for
                    git=git_for(self,project,root)
                    job['result']=git.pull(job['id']) if job['operation']=='pull' else {'fetched':True,'head':git.fetch()}
                    with self.lock:job['status']='succeeded';self.save_job(job)
                    return
                if project.get('git',{}).get('enabled') and project['git'].get('auto_pull_before_render') and (job['engine']=='godot' or job['operation'] in ('open','execute_code','run_script','render')):
                    from native_git import git_for
                    git_update=git_for(self,project,root).pull(job['id'])
                if job['engine']=='blender' and job['operation'] in ('run_script','execute_code') and not project.get('allow_scripts'):raise ValueError('Project script access is disabled.')
                if job['engine']=='godot' and job['operation']=='script':
                    from native_script import run_script
                    self.import_godot(job,project,root)
                    run_script(self,job,project,root,output_dir)
                elif job['engine']=='godot':self.run_godot(job,project,root,output_dir)
                else:
                    self.validate_blender(job['operation'],job['arguments'],root)
                    self.run_blender(job,root,output_dir)
                if git_update is not None:job.setdefault('result',{})['git_update']=git_update
                with self.lock:job['status']='succeeded';self.save_job(job)
            except Exception:
                import logging;logging.exception('Native task failed')
                with self.lock:job['status']='failed';job['error']='Native operation failed. Check the local management page and application log.';self.save_job(job)
    def import_godot(self,job,project,root):
        client=inside(root,project.get('godot_subdir','client'));folder=self.root/'runs'/job['id'];folder.mkdir(parents=True,exist_ok=True)
        executable=self.config['native']['godot_executable']
        # Import synchronized textures/models before opening the runtime scene.
        # Recovery mode keeps editor tool scripts/plugins disabled during import.
        importer=self.process_factory([executable,'--headless','--editor','--path',str(client),'--import','--quit','--recovery-mode'],client,folder/'import.log')
        try:
            if importer.wait(timeout=300):raise ValueError('Asset import failed')
        except subprocess.TimeoutExpired:importer.stop();raise ValueError('Asset import timeout') from None
        finally:importer.close()
    def run_godot(self,job,project,root,output_dir):
        args=job['arguments'];client=inside(root,project.get('godot_subdir','client'));self.validate_godot(project,root,args)
        folder=self.root/'runs'/job['id'];folder.mkdir(parents=True,exist_ok=True);output=output_dir/(job['id']+'.png')
        request={'scene':args.get('scene','scenes/main.tscn'),'width':args.get('width',1280),'height':args.get('height',720),'wait_seconds':args.get('wait_seconds',3),'output':str(output)}
        atomic(folder/'capture.json',request);self.import_godot(job,project,root)
        executable=self.config['native']['godot_executable']
        command=[executable,'--path',str(client),'--audio-driver','Dummy','--rendering-method',args.get('renderer','forward_plus'),'--position','-32000,-32000','--script',str(pathlib.Path(__file__).parent/'native_godot.gd'),'--',str(folder/'capture.json'),*args.get('user_args',[])]
        process=self.process_factory(command,client,folder/'application.log')
        try:
            code=process.wait(timeout=240)
            if code or not output.is_file():raise ValueError('Capture failed')
        except subprocess.TimeoutExpired:process.stop();raise ValueError('Capture timeout') from None
        finally:process.close()
        job['artifacts']=[{'index':0,'filename':'godot-capture.png','file':output.name}];job['result']={'captured':True,'hardware_render':True}
    def run_blender(self,job,root,output_dir):
        spool=self.root/'blender-spool';spool.mkdir(exist_ok=True)
        if self.blender and (self.blender.poll() is not None or self.blender_project!=job['project_id']):
            if self.blender_project!=job['project_id'] and self.blender.poll() is None:raise ValueError('Stop the managed Blender instance before switching projects.')
            self.blender.close();self.blender=None
        if not self.blender:
            ready=spool/'ready.json'
            if ready.exists():ready.unlink()
            for old in spool.glob('*.request.json'):old.replace(old.with_suffix('.abandoned'))
            atomic(spool/'settings.json',{'project':str(root),'spool':str(spool),'outputs':str(output_dir)})
            command=[self.config['native']['blender_executable'],'--factory-startup','--disable-autoexec','--python',str(pathlib.Path(__file__).parent/'native_blender.py'),'--',str(spool/'settings.json')]
            self.blender=self.process_factory(command,root,self.root/'blender.log',{'BLENDER_SYSTEM_SCRIPTS':str(pathlib.Path(self.config['native']['blender_executable']).parent/'5.2/scripts')})
            self.blender_project=job['project_id']
            for _ in range(300):
                if ready.exists():break
                if self.blender.poll() is not None:raise ValueError('Managed Blender stopped')
                time.sleep(0.1)
            else:raise ValueError('Managed Blender startup timeout')
        atomic(spool/(job['id']+'.request.json'),{'command':job['operation'],'arguments':job['arguments']})
        response=spool/(job['id']+'.response.json')
        for _ in range(10*job['arguments'].get('timeout_seconds',1800 if job['operation'] in ('execute_code','run_script') else 240)):
            if response.exists():break
            if self.blender.poll() is not None:raise ValueError('Managed Blender stopped')
            time.sleep(0.1)
        else:raise ValueError('Managed Blender operation timeout')
        data=json.loads(response.read_text(encoding='utf-8'))
        if not data.get('ok'):raise ValueError('Blender operation failed')
        job['result']={'executed':True} if job['operation'] in ('execute_code','run_script') else private_result(data['result'])
        if job['operation']=='render':
            file=output_dir/(job['id']+'.png')
            if not file.is_file():raise ValueError('Rendered artifact missing')
            job['artifacts']=[{'index':0,'filename':'blender-render.png','file':file.name}]
    def job_status(self,ident):
        with self.lock:
            if ident not in self.jobs:raise ValueError('Unknown native task.')
            self.project(self.jobs[ident]['project_id'])
            return self.public_job(self.jobs[ident])
    def artifact(self,ident,index):
        with self.lock:
            job=self.jobs.get(ident)
            if not job or job['status']!='succeeded' or type(index)is not int or not 0<=index<len(job['artifacts']):raise ValueError('Artifact is not available.')
            self.project(job['project_id'])
            file=self.root/'artifacts'/job['artifacts'][index]['file']
            if not re.fullmatch(ident+r'(?:-\d+)?\.(png|jpg|jpeg|webp|glb|blend)',file.name) or not file.is_file():raise ValueError('Invalid artifact.')
            return file
    def stop_blender(self):
        with self.lock:
            if any(j['engine']=='blender' and j['status'] in ('queued','running') for j in self.jobs.values()):raise ValueError('Wait for current Blender operations to finish.')
            if self.blender:self.blender.stop();self.blender.close();self.blender=None;self.blender_project=None
            return {'stopped':True}
