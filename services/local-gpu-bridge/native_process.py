"""Fixed native executables, no shell, one-process Windows jobs and egress guard."""
import ctypes,ctypes.wintypes as w,ipaddress,json,os,pathlib,subprocess,threading
BLOCKED_ADDRESSES={'0.0.0.0/2','64.0.0.0/3','96.0.0.0/6','100.0.0.0/10','100.128.0.0/9','101.0.0.0/8','102.0.0.0/7','104.0.0.0/5','112.0.0.0/5','120.0.0.0/6','124.0.0.0/7','126.0.0.0/8','128.0.0.0/1','::/1','8000::/1'}

class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_=[('PerProcessUserTimeLimit',ctypes.c_int64),('PerJobUserTimeLimit',ctypes.c_int64),('LimitFlags',w.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
class IO_COUNTERS(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_=[('BasicLimitInformation',JOBOBJECT_BASIC_LIMIT_INFORMATION),('IoInfo',IO_COUNTERS),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]

class EgressGuard:
    def __init__(self,config):self.config=config;self.lock=threading.Lock()
    def ready(self,engine):
        if os.name!='nt':return False
        value=self.config.get('server_executables',{}).get(engine[7:]) if engine.startswith('server-') else self.config.get(engine.replace('-','_')+'_executable')
        if not value:return False
        exe=pathlib.Path(value)
        if not engine.startswith('server-') and not exe.is_file():return False
        name='Local GPU Bridge - '+engine+' - block external network'
        # INetFwPolicy2 permits a standard-user read of the active firewall.
        # The NetSecurity CIM rule provider requires elevation on this machine.
        script="$ErrorActionPreference='Stop'; $policy=New-Object -ComObject HNetCfg.FwPolicy2; foreach($profile in @(1,2,4)){if(-not $policy.FirewallEnabled($profile)){exit 3}}; if($policy.LocalPolicyModifyState -ne 0){exit 4}; $r=$policy.Rules.Item('"+name+"'); if(-not $r.Enabled -or $r.Direction -ne 2 -or $r.Action -ne 0 -or $r.Protocol -ne 256 -or ($r.Profiles -band 7) -ne 7 -or $r.LocalAddresses -ne '*' -or $r.InterfaceTypes -ne 'All' -or $r.ServiceName){exit 2}; [pscustomobject]@{program=$r.ApplicationName;remote=@($r.RemoteAddresses -split ',')}|ConvertTo-Json -Compress"
        try:
            p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=15,creationflags=0x08000000)
            if p.returncode:return False
            value=json.loads(p.stdout)
            # Allow only IPv4 loopback and Tailscale; IPv6 entirely denied.
            expected=BLOCKED_ADDRESSES
            remote={str(ipaddress.ip_network(s.strip(),strict=False)) for s in value['remote']}
            return pathlib.Path(value['program']).resolve()==exe.resolve() and remote==expected
        except (OSError,ValueError,subprocess.TimeoutExpired):return False
    def require(self,engine):
        if not self.ready(engine):raise ValueError('Native network isolation is not ready. Complete the local firewall setup from the management page first.')

class ManagedProcess:
    def __init__(self,args,cwd,log,env=None,show_window=False,process_limit=1):
        if type(process_limit) is not int or not 1<=process_limit<=128:raise ValueError('Invalid managed process limit.')
        if os.name!='nt':raise ValueError('Native rendering currently requires Windows.')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.restype=w.HANDLE;kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR]
        kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        kernel.TerminateJobObject.argtypes=[w.HANDLE,w.UINT]
        job=kernel.CreateJobObjectW(None,None)
        limits=JOBOBJECT_EXTENDED_LIMIT_INFORMATION();limits.BasicLimitInformation.LimitFlags=0x2000|0x8
        limits.BasicLimitInformation.ActiveProcessLimit=process_limit
        if not job or not kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            if job:kernel.CloseHandle(job)
            raise ValueError('Could not create the isolated native process job.')
        self.kernel=kernel;self.job=job;self.output=open(log,'ab',buffering=0)
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=4 if show_window else 0
        clean={k:v for k,v in os.environ.items() if not any(t in k.upper() for t in ('TOKEN','SECRET','API_KEY','CREDENTIAL','PASSWORD','ORCA_','CLAUDE_'))}
        clean.update(env or {});clean['PYTHONNOUSERSITE']='1';clean.pop('PYTHONPATH',None)
        try:
            # Start suspended so no project code can spawn before containment.
            self.process=subprocess.Popen(args,cwd=cwd,env=clean,stdin=subprocess.DEVNULL,stdout=self.output,stderr=self.output,shell=False,startupinfo=startup,creationflags=0x4|0x08000000)
            if not kernel.AssignProcessToJobObject(job,w.HANDLE(int(self.process._handle))):raise OSError('Process containment failed')
            # Popen closes its thread handle. NtResumeProcess resumes the suspended process.
            ntdll=ctypes.WinDLL('ntdll');ntdll.NtResumeProcess.argtypes=[w.HANDLE];ntdll.NtResumeProcess.restype=ctypes.c_long
            if ntdll.NtResumeProcess(w.HANDLE(int(self.process._handle)))!=0:raise OSError('Could not resume contained process')
        except Exception:
            if hasattr(self,'process'):self.process.kill();self.process.wait(timeout=5)
            self.close();raise ValueError('The contained native application could not start.') from None
    def poll(self):return self.process.poll()
    def show_without_focus(self):
        # Only restore top-level windows owned by this managed editor process.
        user32=ctypes.WinDLL('user32',use_last_error=True)
        callback=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        user32.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
        user32.ShowWindowAsync.argtypes=[w.HWND,ctypes.c_int]
        @callback
        def restore(window,_):
            owner=w.DWORD();user32.GetWindowThreadProcessId(window,ctypes.byref(owner))
            if owner.value==self.process.pid:user32.ShowWindowAsync(window,4)
            return True
        user32.EnumWindows.argtypes=[callback,w.LPARAM]
        user32.EnumWindows(restore,0)
    def wait(self,timeout=None):return self.process.wait(timeout)
    def stop(self):
        if self.job:self.kernel.TerminateJobObject(self.job,1)
    def close(self):
        if self.job:self.kernel.CloseHandle(self.job);self.job=None
        self.output.close()
