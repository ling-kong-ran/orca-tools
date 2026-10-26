"""Build/install the Toolkit VRM exporter against a prepared, stopped VRoid copy."""
import argparse, hashlib, importlib.util, json, os, pathlib, shutil, subprocess, tempfile, urllib.request

REVISION = 'ab9ad4f90d6ba6486a234a975c86e3298ccfd75e'
CHECKSUM = 'b5655f9583a4e752ce9aa38cb6f9826fc99ce61a7e95af3b38da4fc969c0fc1d'
ROOT = pathlib.Path(__file__).resolve().parents[1]


def replace_once(file, old, new):
    source = file.read_text(encoding='utf-8')
    if source.count(old) != 1: raise ValueError('Pinned upstream source does not match export patch: '+file.name)
    file.write_text(source.replace(old, new, 1), encoding='utf-8')


def patch_source(source):
    project = source/'plugin/VroidStudioMcp'
    if (project/'Commands/Handlers/ExportHandlers.cs').exists():
        raise ValueError('Pinned upstream source does not match export patch: already patched')
    shutil.copy2(ROOT/'services/local-gpu-bridge/vroid-export/ExportHandlers.cs', project/'Commands/Handlers/ExportHandlers.cs')
    replace_once(project/'Commands/CommandDispatcher.cs', '"save", "categories"', '"export_vrm", "save", "categories"')
    replace_once(project/'Commands/CommandDispatcher.cs', '["save"] = SessionHandlers.Save,',
                 '["save"] = SessionHandlers.Save,\n        ["export_vrm"] = ExportHandlers.Export,')
    replace_once(project/'Plugin.cs', 'MessagesI18n.Install();', '''MessagesI18n.Install();
        PatchByTypeName("VRoid.Studio.VRMExportScreen.ViewModel", "OnScreenActivate",
            new HarmonyMethod(typeof(ExportHandlers).GetMethod(nameof(ExportHandlers.OnExportScreen))));''')
    replace_once(project/'MCP/McpHost.cs', 'T("sections",', '''T("export_vrm", "Export the current model without a file dialog, then return to editing. Fresh metadata, restrictive license defaults.",
              new[] { "path", "format", "title", "author", "replace" }, new[] { "path", "title", "author" },
              new() { ["path"] = P("string", "Absolute .vrm destination."), ["format"] = EnumSchema("VRM version.", "1.0", "0.0"),
                ["title"] = P("string", "Model title."), ["author"] = P("string", "Author name."), ["replace"] = P("boolean", "Allow overwrite.") }),

            T("sections",''')
    return project


def build(game, archive, output):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != CHECKSUM:
        raise ValueError('Pinned VRoid source checksum mismatch.')
    for name in ('core/Il2CppInterop.Runtime.dll', 'interop/VRoidStudio.dll'):
        if not (game/'BepInEx'/name).is_file():
            raise ValueError('Start the managed Studio once to generate IL2CPP interop, then stop it before installation.')
    spec = importlib.util.spec_from_file_location('vroid_installer', ROOT/'scripts/install-vroid.py')
    installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
    with tempfile.TemporaryDirectory(prefix='orca-vroid-export-') as folder:
        destination = pathlib.Path(folder)
        installer.extract(archive, destination)
        source = destination/('vroid-studio-mcp-'+REVISION)
        project = patch_source(source)
        subprocess.run(['dotnet', 'build', str(project/'VroidStudioMcp.csproj'), '-c', 'Release',
                        '-p:GameDir='+str(game), '--nologo'], check=True, timeout=300)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project/'bin/Release/VroidStudioMcp.dll', output)
        shutil.copy2(source/'LICENSE', output.with_suffix('.upstream-LICENSE.txt'))
    return output


def require_stopped(game):
    # Query only the managed executable, not unrelated user applications.
    query = "Get-Process -Name 'VRoidStudio-LocalGpu' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', query],
                            capture_output=True, text=True, timeout=20, creationflags=0x08000000)
    if any(pathlib.Path(p).resolve() == (game/'VRoidStudio-LocalGpu.exe').resolve() for p in result.stdout.splitlines() if p.strip()):
        raise ValueError('Save and stop managed Studio before replacing its MCP assembly.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=pathlib.Path, default=pathlib.Path(os.environ.get('LOCALAPPDATA', ''))/'LocalGpuBridge')
    parser.add_argument('--source-archive', type=pathlib.Path)
    parser.add_argument('--build-only', type=pathlib.Path, metavar='OUTPUT_DLL', help='Build without changing the installed plugin.')
    args = parser.parse_args()
    game = args.data_dir.resolve()/'native/vroid'
    if not args.build_only: require_stopped(game)
    archive = args.source_archive
    if archive is None:
        archive = pathlib.Path.home()/'.cache/orca-tools/vroid'/('source-'+REVISION+'.zip')
        if not archive.is_file():
            archive.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request('https://codeload.github.com/brainrom/vroid-studio-mcp/zip/'+REVISION,
                                             headers={'User-Agent': 'Orca-Tools/1.6'})
            temporary = archive.with_suffix('.download')
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != CHECKSUM:
                temporary.unlink(); raise ValueError('Pinned VRoid source checksum mismatch.')
            temporary.replace(archive)
    with tempfile.TemporaryDirectory(prefix='orca-vroid-build-') as folder:
        binary = build(game, archive.resolve(), pathlib.Path(folder)/'VroidStudioMcp.dll')
        if args.build_only:
            args.build_only.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, args.build_only)
            shutil.copy2(binary.with_suffix('.upstream-LICENSE.txt'), args.build_only.with_suffix('.upstream-LICENSE.txt'))
        else:
            require_stopped(game)
            target = game/'BepInEx/plugins/VroidStudioMcp.dll'
            backup = target.with_suffix('.dll.before-export')
            if target.exists() and not backup.exists(): shutil.copy2(target, backup)
            staging = target.with_suffix('.dll.installing'); shutil.copy2(binary, staging); staging.replace(target)
            shutil.copy2(binary.with_suffix('.upstream-LICENSE.txt'), target.with_suffix('.upstream-LICENSE.txt'))
            (target.parent/'toolkit-export.json').write_text(json.dumps({'version': '1.6.0', 'upstream': REVISION,
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}), encoding='utf-8')
    print(json.dumps({'built': True, 'installed': not bool(args.build_only), 'version': '1.6.0',
                      'next': 'Start managed Studio through the bridge, then reload the VPS plugin.'}))


if __name__ == '__main__': main()
