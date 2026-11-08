"""MCP stdio / CLI client. Contains no remote URL, deploy key or author identity."""
import argparse
import json
import pathlib
import socket
import sys

OPERATIONS = {
    'status': {}, 'diff': {}, 'log': {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 30}},
    'commit': {'message': {'type': 'string', 'maxLength': 2000}, 'expected_head': {'type': ['string', 'null']}},
    'fetch': {}, 'pull': {'expected_head': {'type': ['string', 'null']}},
    'push': {'expected_head': {'type': ['string', 'null']}},
}


def call(path, project, operation, arguments):
    if operation not in OPERATIONS:
        raise ValueError('Unknown fixed Git operation.')
    request = json.dumps({'project_id': project, 'operation': operation, 'arguments': arguments}).encode() + b'\n'
    if len(request) > 16384:
        raise ValueError('Request too large.')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(330)
        connection.connect(str(path))
        connection.sendall(request)
        data = bytearray()
        while not data.endswith(b'\n'):
            chunk = connection.recv(65536)
            if not chunk:
                raise ValueError('Git service response was interrupted; check status before retrying writes.')
            data.extend(chunk)
            if len(data) > 256 * 1024:
                raise ValueError('Response exceeds limit.')
        response = json.loads(data)
        if not response.get('ok'):
            raise ValueError(response.get('error', 'Git request failed.'))
        return response['result']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', default='/run/orca-git-broker/broker.sock')
    parser.add_argument('--project', required=True)
    parser.add_argument('--operation', choices=list(OPERATIONS))
    parser.add_argument('--arguments', default='{}')
    args = parser.parse_args()
    if args.operation:
        print(json.dumps(call(args.socket, args.project, args.operation, json.loads(args.arguments))))
        return
    for line in sys.stdin:
        request = None
        try:
            if len(line) > 16384:
                raise ValueError('MCP request too large.')
            request = json.loads(line)
            if 'id' not in request:
                continue
            method = request.get('method')
            if method == 'initialize':
                result = {'protocolVersion': request.get('params', {}).get('protocolVersion', '2024-11-05'),
                          'capabilities': {'tools': {}}, 'serverInfo': {'name': 'orca-git-broker', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': [{'name': 'git_' + op,
                                     'description': 'Fixed Git ' + op + '. Identity and credentials stay with the trusted broker. Use status before writes; never pass arbitrary Git arguments.',
                                     'inputSchema': {'type': 'object', 'properties': properties,
                                                     'required': ['message', 'expected_head'] if op == 'commit' else ['expected_head'] if op in ('push', 'pull') else [],
                                                     'additionalProperties': False},
                                     'annotations': {'readOnlyHint': op in ('status', 'diff', 'log'), 'destructiveHint': False}}
                                    for op, properties in OPERATIONS.items()]}
            elif method == 'tools/call':
                params = request['params']
                name = params.get('name', '')
                if not name.startswith('git_') or name[4:] not in OPERATIONS:
                    raise ValueError('Unknown tool.')
                value = call(args.socket, args.project, name[4:], params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=True)}]}
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found.'}}), flush=True)
                continue
            print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
        except Exception as error:
            if isinstance(request, dict) and 'id' in request:
                message = str(error) if isinstance(error, ValueError) else 'Git broker unavailable; check the approved service.'
                print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': {'isError': True,
                                  'content': [{'type': 'text', 'text': message}]}}), flush=True)


if __name__ == '__main__':
    main()
