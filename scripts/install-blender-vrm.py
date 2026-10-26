"""Offline-install the pinned VRM extension without replacing Blender preferences."""
import argparse, hashlib, json, os, pathlib, subprocess, urllib.request

URL = 'https://github.com/saturday06/VRM-Addon-for-Blender/releases/download/v4.10.2/VRM_Addon_for_Blender-Extension-4_10_2.zip'
CHECKSUM = '228e622d158fbbf070b1b49547708f360a223873f00fa81a42170794492e6db9'


def install(root, archive=None):
    root = root.resolve(); config = json.loads((root/'config.json').read_text(encoding='utf-8-sig'))
    executable = pathlib.Path(config['native']['blender_executable'])
    if executable.name != 'blender-local-gpu.exe' or not executable.is_file():
        raise ValueError('Configure the dedicated managed Blender executable first.')
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'services/local-gpu-bridge'))
    from native_process import EgressGuard
    EgressGuard(config['native']).require('blender')
    cache = root/'native/vrm-install'; cache.mkdir(parents=True, exist_ok=True)
    archive = archive.resolve() if archive else cache/'VRM_Addon_for_Blender-Extension-4_10_2.zip'
    if not archive.exists():
        request = urllib.request.Request(URL, headers={'User-Agent': 'Orca-Tools'})
        archive.write_bytes(urllib.request.urlopen(request, timeout=90).read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != CHECKSUM:
        raise ValueError('VRM extension checksum mismatch.')
    report = cache/'result.json'; report.unlink(missing_ok=True)
    code = '''import addon_utils,bpy,importlib.util,json,pathlib
archive=pathlib.Path(ARCHIVE)
module='bl_ext.user_default.vrm'
if importlib.util.find_spec(module) is None:
    try:
        bpy.ops.extensions.package_install_files(filepath=str(archive),repo='user_default',enable_on_install=False)
    except RuntimeError:
        # Blender can report unrelated broken legacy add-on names after installing
        # the package successfully. Verify this package rather than trusting exit 0.
        if importlib.util.find_spec(module) is None: raise
addon_utils.enable(module,default_set=True,persistent=True)
assert addon_utils.check(module)[1], 'VRM extension did not register'
assert bpy.ops.import_scene.vrm.get_rna_type()
assert bpy.ops.export_scene.vrm.get_rna_type()
manifest=pathlib.Path(importlib.util.find_spec(module).origin).parent/'blender_manifest.toml'
assert 'version = "4.10.2"' in manifest.read_text(encoding='utf-8'), 'Unexpected installed VRM version'
bpy.ops.wm.save_userpref()
pathlib.Path(REPORT).write_text(json.dumps({'installed':True,'enabled':True,'vrm_import':True,'vrm_export':True,'version':'4.10.2'}))
'''.replace('ARCHIVE', repr(str(archive))).replace('REPORT', repr(str(report)))
    script = cache/'install.py'; script.write_text(code, encoding='utf-8')
    # Load the existing user preferences. Saving --factory-startup preferences
    # would discard unrelated settings; the managed renderer never saves those.
    with (cache/'install.log').open('wb') as log:
        run = subprocess.run([str(executable), '--background', '--disable-autoexec', '--python-exit-code', '1', '--python', str(script)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=180, creationflags=0x08000000)
    if run.returncode or not report.is_file(): raise ValueError('VRM install failed. Check the local native/vrm-install/install.log.')
    return json.loads(report.read_text(encoding='utf-8'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=pathlib.Path, default=pathlib.Path(os.environ.get('LOCALAPPDATA', ''))/'LocalGpuBridge')
    parser.add_argument('--archive', type=pathlib.Path, help='Optional offline ZIP with the pinned checksum')
    args = parser.parse_args()
    print(json.dumps(install(args.data_dir, args.archive)))
