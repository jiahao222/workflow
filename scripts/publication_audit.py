"""Simple portfolio static content guard. Complements, not replaces, review."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {'.py','.md','.json','.yml','.yaml','.toml','.example','.gitignore'}
PATTERNS = {
    'private_key': r'-----BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY-----',
    'github_token': r'gh[pousr]_[A-Za-z0-9]{20,}',
    'cloud_key': r'AKIA[0-9A-Z]{16}',
    'google_key': r'AIza[0-9A-Za-z_-]{20,}',
    'openai_key': r'sk-[A-Za-z0-9_-]{20,}',
}
SKIP_PARTS = {'.git','.local','__pycache__','.venv'}
findings = []
for path in ROOT.rglob('*'):
    if not path.is_file() or any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts):
        continue
    if path.suffix not in EXTENSIONS and path.name not in {'Makefile','.gitignore'}:
        continue
    data = path.read_text(encoding='utf-8')
    for key, pattern in PATTERNS.items():
        if re.search(pattern, data) and path.name != 'publication_audit.py':
            findings.append((str(path.relative_to(ROOT)), key))
if findings:
    for path,key in findings: print(f'FLAG {path}: {key}')
    raise SystemExit(1)
print('CHECK PASSED: no common secret patterns found; manual business/IP review still required.')
