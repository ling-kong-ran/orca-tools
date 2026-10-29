"""Qualified, typed adapters for commands flattened by the official MCP server."""
import json
import pathlib
import re
import subprocess


def field(kind, description): return {'type':kind, 'description':description}


def tool(name, description, properties=None, required=None):
    return {'name':name, 'description':description, 'inputSchema':{'type':'object',
        'properties':properties or {}, 'required':required or [], 'additionalProperties':False}}


TOOLS = [
    tool('console.get', 'Read compile errors and console entries with a UTC cursor; host metadata is filtered.', {
        'tail':field('integer','Most recent entries, 1..200.'),
        'level':{'type':'string','enum':['log','warn','error']},
        'since':field('integer','Previous response cursor.'),
        'since_session':field('string','Previous response session.')}),
    tool('console.status','Read compilation and console error counts.'),
    tool('test.list','List project tests.', {'mode':{'type':'string','enum':['all','editor','playmode']}}),
    tool('test.run','Start project tests asynchronously. Poll test.status; execution is never retried.', {
        'mode':{'type':'string','enum':['all','editor','playmode']},
        'filter':field('string','Optional test name/assembly/category filter.'),
        'filter_type':{'type':'string','enum':['testName','assembly','category']},
        'include_explicit':field('boolean','Include explicit tests.')}),
    tool('test.status','Read async test results, including failures.'),
    tool('build.run','Validate or start an async Player build. Poll build.status. Outputs stay under this project Builds/.', {
        'target':field('string','Installed BuildTarget, e.g. StandaloneWindows64.'),
        'outputPath':field('string','Project-relative path under Builds/, e.g. Builds/Game.exe.'),
        'profileName':field('string','Optional existing Build Profile.'),
        'options':{'type':'array','items':{'type':'string'}},
        'scenes':{'type':'array','items':{'type':'string'},'description':'Existing Assets/*.unity paths.'},
        'confirm':field('boolean','Must be true to build.'),
        'dry_run':field('boolean','Validate only.')}),
    tool('build.status','Read build status and report, including errors.'),
    tool('package.list','List installed packages; does not query host diagnostics.'),
    tool('package.search','Query the configured package registry using Package Manager.', {
        'query':field('string','Package name/search term.'), 'offline':field('boolean','Search cache only.')}, ['query']),
    tool('package.add','Add a registry package by exact name@version, then poll package.status. Git/file URLs are not accepted.', {
        'identifier':field('string','Registry package name@version, e.g. com.unity.entities@1.5.0.'),
        'confirm':field('boolean','Must be true to add.'), 'dry_run':field('boolean','Validate only.')}, ['identifier']),
    tool('package.status','Read last package operation status.')
]
BY_NAME = {t['name']:t for t in TOOLS}


def invoke(control, project_id, name, arguments):
    """No user command fragments: fixed CLI verb, fixed group, typed --key=value tokens."""
    from native_control import inside, private_text, PRIVATE_KEYS
    from remote_privacy import remote_json
    spec=BY_NAME[name]['inputSchema']; args=dict(arguments)
    if set(args)-set(spec['properties']) or set(spec['required'])-set(args):
        raise ValueError('Unexpected or missing Unity parameters.')
    for key, value in args.items():
        schema=spec['properties'][key]; kind=schema['type']
        valid = (type(value) is bool if kind=='boolean' else type(value) is int if kind=='integer'
            else isinstance(value,str) if kind=='string' else isinstance(value,list) and all(isinstance(v,str) for v in value))
        if not valid or ('enum' in schema and value not in schema['enum']): raise ValueError('Invalid Unity parameter: '+key)
    _, root=control.project(project_id)
    if 'tail' in args and not 1<=args['tail']<=200: raise ValueError('Console tail must be 1..200.')
    if name=='test.run': args.update(async_tests=True, timeout=60)
    if name=='package.list': args.update(scope='installed')
    if name=='package.search': args.update(timeout=30)
    if name=='package.add':
        if not re.fullmatch(r'[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+@[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?', args['identifier']):
            raise ValueError('Use an exact registry package name@version; URLs and local files are not exposed.')
        args.update(wait=False, timeout=60)
    if name=='build.run':
        output=args.setdefault('outputPath','Builds/Game.exe')
        # Build executables are valid outputs, but must not overwrite project source.
        path=pathlib.PurePosixPath(output)
        if '\\' in output or ':' in output or path.is_absolute() or len(path.parts)<2 or path.parts[0]!='Builds' or any(p in ('.','..') for p in output.split('/')):
            raise ValueError('Build output must be a project-relative path under Builds/.')
        parent=pathlib.PurePosixPath(output).parent.as_posix()
        inside(root,parent)
        target=root/output
        if target.exists() and (target.is_symlink() or getattr(target.stat(),'st_file_attributes',0)&0x400):
            raise ValueError('Linked build outputs are not exposed.')
        for scene in args.get('scenes',[]):
            if not scene.startswith('Assets/') or not scene.endswith('.unity') or not inside(root,scene).is_file():
                raise ValueError('Use an existing project Assets/*.unity scene.')
        args.update(timeout=60)
    command=[control.settings()['unity_cli_executable'],'command',*name.split('.'),
        '--project-path',str(root),'--result-only','--format','json','--timeout','65']
    for key,value in args.items():
        encoded=json.dumps(value,separators=(',',':')) if not isinstance(value,str) else value
        command.append('--'+key+'='+encoded)
    try:
        result=subprocess.run(command,cwd=root,env=control.environment(),capture_output=True,text=True,
            encoding='utf-8',timeout=75,creationflags=0x08000000)
        data=json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise ValueError('Unity command timed out. Inspect its status before repeating; it may still be running.') from None
    except (ValueError,OSError):
        raise ValueError('Unity command did not return JSON. Check the local Editor log.') from None
    # Preserve structured command failures and actual errors instead of replacing
    # them with a generic failure. The existing remote boundary filters once more.
    def filtered(value):
        if isinstance(value,dict):
            return {k:filtered(v) for k,v in value.items() if k.lower() not in PRIVATE_KEYS-{'version','platform','log'}}
        if isinstance(value,list): return [filtered(v) for v in value[:1000]]
        if isinstance(value,str): return private_text(value)[:16000]
        return value
    return {'content':[{'type':'text','text':json.dumps(filtered(remote_json(data)),ensure_ascii=False)}],
        'isError':result.returncode!=0}
