"""Configure dedicated Unity executable copies; no account data or license activation."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import uuid


def configure(config_path, editor, cli, data_dir, project=None, project_id='unity-game'):
    editor=pathlib.Path(editor).resolve();cli=pathlib.Path(cli).resolve();data_dir=pathlib.Path(data_dir).resolve()
    if editor.name.lower()!='unity.exe' or not editor.is_file():raise ValueError('Select the installed Editor Unity.exe.')
    if not cli.is_file():raise ValueError('Select the official Unity CLI executable.')
    if not (editor.parent/'Data').is_dir():raise ValueError('The Editor installation is incomplete.')
    def dedicated(source,name):
        target=source.with_name(name)
        if not target.exists() or hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(source.read_bytes()).digest():
            staged=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp');shutil.copy2(source,staged);staged.replace(target)
        return str(target)
    config_path=pathlib.Path(config_path);config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    native=config.setdefault('native',{})
    native.update(unity_executable=dedicated(editor,'Unity-LocalGpu.exe'),
        unity_cli_executable=dedicated(cli,'unity-cli-local-gpu.exe'),unity_data_dir=str(data_dir))
    for folder in ('temp','upm','assets'): (data_dir/folder).mkdir(parents=True,exist_ok=True)
    if project:
        root=pathlib.Path(project).resolve()
        if not all((root/name).is_dir() for name in ('Assets','Packages','ProjectSettings')):raise ValueError('Select a Unity project root.')
        import re
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',project_id):raise ValueError('Invalid project id.')
        projects=native.setdefault('projects',[]);existing=next((p for p in projects if p['id']==project_id),None)
        if existing and pathlib.Path(existing['root']).resolve()!=root:raise ValueError('Project id already belongs to another directory.')
        if not existing:
            projects.append({'id':project_id,'name':'Unity Project','root':str(root),'unity_subdir':'',
                'godot_subdir':'client','enabled':True,'allow_scripts':False,'sync_policy':'remote_wins',
                'git':{'enabled':False,'remote':'origin','branch':'main','auto_pull_before_render':False}})
        else:existing['unity_subdir']=''
    staged=config_path.with_name(config_path.name+'.'+uuid.uuid4().hex+'.tmp')
    staged.write_text(json.dumps(config,indent=2),encoding='utf-8');staged.replace(config_path)
    return {'configured':True,'project_id':project_id if project else None,'next':'Restart the GPU Bridge and complete local network privacy setup.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=pathlib.Path,default=pathlib.Path(os.environ.get('LOCALAPPDATA',''))/'LocalGpuBridge/config.json')
    parser.add_argument('--editor',type=pathlib.Path,required=True);parser.add_argument('--cli',type=pathlib.Path,required=True)
    parser.add_argument('--data-dir',type=pathlib.Path,required=True);parser.add_argument('--project',type=pathlib.Path)
    parser.add_argument('--project-id',default='unity-game');args=parser.parse_args()
    print(json.dumps(configure(args.config,args.editor,args.cli,args.data_dir,args.project,args.project_id)))


if __name__=='__main__':main()
