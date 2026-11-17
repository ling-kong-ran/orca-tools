"""Provision dedicated offline media executables; run --write-config with Bridge stopped.

Install project npm dependencies and Playwright headless Chromium separately.
Normal Python/Node/FFmpeg installations are never firewall-blocked or modified.
"""
import argparse,hashlib,json,os,pathlib,shutil,sys,uuid

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--chromium',required=True)
    parser.add_argument('--config',default=str(pathlib.Path(os.environ['LOCALAPPDATA'])/'LocalGpuBridge/config.json'))
    parser.add_argument('--write-config',action='store_true')
    parser.add_argument('--stage-config',action='store_true',help='Save local media settings for the next Bridge startup; do not restart.')
    args=parser.parse_args()
    root=pathlib.Path(args.root).resolve();chrome=pathlib.Path(args.chromium).resolve()
    if root.name!='LocalGpuMedia' or not chrome.is_relative_to(root/'playwright') or not chrome.is_file():
        parser.error('Use a dedicated LocalGpuMedia folder and its installed Playwright browser.')
    config_file=pathlib.Path(args.config)
    config=json.loads(config_file.read_text(encoding='utf-8'))
    if not any(p['id']==args.project and p.get('enabled') and p.get('allow_scripts') for p in config['native']['projects']):
        parser.error('Enable the project and its script permission locally first.')
    root.mkdir(parents=True,exist_ok=True)
    sources={'python':sys.executable,**{name:shutil.which(name) for name in ('node','ffmpeg','ffprobe')}}
    if not all(sources.values()):parser.error('Install Python, Node, FFmpeg full and ffprobe first.')
    def copy(source,target):
        source=pathlib.Path(source)
        if target.exists():
            if hashlib.sha256(source.read_bytes()).digest()!=hashlib.sha256(target.read_bytes()).digest():
                raise ValueError('Dedicated binary differs; stop media tasks before explicitly replacing it: '+target.name)
        else:shutil.copy2(source,target)
    for name,source in sources.items():copy(source,root/(name+'.exe'))
    for source in pathlib.Path(sys.base_prefix).glob('*.dll'):copy(source,root/source.name)
    settings={'root':str(root),'python_home':sys.base_prefix,'browsers_path':str(root/'playwright'),
              'chromium_executable':str(chrome),**{name+'_executable':str(root/(name+'.exe')) for name in sources}}
    staged_file=pathlib.Path(config.get('data_dir',config_file.parent))/'native/media-tools.json'
    previous=json.loads(staged_file.read_text(encoding='utf-8')) if staged_file.is_file() else config['native'].get('media_tools',{})
    settings['project_ids']=sorted(set(previous.get('project_ids',[]))|{args.project})
    if args.write_config:
        config['native']['media_tools']=settings
        temporary=config_file.with_name(config_file.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(config_file)
    if args.stage_config:
        target=staged_file
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(settings,indent=2),encoding='utf-8');temporary.replace(target)
    print(json.dumps({'prepared':True,'configured':args.write_config,'staged':args.stage_config,'project_id':args.project,'tools':list(sources)+['chromium']}))

if __name__=='__main__':main()
