"""Project script tasks and an allowlisted process broker for Godot galleries.

Renderer processes still cannot spawn arbitrary children. Gallery calls are
redirected to fixed Godot/Go/game-server operations owned by this job.
"""
import hashlib,json,os,pathlib,re,shutil,subprocess,time

def go_build_environment(native):
    clean={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ('TOKEN','SECRET','KEY','CREDENTIAL','PASSWORD','ORCA_','CLAUDE_'))}
    clean.update({'CGO_ENABLED':'0','GOPROXY':'off','GOSUMDB':'off','GOTOOLCHAIN':'local','GOFLAGS':'','GOENV':'off','GOWORK':'off','GOROOT':native['go_root']})
    # GOENV=off also hides the user's cache locations. Keep approved local paths
    # explicit so offline builds can find dependencies already on this computer.
    for setting,variable in [('go_path','GOPATH'),('go_module_cache','GOMODCACHE'),('go_build_cache','GOCACHE')]:
        if native.get(setting):
            value=pathlib.Path(native[setting])
            if not value.is_absolute():raise ValueError('Go cache settings must use absolute local paths.')
            clean[variable]=str(value)
    return clean

def arguments(value):
    if not isinstance(value,list) or len(value)>256 or any(not isinstance(s,str) or len(s)>8192 or '\0' in s for s in value):
        raise ValueError('user_args must contain at most 256 text arguments.')
    return value

def script_request(control,project,root,operation,args,allow_missing=False):
    from native_control import inside
    if not project.get('allow_scripts',False):raise ValueError('Project script access is disabled on the local management page.')
    allowed={'script','user_args','timeout_seconds','output_paths','project_subdir','headless'}
    if set(args)-allowed:raise ValueError('Unexpected project script fields.')
    file=inside(root,args.get('script','tools/shots.gd'))
    if file.suffix!='.gd' or (not file.is_file() and not allow_missing) or file.is_dir():raise ValueError('Select an existing project .gd script.')
    arguments(args.get('user_args',[]))
    timeout=args.get('timeout_seconds',1800)
    if type(timeout)is not int or not 10<=timeout<=7200:raise ValueError('Script timeout must be 10 to 7200 seconds.')
    if not isinstance(args.get('output_paths',[]),list):raise ValueError('output_paths must be a list.')
    for path in args.get('output_paths',[]):inside(root,path)
    if 'headless' in args and type(args['headless'])is not bool:raise ValueError('headless must be boolean.')
    if args.get('project_subdir'):inside(root,args['project_subdir'])
    return file

SHIM='''
func _bridge_call(kind: String, data: Dictionary) -> Dictionary:
	var folder := OS.get_environment("LOCAL_GPU_PROCESS_QUEUE")
	var key := str(Time.get_ticks_usec())
	var request := folder.path_join(key + ".request.json")
	var f := FileAccess.open(request + ".tmp", FileAccess.WRITE)
	f.store_string(JSON.stringify({"kind": kind, "data": data}))
	f.close()
	DirAccess.rename_absolute(request + ".tmp", request)
	var response := folder.path_join(key + ".response.json")
	var deadline := Time.get_ticks_msec() + 600000
	while not FileAccess.file_exists(response):
		if Time.get_ticks_msec() > deadline:
			return {"code": 1, "pid": -1, "running": false}
		OS.delay_msec(25)
	var result = JSON.parse_string(FileAccess.get_file_as_string(response))
	DirAccess.remove_absolute(response)
	return result if result is Dictionary else {}
func _bridge_execute(executable: String, argv: Variant, output: Array = [], _stderr: bool = false) -> int:
	var r := _bridge_call("execute", {"executable": executable, "args": argv})
	output.append(str(r.get("output", "")))
	return int(r.get("code", 1))
func _bridge_create(executable: String, argv: Variant, _open_console: bool = false) -> int:
	return int(_bridge_call("create", {"executable": executable, "args": argv}).get("pid", -1))
func _bridge_running(pid: int) -> bool:
	return bool(_bridge_call("running", {"pid": pid}).get("running", false))
func _bridge_kill(pid: int) -> int:
	return int(_bridge_call("kill", {"pid": pid}).get("code", 1))
'''

def adapt_script(text):
    for old,new in [('OS.execute(', '_bridge_execute('),('OS.create_process(', '_bridge_create('),('OS.is_process_running(', '_bridge_running('),('OS.kill(', '_bridge_kill(')]:text=text.replace(old,new)
    # Device model is unnecessary in a shareable gallery manifest.
    if 'func _probe() -> String:' in text:
        text=re.sub(r'func _probe\(\) -> String:.*?(?=\nfunc )','func _probe() -> String:\n\treturn "hardware GPU"\n\n',text,flags=re.S)
    return text+'\n'+SHIM

class ProcessBroker:
    def __init__(self,control,job,root,folder):
        self.control=control;self.job=job;self.root=root;self.folder=folder;self.children={};self.serial=0;self.server_alias=None
    def close(self):
        for child in self.children.values():
            if child.poll() is None:child.stop()
            child.close()
    def start(self,exe,args,env=None):
        self.serial+=1
        p=self.control.process_factory([str(exe),*args],self.root,self.folder/('child-'+str(self.serial)+'.log'),env)
        self.children[self.serial]=p
        return self.serial
    def execute(self,exe,args):
        native=self.control.config['native'];godot=pathlib.Path(native['godot_executable'])
        if exe=='git':
            # The local render mirror has no synchronized Git history.
            return {'code':1,'output':''}
        if exe=='go':
            if len(args)!=6 or args[0]!='-C' or pathlib.Path(args[1]).resolve()!=(self.root/'server').resolve() or args[2:4]!=['build','-o'] or args[5]!='./cmd/gameserver':raise ValueError('Only the project game-server build is exposed.')
            server=native.get('server_executables',{}).get(self.job['project_id'])
            if not server:raise ValueError('The project has no configured managed game server.')
            self.control.guard.require('server-'+self.job['project_id']);self.control.guard.require('go')
            target=pathlib.Path(server);target.parent.mkdir(parents=True,exist_ok=True)
            # Fixed trusted compiler, no cgo, downloads, toolchain switch or toolexec.
            clean=go_build_environment(native)
            with (self.folder/'build.log').open('wb') as log:
                p=subprocess.run([native['go_executable'],'-C',str(self.root/'server'),'build','-o',str(target),'./cmd/gameserver'],env=clean,stdin=subprocess.DEVNULL,stdout=log,stderr=log,timeout=300,creationflags=0x08000000)
            if p.returncode:return {'code':p.returncode,'output':'Managed game-server build failed; inspect the local build log.'}
            self.server_alias=args[4];return {'code':0,'output':''}
        if pathlib.Path(exe).resolve()!=godot.resolve():raise ValueError('Executable is not exposed.')
        self.control.guard.require('godot');pid=self.start(godot,args)
        try:return {'code':self.children[pid].wait(timeout=300),'output':''}
        except subprocess.TimeoutExpired:self.children[pid].stop();return {'code':1,'output':''}
    def service(self):
        for request in sorted(self.folder.glob('*.request.json')):
            try:
                if request.stat().st_size>65536:raise ValueError('Process request exceeds limit.')
                value=json.loads(request.read_text(encoding='utf-8'));kind=value['kind'];data=value['data']
                if kind in ('running','kill'):
                    p=self.children.get(data.get('pid'))
                    if kind=='running':result={'running':p is not None and p.poll() is None}
                    elif p:
                        p.stop();result={'code':0}
                    else:result={'code':1}
                else:
                    exe=data['executable'];argv=arguments(data['args'])
                    if kind=='execute':result=self.execute(exe,argv)
                    elif kind=='create':
                        native=self.control.config['native'];godot=pathlib.Path(native['godot_executable'])
                        if pathlib.Path(exe).resolve()==godot.resolve():self.control.guard.require('godot');managed=godot
                        elif exe==self.server_alias and self.server_alias:
                            self.control.guard.require('server-'+self.job['project_id']);managed=pathlib.Path(native['server_executables'][self.job['project_id']])
                        else:raise ValueError('Executable is not exposed.')
                        result={'pid':self.start(managed,argv)}
                    else:raise ValueError('Process operation is not exposed.')
            except Exception:
                import logging;logging.exception('Gallery process request failed');result={'code':1,'pid':-1,'running':False,'output':'Managed process request failed. Inspect the local log.'}
            response=request.with_name(request.name.replace('.request.json','.response.json'))
            from native_control import atomic
            atomic(response,result);request.unlink()

def run_script(control,job,project,root,outputs):
    from native_control import inside,digest
    args=job['arguments'];script=script_request(control,project,root,'script',args)
    folder=control.root/'runs'/job['id'];folder.mkdir(parents=True,exist_ok=True)
    queue=folder/'processes';queue.mkdir(exist_ok=True)
    selected=args.get('output_paths',['docs/shots']);before={}
    def files():
        result=[]
        for relative in selected:
            path=inside(root,relative)
            for file in (path.rglob('*') if path.is_dir() else [path]):
                if file.is_file() and file.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.glb','.blend'}:
                    inside(root,file.relative_to(root).as_posix());result.append(file)
                    if len(result)>1000:raise ValueError('Select fewer than 1000 output artifacts.')
        return sorted(set(result))
    for file in files():before[file]=(file.stat().st_mtime_ns,file.stat().st_size,digest(file))
    adapted=folder/'project-script.gd';adapted.write_text(adapt_script(script.read_text(encoding='utf-8-sig')),encoding='utf-8')
    path=inside(root,args['project_subdir']) if args.get('project_subdir') else root
    # Resource paths in project scripts remain relative to the original project.
    cmd=[control.config['native']['godot_executable']]
    if args.get('headless',script.name=='shots.gd'):cmd.append('--headless')
    cmd+=['--path',str(path),'--audio-driver','Dummy','--position','-32000,-32000','--script',str(adapted),'--',*args.get('user_args',[])]
    broker=ProcessBroker(control,job,root,queue);process=control.process_factory(cmd,root,folder/'application.log',{'LOCAL_GPU_PROCESS_QUEUE':str(queue)})
    timed_out=False
    try:
        deadline=time.monotonic()+args.get('timeout_seconds',1800)
        while process.poll() is None:
            if time.monotonic()>deadline:
                timed_out=True;process.stop();break
            broker.service();time.sleep(.05)
        exit_code=process.poll()
    finally:
        if process.poll() is None:process.stop()
        process.close();broker.close()
    artifacts=[]
    for file in files():
        if before.get(file)==(file.stat().st_mtime_ns,file.stat().st_size,digest(file)):continue
        index=len(artifacts);target=outputs/(job['id']+'-'+str(index)+file.suffix.lower());shutil.copyfile(file,target)
        artifacts.append({'index':index,'filename':file.relative_to(root).as_posix(),'file':target.name})
    complete=not timed_out and exit_code==0
    job['artifacts']=artifacts;job['result']={'script_completed':complete,'artifact_count':len(artifacts)}
    if not complete:
        failed=[]
        with (folder/'application.log').open('r',encoding='utf-8',errors='replace') as log:
            for line in log:
                match=re.match(r'^\s*FAIL ([A-Za-z0-9_/-]{1,180}):',line)
                if match and match[1] not in failed and len(failed)<64:failed.append(match[1])
        job['result'].update(partial_success=bool(artifacts),exit_code=exit_code,
                             timed_out=timed_out,failed_screenshots=failed)
        if not artifacts:raise ValueError('Project script timed out.' if timed_out else 'Project script failed. Inspect the local log.')
