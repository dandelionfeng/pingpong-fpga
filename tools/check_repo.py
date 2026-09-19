"""Small repository hygiene check; no FPGA or model correctness claims."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

LIMIT = 10 * 1024 * 1024
TEXT = {'.md', '.py', '.ps1', '.sh', '.v', '.sv', '.vh', '.svh', '.c', '.h', '.cpp', '.hpp', '.json', '.yaml', '.yml', '.tcl', '.sdc', '.xdc', '.txt', '.toml'}
ARTIFACTS = {'.pt', '.pth', '.onnx', '.rknn', '.bit', '.fs', '.pcap', '.pcapng', '.mp4', '.avi', '.pem', '.key', '.lic'}
CONFLICT = re.compile(rb'^(?:<<<<<<< .+|=======|>>>>>>> .+)\r?$', re.MULTILINE)
SECRETS = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')

def inspect_file(name, content):
    path = Path(name)
    problems = []
    if len(content) > LIMIT:
        problems.append('file exceeds 10 MiB; use artifact manifest')
    if path.suffix.lower() in ARTIFACTS or (path.name.startswith('.env') and path.name != '.env.example'):
        problems.append('credential or generated artifact filename')
    if name.startswith(('tmp/', 'vendor/', 'data/raw/', 'artifacts/files/')):
        problems.append('local-only directory')
    if path.suffix.lower() in TEXT or path.name.startswith('.') or name.startswith('.githooks/'):
        if CONFLICT.search(content):
            problems.append('unresolved merge conflict marker')
        if SECRETS.search(content):
            problems.append('possible credential; value suppressed')
    return problems

def git(*args):
    return subprocess.check_output(['git', *args])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='inspect the complete Git index rather than working files')
    args = parser.parse_args()
    root = Path(git('rev-parse', '--show-toplevel').decode().strip())
    names = git('ls-files', '-z').decode('utf-8').split('\0')
    failures = []
    count = 0
    for name in filter(None, names):
        if args.staged:
            content = git('show', ':' + name)
        else:
            path = root / name
            if not path.is_file():
                failures.append((name, 'tracked file missing'))
                continue
            content = path.read_bytes()
        count += 1
        failures.extend((name, problem) for problem in inspect_file(name, content))
    for name, problem in failures:
        print(f'FAIL {name}: {problem}')
    print(f'Checked {count} tracked files; {len(failures)} problem(s).')
    return bool(failures)

if __name__ == '__main__':
    sys.exit(main())
