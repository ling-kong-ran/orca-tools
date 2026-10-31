"""Bounded Blender diagnostics and script values for the remote boundary."""
import json,traceback
from remote_privacy import remote_json

class Capture:
    def __init__(self):self.text='';self.truncated=False
    def write(self,value):
        value=str(value);left=8192-len(self.text)
        self.text+=value[:max(0,left)];self.truncated|=len(value)>left
        return len(value)
    def flush(self):pass

def bounded(value,depth=0):
    if depth>8:return '[depth limit]'
    if isinstance(value,dict):return {str(k)[:120]:bounded(v,depth+1) for k,v in list(value.items())[:100]}
    if isinstance(value,(list,tuple)):return [bounded(v,depth+1) for v in value[:100]]
    if isinstance(value,str):return value[:8192]
    if value is None or type(value) in (bool,int,float):return value
    return '[non-JSON value]'

def result(value):
    value=remote_json(bounded(value))
    if len(json.dumps(value,ensure_ascii=False))>65536:return {'truncated':True,'message':'Result exceeds 64 KB. Save structured project data and read it in smaller sections.'}
    return value

def diagnostic(error,root):
    frames=[]
    for frame in traceback.extract_tb(error.__traceback__)[-5:]:
        import pathlib
        file=pathlib.Path(frame.filename)
        try:name=file.resolve().relative_to(root).as_posix()
        except ValueError:name='<script>' if frame.filename=='<remote-blender>' else '<library>'
        frames.append({'file':name,'line':frame.lineno,'function':frame.name})
    return result({'type':type(error).__name__,'message':str(error)[:2000],'line':getattr(error,'lineno',None),'frames':frames})
