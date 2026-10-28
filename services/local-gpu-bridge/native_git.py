"""Fixed Git operations for an approved local render mirror. No shell API."""
import json,os,pathlib,re,subprocess,time,uuid,zipfile

class ProjectGit:
    BACKUPS_TO_KEEP=5
    def __init__(self,control,project,root):
        self.control=control;self.project=project;self.root=root
        self.settings=project.get('git',{})
        self.exe=control.config.get('native',{}).get('git_executable','git')
        self.remote=self.settings.get('remote','origin');self.branch=self.settings.get('branch','main')
        if not self.settings.get('enabled'):raise ValueError('Git access is disabled for this project.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',self.remote) or not isinstance(self.branch,str) or self.branch.startswith('-') or '..' in self.branch or any(c in self.branch for c in '\\:~^?*['):raise ValueError('Invalid configured Git remote or branch.')
        top=self.run(['rev-parse','--show-toplevel']).decode('utf-8').strip()
        if pathlib.Path(top).resolve()!=root.resolve():raise ValueError('Git repository must match the approved project root.')
        self.run(['check-ref-format','refs/heads/'+self.branch])
    def run(self,args,timeout=30):
        env={k:v for k,v in os.environ.items() if not k.upper().startswith('GIT_') and not any(t in k.upper() for t in ('TOKEN','SECRET','CREDENTIAL','PASSWORD','ORCA_','CLAUDE_'))}
        env.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never',GIT_OPTIONAL_LOCKS='0',SSH_ASKPASS_REQUIRE='never',GIT_PAGER='cat')
        nohooks=self.control.root/'git-no-hooks';nohooks.mkdir(exist_ok=True)
        command=[self.exe,'-c','core.hooksPath='+str(nohooks),'-c','core.fsmonitor=false','-c','core.longpaths=true','-c','submodule.recurse=false','-C',str(self.root),*args]
        for attempt in range(4):
            result=subprocess.run(command,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout,creationflags=0x08000000 if os.name=='nt' else 0)
            transient=args[0]=='reset' and result.returncode and any(s in result.stderr.lower() for s in (b'unable to unlink',b'being used by another process',b'invalid argument'))
            if not transient or attempt==3:break
            time.sleep(attempt+1)
        if result.returncode:
            import logging;logging.error('Local Git operation %s failed: %s',args[0],result.stderr.decode('utf-8',errors='replace')[-3000:])
            raise ValueError('Local Git operation failed. Check the local Git log, credentials and configured branch.')
        return result.stdout
    def names(self,args):return [p.decode('utf-8') for p in self.run(args).split(b'\0') if p]
    def status(self):
        return {'branch':self.run(['branch','--show-current']).decode().strip(),'head':self.run(['rev-parse','HEAD']).decode().strip(),'tracked_changes':len(self.names(['diff','--name-only','-z','HEAD'])),'untracked_files':len(self.names(['ls-files','--others','--exclude-standard','-z'])),'remote':self.remote,'target_branch':self.branch,'auto_pull_before_render':self.settings.get('auto_pull_before_render',False)}
    def file(self,relative):
        parts=pathlib.PurePosixPath(relative).parts
        if not parts or relative.startswith('/') or '\\' in relative or ':' in relative or any(p in ('.','..','.git') for p in parts):raise ValueError('Unsafe Git project path.')
        file=self.root.joinpath(*parts)
        for p in [file,*file.parents]:
            if p==self.root:break
            if p.is_symlink() or p.exists() and getattr(p.stat(),'st_file_attributes',0)&0x400:raise ValueError('Git mirror contains a link or reparse point.')
        if not file.resolve().is_relative_to(self.root.resolve()):raise ValueError('Git path escapes the approved project.')
        return file
    def fetch(self):
        self.run(['fetch','--no-tags','--',self.remote,'+refs/heads/'+self.branch+':refs/remotes/'+self.remote+'/'+self.branch],timeout=600)
        return self.run(['rev-parse','refs/remotes/'+self.remote+'/'+self.branch]).decode().strip()
    def prune_backups(self,current):
        # Only complete, flat backups owned by this project are eligible. Do not
        # follow links or remove unknown/incomplete folders after a failed pull.
        import logging
        folder=self.control.root/'git-backups'/self.project['id']
        for parent in (self.control.root,folder.parent,folder):
            if parent.is_symlink() or getattr(parent.stat(),'st_file_attributes',0)&0x400:return
        if not folder.resolve().is_relative_to(self.control.root.resolve()):return
        protected={current}
        protected.update(j.get('id') for j in getattr(self.control,'jobs',{}).values()
                         if j.get('status') in ('queued','running'))
        complete=[]
        for item in folder.iterdir():
            if not re.fullmatch('[a-f0-9]{32}',item.name) or item.is_symlink() or not item.is_dir() or getattr(item.stat(),'st_file_attributes',0)&0x400:continue
            files=list(item.iterdir())
            if {p.name for p in files}!={'files.zip','changes.patch','state.json'}:continue
            if any(p.is_symlink() or not p.is_file() or getattr(p.stat(),'st_file_attributes',0)&0x400 for p in files):continue
            try:
                stamp=float(json.loads((item/'state.json').read_text(encoding='utf-8'))['created_at'])
                if not stamp>0:continue
            except (ValueError,KeyError,TypeError,OSError):continue
            complete.append((stamp,item,files))
        complete.sort(key=lambda row:row[0],reverse=True)
        for _,item,files in complete[self.BACKUPS_TO_KEEP:]:
            if item.name in protected:continue
            try:
                for file in files:file.unlink()
                item.rmdir()
                self.run(['update-ref','-d','refs/local-gpu-backups/'+item.name])
            except (OSError,ValueError):logging.warning('Could not prune an old local Git backup.')
    def pull(self,ident=None):
        ident=ident or uuid.uuid4().hex
        before=self.status();target=self.fetch();ref='refs/remotes/'+self.remote+'/'+self.branch
        if before['branch']!=self.branch:raise ValueError('Local branch differs from the configured render branch. Select the matching branch locally first.')
        changed=self.names(['diff','--name-only','-z','HEAD']);untracked=self.names(['ls-files','--others','--exclude-standard','-z'])
        # Non-obstructing untracked render outputs survive reset unchanged. Do
        # not copy all of them into another backup on every render-triggered pull.
        tracked=set(self.names(['ls-files','-z']));incoming=self.names(['ls-tree','-rz','--name-only',ref]);selected=set(changed)
        # reset --hard may remove untracked/ignored files obstructing incoming paths.
        for name in incoming:
            file=self.file(name)
            if name not in tracked and file.is_file():selected.add(name)
            if file.is_dir():
                for item in file.rglob('*'):
                    relative=item.relative_to(self.root).as_posix();self.file(relative)
                    if item.is_file():selected.add(relative)
            for parent in file.parents:
                if parent==self.root:break
                if parent.is_file():selected.add(parent.relative_to(self.root).as_posix())
        if before['head']==target and not changed:return {'updated':False,'head':target,'tracked_changes_discarded':0}
        folder=self.control.root/'git-backups'/self.project['id']/ident;folder.mkdir(parents=True,exist_ok=False)
        files=[];total=0
        for name in sorted(selected):
            file=self.file(name)
            if file.is_file():
                total+=file.stat().st_size;files.append((name,file))
                if total>2*1024**3:raise ValueError('Local Git backup exceeds 2 GB. Review the local files before updating.')
        with zipfile.ZipFile(folder/'files.zip','w',zipfile.ZIP_STORED) as archive:
            for name,file in files:archive.write(file,name)
        (folder/'changes.patch').write_bytes(self.run(['diff','--binary','HEAD']))
        (folder/'state.json').write_text(json.dumps({'previous_head':before['head'],'target_head':target,'branch':self.branch,'changed':changed,'untracked':untracked,'backup_files':[name for name,_ in files],'created_at':time.time()}),encoding='utf-8')
        self.run(['update-ref','refs/local-gpu-backups/'+ident,before['head']])
        # Root and every incoming path were checked before this destructive operation.
        self.run(['reset','--hard',ref],timeout=300)
        if self.run(['rev-parse','HEAD']).decode().strip()!=target:raise ValueError('Git update could not be verified.')
        self.prune_backups(ident)
        return {'updated':True,'head':target,'previous_head':before['head'],'backup_id':ident,'tracked_changes_discarded':len(changed),'untracked_files_preserved_unless_obstructing_remote':True}

def git_for(control,project,root):return ProjectGit(control,project,root)
