"""Administrator-only Claude launcher with a private /proc and a source-only FS.

This is NOT installed into an existing Orca account automatically. Validate the
exact runtime, MCP and worktree behavior on a new project before adopting it.
"""
import argparse
import grp
import json
import os
import pathlib
import pwd
import shutil
import tempfile

CONFIG = pathlib.Path('/var/lib/orca-git-broker/broker.json')


def main():
    if os.geteuid() != 0:
        raise SystemExit('Launch from the trusted administrator/runtime, not an agent-controlled shell wrapper.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    project = config['projects'].get(args.project)
    if not project or project.get('state') != 'ready-for-isolation-tests':
        raise SystemExit('Use an initialized independent test project.')
    agent = pwd.getpwuid(project['agent_uid'])
    identities = json.loads(CONFIG.with_name('agent-identities.json').read_text())
    if identities.get(agent.pw_name) != agent.pw_uid:
        raise SystemExit('Agent identity was not provisioned as a fresh dedicated account.')
    home = pathlib.Path(agent.pw_dir)
    if agent.pw_uid == 0 or any((home / name).exists() for name in ('.gitconfig', '.ssh', '.config/gh')):
        raise SystemExit('A clean unprivileged agent HOME is required.')
    workspace = pathlib.Path(project['workspace'])
    if (workspace / '.git').exists():
        raise SystemExit('Workspace exposes Git metadata; do not launch.')
    bwrap = shutil.which('bwrap')
    if not bwrap:
        raise SystemExit('Install bubblewrap from the operating system repository first.')
    claude = home / '.local/bin/claude'
    if not args.self_test and not claude.is_file():
        raise SystemExit('Install and authorize Claude as this dedicated agent user first.')
    access = grp.getgrnam('orca-git-access')
    os.umask(0o007)
    command = [bwrap, '--die-with-parent', '--new-session', '--unshare-pid', '--unshare-ipc', '--unshare-uts',
               '--hostname', 'agent', '--cap-drop', 'ALL', '--clearenv', '--ro-bind', '/usr', '/usr']
    for name in ('/bin', '/sbin', '/lib', '/lib64'):
        path = pathlib.Path(name)
        if path.is_symlink():
            command += ['--symlink', os.readlink(path), name]
        elif path.is_dir():
            command += ['--ro-bind', name, name]
    command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/etc',
                '--dir', '/run', '--dir', '/run/orca-git-broker', '--dir', '/home',
                '--bind', str(home), str(home), '--bind', str(workspace), str(workspace),
                '--bind', config['socket'], config['socket']]
    for name in ('/etc/ssl/certs', '/etc/resolv.conf'):
        if pathlib.Path(name).exists():
            command += ['--ro-bind', str(pathlib.Path(name).resolve()), name]
    with tempfile.TemporaryDirectory(prefix='orca-agent-nss-') as temporary:
        folder = pathlib.Path(temporary)
        (folder / 'passwd').write_text(f'root:x:0:0:root:/root:/usr/sbin/nologin\n{agent.pw_name}:x:{agent.pw_uid}:{access.gr_gid}:Agent:{home}:/bin/bash\n')
        (folder / 'group').write_text(f'root:x:0:\n{access.gr_name}:x:{access.gr_gid}:\n')
        (folder / 'nsswitch.conf').write_text('passwd: files\ngroup: files\nhosts: files dns\n')
        (folder / 'hosts').write_text('127.0.0.1 localhost\n::1 localhost\n')
        for name in ('passwd', 'group', 'nsswitch.conf', 'hosts'):
            (folder / name).chmod(0o644)
            command += ['--ro-bind', str(folder / name), '/etc/' + name]
        command += ['--setenv', 'HOME', str(home), '--setenv', 'USER', agent.pw_name,
                    '--setenv', 'PATH', str(home / '.local/bin') + ':/usr/local/bin:/usr/bin:/bin',
                    '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'TZ', 'UTC0',
                    '--uid', str(agent.pw_uid), '--gid', str(access.gr_gid), '--chdir', str(workspace)]
        if args.self_test:
            program = '''import pathlib,json,os
blocked=not pathlib.Path('/var/lib/orca-git-broker').exists()
no_git=not pathlib.Path('.git').exists()
no_host_homes=not pathlib.Path('/home/workspace').exists()
print(json.dumps({'private_store_hidden':blocked,'source_has_no_git':no_git,'other_user_home_hidden':no_host_homes,'private_proc':os.getpid()<100,'uid':os.getuid()}))
raise SystemExit(0 if blocked and no_git and no_host_homes and os.getpid()<100 else 1)
'''
            command += ['/usr/bin/python3', '-c', program]
        else:
            command += [str(claude)]
        import subprocess
        return subprocess.call(command)


if __name__ == '__main__':
    raise SystemExit(main())
