"""Install the standalone upstream Tripo bundle; no Codex installation or service required."""
import argparse,io,json,os,pathlib,re,shutil,tarfile,tempfile,urllib.request

REPOSITORY='Ador-able/tripo-studio-mcp'
def request(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Orca-Tools-Tripo-Installer'}),timeout=90)

def install_bundle(source, destination):
    source=pathlib.Path(source).resolve();destination=pathlib.Path(destination).resolve()
    for name in ('mcp/bootstrap.mjs','mcp/server.mjs','.codex-plugin/plugin.json'):
        if not (source/name).is_file():raise ValueError('The compiled upstream Tripo bundle is incomplete.')
    version=json.loads((source/'.codex-plugin/plugin.json').read_text(encoding='utf-8'))['version']
    if not re.fullmatch(r'[A-Za-z0-9.+_-]{1,100}',version):raise ValueError('Unsafe bundle version.')
    destination.mkdir(parents=True,exist_ok=True);target=destination/version
    if target.exists():
        # An identical install is reusable; never overwrite a bundle a backend may be using.
        if (target/'mcp/server.mjs').read_bytes() == (source/'mcp/server.mjs').read_bytes():return target
        raise ValueError('A different bundle already uses this version. Stop its backend and choose a new cache directory.')
    if any(p.is_symlink() for p in source.rglob('*')):raise ValueError('Bundle links are not allowed.')
    with tempfile.TemporaryDirectory(prefix='.install-',dir=destination) as temporary:
        staged=pathlib.Path(temporary)/'bundle';shutil.copytree(source,staged)
        if any(p.is_symlink() for p in staged.rglob('*')):raise ValueError('Bundle links are not allowed.')
        staged.rename(target)
    return target

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=pathlib.Path,help='Existing compiled upstream bundle, or omit to download from GitHub')
    p.add_argument('--ref',default='main',help='Upstream ref; resolved to a commit before downloading')
    p.add_argument('--destination',type=pathlib.Path,default=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()/'AppData/Local'))/'LocalGpuBridge/tripo/plugins')
    a=p.parse_args()
    if a.bundle:target=install_bundle(a.bundle,a.destination)
    else:
        from urllib.parse import quote
        with request('https://api.github.com/repos/'+REPOSITORY+'/commits/'+quote(a.ref,safe='')) as r:commit=json.load(r)['sha']
        if not re.fullmatch(r'[0-9a-f]{40}',commit):raise ValueError('Invalid upstream commit.')
        with request('https://codeload.github.com/'+REPOSITORY+'/tar.gz/'+commit) as r:data=r.read(200*1024**2+1)
        if len(data)>200*1024**2:raise ValueError('Upstream archive exceeds 200 MB.')
        with tempfile.TemporaryDirectory(prefix='orca-tripo-install-') as temporary:
            source=pathlib.Path(temporary)
            with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
                prefix='tripo-studio-mcp-'+commit+'/plugins/tripo-studio-mcp/'
                for member in archive:
                    if not member.name.startswith(prefix) or not member.isfile():continue
                    relative=pathlib.PurePosixPath(member.name[len(prefix):])
                    if relative.is_absolute() or any(x in ('..','') for x in relative.parts):raise ValueError('Unsafe archive path.')
                    output=source.joinpath(*relative.parts);output.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as stream:output.write_bytes(stream.read())
            (source/'bundle-source.json').write_text(json.dumps({'repository':REPOSITORY,'commit':commit}),encoding='utf-8')
            target=install_bundle(source,a.destination)
    print(json.dumps({'installed':str(target),'codex_required':False}))

if __name__=='__main__':main()
