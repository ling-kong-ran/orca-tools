#!/usr/bin/env python3
"""List/select the current Linux host's managed Orca Claude accounts.

Uses Orca's existing local runtime RPC. No OAuth token is printed or copied.
Tested with Orca 1.4.223. This is a tutorial helper, not an official Orca CLI.
"""
import argparse
import json
import os
import pathlib
import socket
import sys
import uuid


def rpc(method, params):
    home = pathlib.Path.home()
    data_dir = pathlib.Path(os.environ.get(
        'ORCA_USER_DATA_PATH',
        str(pathlib.Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'orca'),
    ))
    metadata = json.loads((data_dir / 'orca-runtime.json').read_text())
    transports = metadata.get('transports')
    if not isinstance(transports, list):
        transports = [metadata.get('transport', {})]
    transport = next((t for t in transports if t.get('kind') == 'unix'), None)
    if not transport or not metadata.get('authToken') or not metadata.get('runtimeId'):
        raise RuntimeError('Orca runtime metadata is incomplete. Run this in the VPS workspace shell.')
    request_id = str(uuid.uuid4())
    request = {'id': request_id, 'authToken': metadata['authToken'],
               'method': method, 'params': params}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(75)
        connection.connect(transport['endpoint'])
        connection.sendall((json.dumps(request) + '\n').encode())
        with connection.makefile('rb') as stream:
            while True:
                line = stream.readline(16 * 1024 * 1024)
                if not line:
                    raise RuntimeError('Orca closed the connection before confirming the request.')
                response = json.loads(line)
                if response.get('_keepalive') is True:
                    continue
                if response.get('id') != request_id:
                    raise RuntimeError('Orca returned a mismatched request ID.')
                if response.get('_meta', {}).get('runtimeId') != metadata['runtimeId']:
                    raise RuntimeError('Orca runtime changed. Check the account list before retrying.')
                if response.get('ok') is not True:
                    error = response.get('error', {})
                    raise RuntimeError(str(error.get('message', 'Orca rejected the request.')))
                return response['result']


def snapshot():
    return rpc('accounts.list', {'refreshUsage': False})['claude']


def show(state):
    print('VPS host:', socket.gethostname())
    accounts = state.get('accounts', [])
    if not accounts:
        print('No managed Claude accounts on this host.')
    for number, account in enumerate(accounts, 1):
        marker = '  [CURRENT]' if account['id'] == state.get('activeAccountId') else ''
        print(f"{number}. {account.get('email', account['id'])}{marker}")
    if not state.get('activeAccountId'):
        print('Current selection: system default (no managed account selected).')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--list', action='store_true', help='Show accounts without changing selection')
    group.add_argument('--select', metavar='EMAIL', help='Select one registered email')
    args = parser.parse_args()
    if sys.platform != 'linux':
        raise RuntimeError('Run this helper in the VPS Linux workspace terminal.')
    state = snapshot()
    show(state)
    if args.list:
        return
    accounts = state.get('accounts', [])
    if not accounts:
        return
    selection = args.select
    if selection is None:
        selection = input('Choose account number or email (Enter cancels): ').strip()
        if not selection:
            print('Cancelled. No account changed.')
            return
        if selection.isdigit():
            number = int(selection)
            if not 1 <= number <= len(accounts):
                raise RuntimeError('Account number is out of range. No account changed.')
            selection = accounts[number - 1].get('email', '')
    matches = [a for a in accounts if a.get('email', '').casefold() == selection.strip().casefold()]
    if len(matches) != 1:
        raise RuntimeError('Email must identify exactly one registered account. No account changed.')
    account = matches[0]
    if state.get('activeAccountId') == account['id']:
        print('Already selected:', account['email'])
        return
    print('Selecting:', account['email'], flush=True)
    rpc('accounts.selectClaude', {'accountId': account['id']})
    after = snapshot()
    if after.get('activeAccountId') != account['id']:
        raise RuntimeError('Selection not confirmed. Check --list before retrying.')
    print('SELECTED:', account['email'])
    print('Start a new Claude session in this VPS project to use the selected account.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nInterrupted. Check --list before retrying.', file=sys.stderr)
        sys.exit(130)
