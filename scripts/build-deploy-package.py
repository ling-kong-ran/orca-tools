"""Build a portable Windows deployment assistant from source (no personal files).

Run on Windows x64 Python 3.14. Dependencies use official PyPI, isolated from
user pip mirrors. Every outer ZIP entry uses UTC; source assets are not renamed.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = '0.1.0-preview.6'
PYTHON_VERSION = '3.14.10'
PYTHON_SHA256 = 'b553e7dac884469b40e0740bb527271c3378f700b427e0485835f1bb6424361c'
PYTHON_URL = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embeddable-amd64.zip'
EXTENSIONS = {'.py', '.cjs', '.mjs', '.html', '.css', '.ps1', '.md', '.sh', '.gd', '.cs'}
JSON_NAMES = {'orca-plugin.json', 'plugin.json', 'marketplace.json', 'example-workflow.json', 'gpu-settings.example.json', 'requirements-windows.lock'}


def file_hash(file):
    value = hashlib.sha256()
    with open(file, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def source_files():
    paths = ['plugins/toolkit', 'services/deploy', 'services/git-broker', 'services/local-gpu-bridge',
             'tools/orca-startup', 'scripts']
    for directory in paths:
        for file in (ROOT / directory).rglob('*'):
            if not file.is_file() or file.is_symlink():
                continue
            relative = file.relative_to(ROOT)
            if any(p in ('__pycache__', 'node_modules', 'dependencies', 'jobs', 'keys', '.venv') for p in relative.parts):
                continue
            if '.local.' in file.name or file.name.startswith('.env') or file.name.startswith('test_') or file.name.startswith('test-'):
                continue
            if file.suffix in EXTENSIONS or file.name in JSON_NAMES:
                yield file
    for name in ('deployment-center.md', 'claude-code-guide.md', 'vps-orca.md', 'gpu-bridge.md', 'toolkit.md', 'operations.md'):
        file = ROOT / 'docs' / name
        if file.is_file():
            yield file
    for file in (ROOT / 'docs/images').rglob('*'):
        if file.is_file() and not file.is_symlink() and file.suffix.lower() in ('.png', '.jpg', '.svg', '.webp'):
            yield file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependencies', type=pathlib.Path)
    parser.add_argument('--resume-runtime-only', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 14):
        raise SystemExit('Build this portable Windows x64 package using Windows Python 3.14.')
    build = ROOT / '.build/deploy'
    build.mkdir(parents=True, exist_ok=True)
    dependencies = args.dependencies or build / 'official-dependencies'
    if not dependencies.exists():
        subprocess.run([sys.executable, '-m', 'pip', '--isolated', 'install', '--index-url', 'https://pypi.org/simple',
                        '--no-cache-dir', '--no-compile', '--only-binary=:all:', '--require-hashes', '--target', str(dependencies),
                        '-r', str(ROOT / 'services/deploy/requirements-windows.lock')], check=True)
    archive = build / ('python-' + PYTHON_VERSION + '-embeddable-amd64.zip')
    if not archive.exists():
        with urllib.request.urlopen(PYTHON_URL, timeout=60) as response, archive.open('xb') as out:
            shutil.copyfileobj(response, out)
    if file_hash(archive) != PYTHON_SHA256:
        raise ValueError('Python archive does not match the pinned official release manifest.')
    package = ROOT / 'dist' / ('orca-deploy-' + VERSION) / 'windows-x64'
    if package.exists() and not (args.resume_runtime_only and {p.name for p in package.iterdir()} == {'runtime'}):
        raise SystemExit('Package directory already exists. Use a new version or inspect/remove the exact prior build deliberately.')
    runtime = package / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundled:
        for item in bundled.infolist():
            target = runtime / item.filename
            if not target.resolve().is_relative_to(runtime.resolve()):
                raise ValueError('Python archive path escapes runtime.')
        bundled.extractall(runtime)
    env = {**os.environ, 'ORCA_DEPLOY_VERIFY_FILE': str(runtime / 'python.exe')}
    # A PowerShell 7 parent can otherwise make Windows PowerShell 5 load the
    # wrong Microsoft.PowerShell.Security module and silently yield null certs.
    for key in list(env):
        if key.lower() in ('psmodulepath', 'pshome'):
            del env[key]
    signature = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
        "$ErrorActionPreference='Stop';$s=Get-AuthenticodeSignature -LiteralPath $env:ORCA_DEPLOY_VERIFY_FILE;@{status=[int]$s.Status;subject=$s.SignerCertificate.Subject}|ConvertTo-Json -Compress"],
        env=env, capture_output=True, text=True, check=True)
    certificate = json.loads(signature.stdout)
    if certificate['status'] != 0 or 'Python Software Foundation' not in (certificate['subject'] or ''):
        raise ValueError('Official Python runtime signature could not be verified; do not distribute this build.')
    for source in source_files():
        target = package / 'source' / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for destination in (package / 'source/services/deploy/dependencies',
                        package / 'source/plugins/toolkit/modules/deploy-runtime/dependencies'):
        shutil.copytree(dependencies, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(ROOT / 'scripts/Start-OrcaDeploy.ps1', package / 'Start-OrcaDeploy.ps1')
    (package / 'Start-OrcaDeploy.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-OrcaDeploy.ps1"\r\n', encoding='ascii')
    shutil.copyfile(ROOT / 'services/deploy/README.md', package / 'README.md')
    packages = []
    for folder in dependencies.glob('*.dist-info'):
        meta = importlib.metadata.PathDistribution(folder)
        packages.append({'name': meta.metadata['Name'], 'version': meta.version})
    manifest = {'version': VERSION, 'built_utc': datetime.now(timezone.utc).isoformat(),
                'runtime': {'version': PYTHON_VERSION, 'url': PYTHON_URL, 'sha256': file_hash(archive), 'authenticode_verified': True},
                'dependencies': sorted(packages, key=lambda x: x['name'].lower()),
                'release_signature': 'not-signed; local preview distribution', 'files': []}
    for file in sorted(package.rglob('*')):
        if file.is_file():
            manifest['files'].append({'path': file.relative_to(package).as_posix(), 'sha256': file_hash(file)})
    (package / 'package-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    zip_path = package.parent / ('orca-deploy-' + VERSION + '-windows-x64.zip')
    stamp = datetime.now(timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as out:
        for file in sorted(package.rglob('*')):
            if file.is_file():
                item = zipfile.ZipInfo('OrcaDeploy/' + file.relative_to(package).as_posix(), date_time=stamp)
                item.compress_type = zipfile.ZIP_DEFLATED
                out.writestr(item, file.read_bytes())
    print(json.dumps({'package': str(zip_path), 'bytes': zip_path.stat().st_size, 'sha256': file_hash(zip_path), 'version': VERSION}))


if __name__ == '__main__':
    main()
