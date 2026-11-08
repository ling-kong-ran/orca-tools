"""SSH transport with explicit host identity, in-memory secrets and fixed payloads."""
import base64
import hashlib
import hmac
import json
import pathlib
import socket
import time
import zlib


def fingerprint(key):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')


def paramiko_module():
    try:
        import paramiko
        return paramiko
    except ImportError:
        raise RuntimeError('SSH 依赖未安装。请运行安装助手，或 pip install -r services/deploy/requirements.txt。') from None


def probe(plan):
    module = paramiko_module()
    connection = socket.create_connection((plan['host'], plan['ssh_port']), timeout=12)
    transport = module.Transport(connection)
    try:
        transport.start_client(timeout=12)
        key = transport.get_remote_server_key()
        return {'fingerprint': fingerprint(key), 'key_type': key.get_name(),
                'notice': '请通过 VPS 厂商控制台或其他可信渠道核对指纹；网络上获取的指纹本身不代表已可信。'}
    finally:
        transport.close()
        connection.close()


class SSH:
    def __init__(self, plan, identity, password=None, key_file=None, key_passphrase=None):
        module = paramiko_module()
        if not isinstance(identity, str) or not identity.startswith('SHA256:'):
            raise ValueError('先核实 SSH 主机指纹。')

        class Pinned(module.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                if not hmac.compare_digest(fingerprint(key), identity):
                    raise RuntimeError('SSH 主机身份已改变，连接已停止。')

        self.client = module.SSHClient()
        self.use_sudo = False
        # Do not modify known_hosts or accept a changed key via AutoAddPolicy.
        self.client.set_missing_host_key_policy(Pinned())
        try:
            self.client.connect(plan['host'], port=plan['ssh_port'], username=plan['ssh_user'],
                                password=password or None, key_filename=key_file or None,
                                passphrase=key_passphrase or None, look_for_keys=not password and not key_file,
                                allow_agent=not password and not key_file, timeout=12,
                                auth_timeout=20, banner_timeout=15)
        except Exception:
            self.client.close()
            raise RuntimeError('SSH 连接或认证失败。检查主机身份、认证方式与 VPS 访问规则。') from None
        self.client.get_transport().set_keepalive(20)

    def stage(self, operation, plan, timeout=900):
        if operation not in ('inspect', 'system', 'tailscale', 'tools', 'service', 'verify', 'handoffs'):
            raise ValueError('不允许的部署操作。')
        source = pathlib.Path(__file__).with_name('linux_stage.py').read_bytes()
        payload = base64.b64encode(zlib.compress(source)).decode()
        # Only trusted shipped code is evaluated. User values travel over stdin as JSON.
        command = "python3 -c 'import base64,zlib;exec(zlib.decompress(base64.b64decode(\"" + payload + "\")))'"
        if self.use_sudo and operation != 'inspect':
            command = 'sudo -n -- ' + command
        channel = self.client.get_transport().open_session(timeout=15)
        channel.settimeout(2)
        channel.exec_command(command)
        channel.sendall(json.dumps({'operation': operation, 'plan': plan}).encode())
        channel.shutdown_write()
        start = time.monotonic()
        output = bytearray()
        try:
            while True:
                if channel.recv_ready():
                    output.extend(channel.recv(65536))
                    if len(output) > 256 * 1024:
                        raise RuntimeError('远端响应超过限制。')
                # Never expose raw stderr: install tools can echo account and credential data.
                if channel.recv_stderr_ready():
                    channel.recv_stderr(65536)
                if channel.exit_status_ready() and not channel.recv_ready():
                    break
                if time.monotonic() - start > timeout:
                    raise RuntimeError('远端步骤超过观察时限；先重新检查实际状态，避免重复安装。')
                time.sleep(.06)
            try:
                result = json.loads(output.decode('utf-8'))
            except (UnicodeError, ValueError):
                raise RuntimeError('远端未返回有效部署结果。确认已安装 Python 3。') from None
            if not result.get('ok'):
                raise RuntimeError(result.get('error', '远端部署步骤未完成。'))
            if operation == 'inspect':
                self.use_sudo = result['result'].get('sudo_available', False) and not result['result'].get('admin', False)
            return result['result']
        finally:
            channel.close()

    def close(self):
        self.client.close()
