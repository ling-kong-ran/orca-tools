"""Provision a NEW Linux Git broker test workspace. Root-only, never migrate live repos."""
import argparse
import grp
import json
import os
import pathlib
import pwd
import re
import shutil
import stat
import subprocess
import sys

STORE = pathlib.Path('/var/lib/orca-git-broker')
CONFIG = STORE / 'broker.json'
LIB = pathlib.Path('/usr/local/lib/orca-git-broker')
USER = 'orca-git-broker'
ACCESS = 'orca-git-access'


def run(args, user=None, env=None, check=True):
    command = (['runuser', '-u', user, '--'] if user else []) + list(map(str, args))
    value = subprocess.run(command, capture_output=True, env=env, timeout=300)
    if check and value.returncode:
        raise RuntimeError('Provisioning step failed: ' + pathlib.Path(str(args[0])).name + '. Protected diagnostics require administrator inspection.')
    return value


def write_config(value, account):
    temporary = CONFIG.with_suffix('.pending')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.chmod(0o600)
    os.chown(temporary, account.pw_uid, account.pw_gid)
    os.replace(temporary, CONFIG)


def prepare():
    if not shutil.which('git') or not shutil.which('bwrap'):
        raise RuntimeError('先安装 git 和 bubblewrap；不擅自更改系统软件源。')
    try:
        grp.getgrnam(ACCESS)
    except KeyError:
        run(['groupadd', '--system', ACCESS])
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        run(['useradd', '--system', '--home-dir', STORE, '--create-home', '--shell', '/usr/sbin/nologin', USER])
        account = pwd.getpwnam(USER)
    STORE.mkdir(exist_ok=True)
    os.chown(STORE, account.pw_uid, account.pw_gid)
    STORE.chmod(0o700)
    LIB.mkdir(parents=True, exist_ok=True)
    for name in ('broker.py', 'client.py', 'isolated-launcher.py'):
        target = LIB / name
        shutil.copyfile(pathlib.Path(__file__).with_name(name), target)
        target.chmod(0o644)
        os.chown(target, 0, 0)
    if not CONFIG.exists():
        write_config({'store': str(STORE), 'socket': '/run/orca-git-broker/broker.sock', 'projects': {}}, account)
    return account


def add_project(request_file):
    info = request_file.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError('Project request must be root-owned and private (0600).')
    value = json.loads(request_file.read_text())
    allowed = {'project_id', 'agent_user', 'remote', 'branch', 'allow_write', 'author_name', 'author_email', 'create_deploy_key', 'known_hosts'}
    if set(value) - allowed:
        raise RuntimeError('Unknown project provisioning field.')
    ident = value['project_id']
    agent_name = value['agent_user']
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', ident) or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', agent_name):
        raise RuntimeError('Invalid project or agent user.')
    account = prepare()
    identities_file = STORE / 'agent-identities.json'
    identities = json.loads(identities_file.read_text()) if identities_file.exists() else {}
    created_agent = False
    try:
        agent = pwd.getpwnam(agent_name)
    except KeyError:
        run(['useradd', '--create-home', '--shell', '/bin/bash', agent_name])
        agent = pwd.getpwnam(agent_name)
        created_agent = True
    if not created_agent and identities.get(agent_name) != agent.pw_uid:
        raise RuntimeError('Use a NEW dedicated agent user. Existing personal accounts cannot be assumed clean.')
    if agent.pw_uid == 0 or agent.pw_uid == account.pw_uid:
        raise RuntimeError('Agent must be a separate unprivileged user.')
    # Existing personal accounts are not accepted as clean isolation identities.
    home = pathlib.Path(agent.pw_dir)
    if any((home / name).exists() for name in ('.gitconfig', '.ssh', '.config/gh')):
        raise RuntimeError('Use a clean dedicated agent user; existing personal Git/SSH configuration was not removed.')
    identities[agent_name] = agent.pw_uid
    identities_file.write_text(json.dumps(identities))
    identities_file.chmod(0o600)
    config = json.loads(CONFIG.read_text())
    if ident in config['projects']:
        raise RuntimeError('Project already provisioned. No automatic replacement.')
    remote = value['remote']
    if not isinstance(remote, str) or not (re.fullmatch(r'git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', remote) or
                                         re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', remote)):
        raise RuntimeError('This provisioner supports explicitly selected GitHub SSH/HTTPS repositories, without embedded credentials.')
    branch = value.get('branch', 'main')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,127}', branch) or '..' in branch:
        raise RuntimeError('Invalid branch.')
    project_store = STORE / ident
    if value.get('create_deploy_key') and not value.get('known_hosts'):
        raise RuntimeError('先准备并核实 Git 主机 known_hosts 文件，再生成隔离 Deploy Key。')
    project_store.mkdir(mode=0o700)
    os.chown(project_store, account.pw_uid, account.pw_gid)
    key = None
    known = None
    if value.get('create_deploy_key'):
        key = project_store / 'deploy-key'
        run(['ssh-keygen', '-t', 'ed25519', '-N', '', '-C', 'orca-deploy-' + ident, '-f', key], user=USER)
        # Public key is printed only to the administrator's provisioning terminal.
        print('Add this PUBLIC key to this repository only; choose read-only unless push was explicitly selected:')
        print(key.with_suffix('.pub').read_text().strip())
        if not value.get('known_hosts'):
            print('Provision a verified known_hosts file, then resume with the protected project request. No insecure host-key bypass is enabled.')
            raise RuntimeError('Verified Git host keys are required before cloning.')
        source = pathlib.Path(value['known_hosts'])
        if source.is_symlink() or not source.is_file():
            raise RuntimeError('Invalid verified known_hosts file.')
        known = project_store / 'known_hosts'
        shutil.copyfile(source, known)
        os.chown(known, account.pw_uid, account.pw_gid)
        known.chmod(0o600)
        # Cloning is deliberately a second administrator action after GitHub authorization.
        project = {'repository': str(project_store / 'repository.git'), 'workspace': '/srv/orca-agent-workspaces/' + ident,
                   'branch': branch, 'agent_uid': agent.pw_uid, 'allow_write': bool(value.get('allow_write')),
                   'author_name': value.get('author_name', 'Developer'), 'author_email': value.get('author_email', 'noreply@local.invalid'),
                   'key_file': str(key), 'known_hosts': str(known), 'pending_remote': remote, 'state': 'key-authorization-required'}
    else:
        project = {'repository': str(project_store / 'repository.git'), 'workspace': '/srv/orca-agent-workspaces/' + ident,
                   'branch': branch, 'agent_uid': agent.pw_uid, 'allow_write': bool(value.get('allow_write')),
                   'author_name': value.get('author_name', 'Developer'), 'author_email': value.get('author_email', 'noreply@local.invalid'),
                   'pending_remote': remote, 'state': 'clone-required'}
    for field in ('author_name', 'author_email'):
        if not isinstance(project[field], str) or not project[field] or len(project[field]) > 200 or re.search(r'[\x00-\x1f<>]', project[field]):
            raise RuntimeError('Invalid administrator-selected commit identity.')
    run(['usermod', '-a', '-G', ACCESS, agent_name])
    run(['usermod', '-a', '-G', ACCESS, USER])
    config['projects'][ident] = project
    write_config(config, account)
    print('Project prepared. Authorize the key, then run initialize. No current project was changed.')


def initialize(ident):
    from broker import Project
    account = pwd.getpwnam(USER)
    config = json.loads(CONFIG.read_text())
    project = config['projects'][ident]
    if project.get('state') not in ('key-authorization-required', 'clone-required'):
        raise RuntimeError('Project already initialized; no automatic replacement.')
    repository = pathlib.Path(project['repository'])
    if repository.exists():
        raise RuntimeError('Repository already exists; inspect the previous attempt before continuing.')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(STORE), 'TZ': 'UTC0', 'GIT_TERMINAL_PROMPT': '0',
           'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
    if project.get('key_file'):
        import shlex
        env['GIT_SSH_COMMAND'] = 'ssh -oBatchMode=yes -oIdentitiesOnly=yes -oStrictHostKeyChecking=yes -i ' + shlex.quote(project['key_file']) + ' -oUserKnownHostsFile=' + shlex.quote(project['known_hosts'])
    # Run as broker, never root. The real remote only exists in the private store.
    run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', 'clone', '--bare', '--single-branch',
         '--branch', project['branch'], '--', project['pending_remote'], repository], user=USER, env=env)
    workspace = pathlib.Path(project['workspace'])
    workspace.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if workspace.exists():
        raise RuntimeError('Source workspace already exists; refusing to overwrite.')
    workspace.mkdir(mode=0o2770)
    os.chown(workspace, project['agent_uid'], grp.getgrnam(ACCESS).gr_gid)
    exporter = '''import json,sys
sys.path.insert(0,'/usr/local/lib/orca-git-broker')
from broker import Project
config=json.load(open('/var/lib/orca-git-broker/broker.json'))
project=Project(config['projects'][sys.argv[1]])
try:
 for name,(content,mode) in project.tree().items():project.workspace.write(name,content,mode)
finally:project.workspace.close()
'''
    run(['/usr/bin/python3', '-c', exporter, ident], user=USER)
    # Files were initially exported by root; set shared-source ownership only.
    for current, directories, files in os.walk(workspace, followlinks=False):
        os.chown(current, project['agent_uid'], grp.getgrnam(ACCESS).gr_gid)
        os.chmod(current, 0o2770)
        for file in files:
            os.chown(pathlib.Path(current, file), project['agent_uid'], grp.getgrnam(ACCESS).gr_gid)
    project['state'] = 'ready-for-isolation-tests'
    project.pop('pending_remote', None)
    write_config(config, account)
    print('Source workspace exported. Isolation and Orca compatibility tests are still REQUIRED.')


def install_service():
    account = prepare()
    unit = pathlib.Path('/etc/systemd/system/orca-git-broker.service')
    if unit.exists():
        raise RuntimeError('Service already exists; do not overwrite a live broker.')
    config = json.loads(CONFIG.read_text())
    ready = {key: value for key, value in config['projects'].items() if value.get('state') == 'ready-for-isolation-tests'}
    if not ready or len(ready) != len(config['projects']):
        raise RuntimeError('Finish initialization before starting the broker.')
    unit.write_text(f'''[Unit]
Description=Orca trusted Git broker
After=network-online.target
[Service]
User={USER}
Group={ACCESS}
ExecStart=/usr/bin/python3 {LIB}/broker.py --config {CONFIG}
RuntimeDirectory=orca-git-broker
RuntimeDirectoryMode=0750
UMask=0077
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={STORE} /srv/orca-agent-workspaces
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
[Install]
WantedBy=multi-user.target
''')
    command = ['/usr/bin/systemctl'] if pathlib.Path('/usr/bin/systemctl').exists() else ['systemctl']
    run(command + ['daemon-reload'])
    run(command + ['enable', '--now', unit.name])
    print('Broker service started. No public listener; use a NEW agent session to pick up group membership.')


def verify(ident):
    config = json.loads(CONFIG.read_text())
    project = config['projects'][ident]
    agent = pwd.getpwuid(project['agent_uid'])
    probes = [str(CONFIG), str(project['repository']) + '/config']
    if project.get('key_file'):
        probes.append(project['key_file'])
    denied = all(run(['/usr/bin/test', '-r', path], user=agent.pw_name, check=False).returncode != 0 for path in probes)
    no_git = not pathlib.Path(project['workspace'], '.git').exists()
    print(json.dumps({'private_store_denied': denied, 'source_has_no_git': no_git,
                      'runtime_namespace_verified': False, 'orca_worktree_compatible': False,
                      'ready_for_production': False,
                      'next': 'Run the isolated-launcher process tests and Orca compatibility tests before migration.'}))
    if not denied or not no_git:
        raise RuntimeError('Identity access checks failed. Do not use this project with an agent.')


def main():
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise SystemExit('Run the provisioner from a trusted Linux administrator terminal.')
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('prepare')
    add = sub.add_parser('add-project')
    add.add_argument('--request-file', type=pathlib.Path, required=True)
    init = sub.add_parser('initialize')
    init.add_argument('--project', required=True)
    check = sub.add_parser('verify')
    check.add_argument('--project', required=True)
    sub.add_parser('install-service')
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare()
    elif args.operation == 'add-project':
        add_project(args.request_file)
    elif args.operation == 'initialize':
        initialize(args.project)
    elif args.operation == 'verify':
        verify(args.project)
    else:
        install_service()


if __name__ == '__main__':
    main()
