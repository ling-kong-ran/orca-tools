"""Host-local admission for managed editors and short-lived render jobs."""
import ctypes
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import threading
import time


def resource_slots():
    """Estimate additional editors from currently available memory (GiB)."""
    if os.name != 'nt':
        return None
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
            (key, ctypes.c_uint64) for key in ('physical','free','commit','commit_free','virtual','virtual_free','extended')]
    memory = MemoryStatus()
    memory.size = ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        return None
    gib = 1024 ** 3
    slots = min((memory.free - 2*gib) // (2*gib), (memory.commit_free - 2*gib) // (4*gib))
    if slots <= 0:
        return 0
    # Only read aggregate free memory. Never invoke a PATH-provided executable.
    for exe in (Path(os.environ['SystemRoot'])/'System32/nvidia-smi.exe',
                Path(os.environ['ProgramFiles'])/'NVIDIA Corporation/NVSMI/nvidia-smi.exe'):
        if exe.is_file():
            try:
                result = subprocess.run([str(exe),'--query-gpu=memory.free','--format=csv,noheader,nounits'],
                    capture_output=True, text=True, timeout=2, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                free_mib = min(int(line.strip()) for line in result.stdout.splitlines())
                return max(0, min(slots, (free_mib - 512) // 1536))
            except (OSError, ValueError, subprocess.SubprocessError):
                continue
    # A host without dedicated GPU telemetry can still budget physical and commit memory.
    return max(0, slots)


class RenderCapacity:
    def __init__(self, maximum=2, probe=resource_slots):
        self.maximum = self.validate(maximum)
        self.probe = probe
        self.condition = threading.Condition()
        self.busy = set()
        self.residents = {}
        self.exclusive_jobs = {}
        self.active = set()
        self.warming = {}
        self.sample_at = 0
        self.sample = None

    @staticmethod
    def validate(value):
        if type(value) is not int or not 1 <= value <= 32:
            raise ValueError('Render concurrency must be an integer from 1 to 32.')
        return value

    def configure(self, maximum):
        with self.condition:
            self.maximum = self.validate(maximum)
            self.condition.notify_all()

    def occupied(self, root):
        with self.condition:
            return root in self.busy or any(
                key[1] == root and process.poll() is None for key, process in self.residents.items()
            )

    def counts(self):
        # Caller holds the condition. A process may have exited between requests.
        self.residents = {key: process for key, process in self.residents.items() if process.poll() is None}
        self.exclusive_jobs = {root:job for root,job in self.exclusive_jobs.items() if job.poll() is None}
        used = self.active | self.residents.keys()
        now = time.monotonic()
        if now >= self.sample_at:
            self.sample = self.probe()
            self.sample_at = now + 2
        self.warming = {key: until for key, until in self.warming.items() if key in used and until > now}
        if self.sample is None:
            limit = min(1, self.maximum)
        else:
            limit = min(self.maximum, len(used) + max(0, self.sample - len(self.warming)))
        return used, limit

    def status(self):
        with self.condition:
            used, limit = self.counts()
            return {'maximum':self.maximum, 'effective':limit, 'in_use':len(used)}

    def track(self, key, process, *, exclusive=False):
        with self.condition:
            self.residents[key] = process
            if exclusive:
                self.exclusive_jobs[key[1]] = process

    def project_available(self, root):
        if root in self.busy:
            return False
        job = self.exclusive_jobs.get(root)
        if job is None:
            return True
        if job.poll() is None:
            return False
        del self.exclusive_jobs[root]
        return True

    @contextmanager
    def operation(self, root, key=None, *, queue=False, cancelled=lambda:False, busy_timeout=None):
        deadline = None if busy_timeout is None else time.monotonic() + busy_timeout
        with self.condition:
            while True:
                if cancelled():
                    raise ValueError('Operation cancelled.')
                used, limit = self.counts() if key is not None else ((), 0)
                available = key is None or key in used or len(used) < limit
                if self.project_available(root) and available:
                    break
                if not available and not queue:
                    raise ValueError('Render capacity is busy. Retry after a project stops or resources become available.')
                if deadline is not None and time.monotonic() >= deadline:
                    raise ValueError('A project operation is still in flight. Retry after it finishes.')
                self.condition.wait(1)
            self.busy.add(root)
            if key is not None:
                if key not in used:
                    # New processes may not have allocated their working set at the latest sample.
                    self.warming[key] = time.monotonic() + 15
                self.active.add(key)
        try:
            yield
        finally:
            with self.condition:
                self.busy.remove(root)
                self.active.discard(key)
                self.condition.notify_all()
