"""Local-only workflow administration. Never served to the VPS."""
import argparse, json, os, pathlib, re, sys
from bridge import atomic_json, validate_workflow

def default_root():
    return pathlib.Path(os.environ.get('LOCALAPPDATA') or pathlib.Path.home()/'AppData/Local')/'LocalGpuBridge'

def main():
    parser=argparse.ArgumentParser(description='Manage locally approved GPU workflows')
    parser.add_argument('--data-dir',default=str(default_root()))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    imp=sub.add_parser('import',help='Approve an API-format workflow on this computer')
    imp.add_argument('file');imp.add_argument('--id');imp.add_argument('--name');imp.add_argument('--description',default='')
    imp.add_argument('--expose',action='append',default=[],help='Expose one literal parameter, e.g. prompt=6.text or seed=3.seed')
    imp.add_argument('--replace',action='store_true')
    args=parser.parse_args();root=pathlib.Path(args.data_dir)
    if args.command=='list':
        for file in sorted((root/'workflows').glob('*.json')):
            value=validate_workflow(json.loads(file.read_text(encoding='utf-8')))
            print(json.dumps({k:value.get(k,{}) for k in ('id','name','description','parameters')},ensure_ascii=False))
        return
    value=json.loads(pathlib.Path(args.file).read_text(encoding='utf-8-sig'))
    if isinstance(value,dict) and 'prompt' in value and 'id' in value:
        workflow=value
        if args.id: workflow['id']=args.id
        if args.name: workflow['name']=args.name
    else:
        if not args.id: raise ValueError('--id is required when importing a raw API-format graph.')
        workflow={'id':args.id,'name':args.name or args.id,'description':args.description,'prompt':value,'parameters':{}}
    validate_workflow(workflow)
    for item in args.expose:
        match=re.fullmatch(r'([a-z0-9][a-z0-9_-]{0,63})=([^.]+)\.(.+)',item)
        if not match: raise ValueError('Use --expose name=node_id.input_name')
        name,node,field=match.groups();current=workflow['prompt'][node]['inputs'][field]
        if type(current) not in (str,int,float,bool): raise ValueError('Only literal text, numbers and booleans can be exposed.')
        kind={str:'string',int:'integer',float:'number',bool:'boolean'}[type(current)]
        spec={'node':node,'input':field,'type':kind}
        if kind=='string':spec['maxLength']=16000
        if field in ('seed','noise_seed'):spec.update(minimum=0,maximum=2**53-1)
        if field=='steps':spec.update(minimum=1,maximum=150)
        if field in ('width','height'):spec.update(minimum=64,maximum=4096)
        workflow.setdefault('parameters',{})[name]=spec
    validate_workflow(workflow);target=root/'workflows'/(workflow['id']+'.json')
    if target.exists() and not args.replace:raise ValueError('Workflow already exists. Use --replace only if you intend to update it.')
    atomic_json(target,workflow)
    print(json.dumps({'imported':workflow['id'],'name':workflow.get('name'),'parameters':workflow.get('parameters',{}),'file':str(target)},ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as error:print(str(error),file=sys.stderr);sys.exit(1)
