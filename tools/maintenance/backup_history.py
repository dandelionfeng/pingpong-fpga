"""Back up explicitly obsolete tracked files before removing them from the checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


KEEP_HANDOFFS = {
    'README.md', 'TEMPLATE.md', '2026-10-05-a-usb-fpga-pipeline.md',
    '2026-10-06-a-vscode-source-build.md',
    '2026-10-06-pr-review-and-b-materials.md',
    '2026-10-06-b-ball-measurement-v2.md',
    '2026-10-06-b-morphology-protocol-fix.md',
}
OLD_REPORTS = {
    'AFH03延期预验证方案核查_20261002.json',
    'PC算法闭环方案文档核查_20261004.json',
    'TD调试归档核查_20261005.json',
    '个人分工段落版文档核查_20261004.json',
    '仓库同步与归档核查_20261004.json',
    '总分工与Agent提示词文档核查_20261004.json',
    '.gitkeep',
}
PLACEHOLDERS = {
    'contracts/.gitkeep', 'fpga/constraints/.gitkeep',
    'vision/calib/.gitkeep', 'vision/quantize/.gitkeep', 'vision/train/.gitkeep',
}
SUBMISSION_DRAFTS = {'第一部分_RTL协议修复PR正文.md', '第一部分_RTL协议修复提交说明.md'}
INDEXES = {
    '.gitignore', 'AGENTS.md', 'README.md', 'archive/README.md',
    'plans/current/README.md', 'fpga/README.md', 'handoffs/README.md', 'reports/README.md',
    'docs/AI_agent协作指南.md', 'docs/实施前待确认项.md', 'docs/PC算法闭环与部署验收.md',
    'docs/OV9281_USB双目模组选型核对.md', 'docs/B接入A交付材料.md',
    'data/manifests/ov9281-usb-module.md', '项目规划/项目实施规划.md',
    '项目规划/接口与验收契约.md', '项目规划/Agent协作交接包.md',
}


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(root), *args])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--backup-root', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='back up, verify, then remove selected files')
    args = parser.parse_args()
    root, backup = args.root.resolve(), args.backup_root.resolve()
    if backup == root or backup.is_relative_to(root):
        raise ValueError('Backup must be outside the checkout')
    if git(root, 'branch', '--show-current').decode().strip() != 'codex/repo-cleanup-20261008':
        raise ValueError('This dated migration is limited to codex/repo-cleanup-20261008')
    names = set(filter(None, git(root, 'ls-files', '-z').decode('utf-8').split('\0')))
    delete = {
        name for name in names
        if (name.startswith('archive/') and name != 'archive/README.md')
        or (name.startswith('handoffs/') and Path(name).name not in KEEP_HANDOFFS
            and (Path(name).name < '2026-10-06' or Path(name).name in {
                'mlk-h10-hardware-review.md', 'simplified-task-plan.md', 'td-batch-smoke.md'}))
        or (name.startswith('reports/') and Path(name).name in OLD_REPORTS)
        or name in PLACEHOLDERS | SUBMISSION_DRAFTS
    }
    move = {'SOURCE_SHA256.json': 'reports/morphology/SOURCE_SHA256_20261006.json'}
    move = {name: target for name, target in move.items() if name in names}
    selected = delete | (INDEXES & names) | set(move)
    print(json.dumps({'delete': len(delete), 'move': move, 'backup_files': len(selected)}, ensure_ascii=False))
    if not args.apply:
        return
    files = []
    # Complete every backup before the first deletion. Keep both checkout and Git bytes.
    for name in sorted(selected):
        source = (root / name).resolve()
        if not source.is_relative_to(root) or source.is_symlink() or not source.is_file():
            raise ValueError(f'Unsafe/missing source: {name}')
        data = source.read_bytes()
        git_data = git(root, 'show', 'HEAD:' + name)
        destinations = [backup / 'files' / name, backup / 'git-bytes' / name]
        for destination, content in zip(destinations, [data, git_data]):
            resolved = destination.resolve()
            if not resolved.is_relative_to(backup):
                raise ValueError(f'Unsafe backup destination: {name}')
            if destination.exists() and destination.read_bytes() != content:
                raise ValueError(f'Different backup already exists: {name}')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            if digest(destination.read_bytes()) != digest(content):
                raise ValueError(f'Backup verification failed: {name}')
        files.append({
            'source_path': name,
            'action': 'delete' if name in delete else 'move' if name in move else 'rewrite-index',
            'bytes': len(data), 'sha256': digest(data),
            'git_bytes': len(git_data), 'git_sha256': digest(git_data),
            'git_blob': git(root, 'rev-parse', 'HEAD:' + name).decode().strip(),
            'local_path': destinations[0].relative_to(backup).as_posix(),
            'git_copy_path': destinations[1].relative_to(backup).as_posix(),
            **({'new_path': move[name]} if name in move else {}),
        })
    record = {
        'schema_version': 1, 'date': '2026-10-08',
        'source_commit': git(root, 'rev-parse', 'HEAD').decode().strip(),
        'source_branch': git(root, 'branch', '--show-current').decode().strip(),
        'backup_root': str(backup), 'checkout_files_before': len(names),
        'delete_count': len(delete), 'move_count': len(move),
        'backup_verified': True, 'files': files,
    }
    raw = (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    (backup / 'manifest.json').write_bytes(raw)
    manifest = root / 'data/manifests/local-history-20261008.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(raw)
    for name, target in move.items():
        destination = (root / target).resolve()
        if not destination.is_relative_to(root) or destination.exists():
            raise ValueError(f'Unsafe/existing move destination: {target}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((backup / 'files' / name).read_bytes())
    for name in sorted(delete | set(move)):
        source = (root / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError(f'Unsafe deletion: {name}')
        original = (backup / 'files' / name).read_bytes()
        if source.read_bytes() != original:
            raise ValueError(f'Source changed after backup: {name}')
        source.unlink()
    print(f'Backups verified; removed {len(delete)} files and relocated {len(move)} manifest(s).')


if __name__ == '__main__':
    main()
