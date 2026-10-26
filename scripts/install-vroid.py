"""Install a private VRoid Studio copy and pinned upstream MCP dependencies."""
import argparse, hashlib, json, os, pathlib, shutil, urllib.request, zipfile

PACKAGES = {
    'vroid-studio-mcp-1.0.0.zip': (
        'https://github.com/brainrom/vroid-studio-mcp/releases/download/v1.0.0/vroid-studio-mcp-1.0.0.zip',
        '9d619f985e5e47a4c858689b0248de4acfdec108ff24f721659054a524274553'),
    'BepInEx.zip': (
        'https://builds.bepinex.dev/projects/bepinex_be/788/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.788%2B5b766a3.zip',
        'f4cc496bd098a0df4164b81e3737297707f13a47c2478dba2f60eefab784817a'),
    '6000.0.62.zip': ('https://unity.bepinex.dev/libraries/6000.0.62.zip',
        'a3c6490d9692d8cf22930b10c80081d1b3c5e93ce98c8306562e77accf2bd268'),
}


def extract(archive, destination):
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            path = pathlib.PurePosixPath(item.filename.replace('\\', '/'))
            if path.is_absolute() or '..' in path.parts or ':' in str(path) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe dependency archive.')
        source.extractall(destination)


def install(studio, root, cache):
    studio = studio.resolve(); root = root.resolve(); cache = cache.resolve()
    if not (studio/'VRoidStudio.exe').is_file() or not (studio/'VRoidStudio_Data').is_dir():
        raise ValueError('Select the installed VRoid Studio directory (supported: 2.14.0, Unity 6000.0.62).')
    target = root/'native/vroid'
    if target.exists(): raise ValueError('The managed VRoid directory already exists. Back it up and stop that instance before upgrading.')
    cache.mkdir(parents=True, exist_ok=True)
    for name, (url, checksum) in PACKAGES.items():
        file = cache/name
        if not file.is_file():
            request = urllib.request.Request(url, headers={'User-Agent': 'Orca-Tools/1.5'})
            with urllib.request.urlopen(request, timeout=120) as source, file.open('xb') as output:
                shutil.copyfileobj(source, output)
        if hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
            raise ValueError('Dependency checksum mismatch: '+name)
    # Keep the stock installation and all user model data untouched.
    shutil.copytree(studio, target)
    (target/'VRoidStudio.exe').rename(target/'VRoidStudio-LocalGpu.exe')
    (target/'VRoidStudio_Data').rename(target/'VRoidStudio-LocalGpu_Data')
    extract(cache/'BepInEx.zip', target)
    extract(cache/'vroid-studio-mcp-1.0.0.zip', target)
    config_file = target/'BepInEx/config/BepInEx.cfg'
    content = config_file.read_text(encoding='utf-8-sig')
    # Bootstrap IL2CPP entirely offline; the renderer never needs internet access.
    content = content.replace('UnityBaseLibrariesSource = https://unity.bepinex.dev/libraries/{VERSION}.zip', 'UnityBaseLibrariesSource = 6000.0.62.zip')
    config_file.write_text(content, encoding='utf-8')
    libraries = target/'BepInEx/unity-libs'; libraries.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache/'6000.0.62.zip', libraries/'6000.0.62.zip')
    settings = {'enabled': True, 'tcp': '127.0.0.1:17890', 'mcp': '127.0.0.1:17891',
                'dev_tools': False, 'debug_artifacts': False, 'max_batch_ops': 12,
                'msaa_samples': 4, 'render_scale': 1, 'aniso_filtering': True}
    (config_file.parent/'com.kokokoshka.vroidstudiomcp.servers.json').write_text(json.dumps(settings, indent=2), encoding='utf-8')
    bridge_config = root/'config.json'; config = json.loads(bridge_config.read_text(encoding='utf-8-sig'))
    backup = root/'config.before-vroid.local.json'
    if not backup.exists(): shutil.copy2(bridge_config, backup)
    config.setdefault('native', {})['vroid_executable'] = str(target/'VRoidStudio-LocalGpu.exe')
    config['auto_setup_privacy'] = True
    temp = bridge_config.with_suffix('.tmp'); temp.write_text(json.dumps(config, indent=2), encoding='utf-8'); temp.replace(bridge_config)
    return {'installed': True, 'upstream': 'brainrom/vroid-studio-mcp 1.0.0',
            'next': 'Restart the idle bridge. Its automatic network setup includes the managed VRoid executable. Reload the VPS MCP plugin.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--studio', type=pathlib.Path, required=True)
    parser.add_argument('--data-dir', type=pathlib.Path, default=pathlib.Path(os.environ.get('LOCALAPPDATA', ''))/'LocalGpuBridge')
    parser.add_argument('--download-cache', type=pathlib.Path, default=pathlib.Path.home()/'.cache/orca-tools/vroid')
    args = parser.parse_args()
    print(json.dumps(install(args.studio, args.data_dir, args.download_cache)))
