"""Syntax, manifest and accidental private configuration checks; no network calls."""
import ast
import json
from pathlib import Path
import re
import subprocess
import shutil

root = Path(__file__).resolve().parents[1]
files = [p for p in root.rglob('*') if p.is_file() and
         not any(x in p.parts for x in ('.git', '__pycache__', 'node_modules'))]
errors = []
node = shutil.which('node')
patterns = [r'gh[pousr]_[A-Za-z0-9_]{20,}', r'github_pat_[A-Za-z0-9_]{20,}',
            r'sk-ant-[A-Za-z0-9_-]{12,}', r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----']
for p in files:
    if p.name in ('client.json', 'config.json', 'launcher.json', 'settings.json') or p.name.endswith('.local.json'):
        errors.append(str(p.relative_to(root)) + ': private runtime file')
    try:
        value = p.read_text(encoding='utf-8-sig')
    except UnicodeError:
        errors.append(str(p.relative_to(root)) + ': unexpected binary')
        continue
    for pattern in patterns:
        if re.search(pattern, value):
            errors.append(str(p.relative_to(root)) + ': credential-like content')
    if p.suffix == '.py':
        ast.parse(value, filename=str(p))
    elif p.suffix in ('.json',):
        json.loads(value)
    elif p.suffix in ('.cjs', '.mjs') and node:
        subprocess.run([node, '--check', str(p)], check=True, capture_output=True)
if errors:
    raise SystemExit('\n'.join(errors))
print(f'PASS: {len(files)} source/documentation files checked; no private runtime files or recognized credentials.')
