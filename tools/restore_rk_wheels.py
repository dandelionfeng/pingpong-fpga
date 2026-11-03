"""Restore app/tools/rk-wheels from the sealed RK deployment archive.

The three aarch64 wheels are stored once, inside app/dist/quick-field-runtime.tar.gz,
to keep the submission archive within its size limit. Board deployment checks
app/files-sha256.json, which also lists app/tools/rk-wheels/*.whl. This script
copies the wheels out of the archive and verifies each against that manifest.
"""
from pathlib import Path
import hashlib, json, sys, tarfile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
ARCHIVE = APP / 'dist' / 'quick-field-runtime.tar.gz'
TARGET = APP / 'tools' / 'rk-wheels'


def main():
    manifest = json.loads((APP / 'files-sha256.json').read_text('utf-8-sig'))
    expected = {r['path']: r['sha256'] for r in manifest['files'] if r['path'].startswith('tools/rk-wheels/')}
    TARGET.mkdir(parents=True, exist_ok=True)
    restored = {}
    with tarfile.open(ARCHIVE) as tar:
        for member in tar.getmembers():
            if not (member.isfile() and member.name.startswith('wheels/') and member.name.endswith('.whl')):
                continue
            name = Path(member.name).name
            data = tar.extractfile(member).read()
            digest = hashlib.sha256(data).hexdigest()
            key = 'tools/rk-wheels/' + name
            if expected.get(key) != digest:
                raise SystemExit(f'Hash mismatch for {name}')
            (TARGET / name).write_bytes(data)
            restored[key] = digest
    missing = sorted(set(expected) - set(restored))
    if missing:
        raise SystemExit('Not found in archive: ' + ', '.join(missing))
    for key in sorted(restored):
        print('OK', key)
    print(f'{len(restored)} wheels restored to {TARGET}')


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print('Failed:', e, file=sys.stderr)
        sys.exit(2)
