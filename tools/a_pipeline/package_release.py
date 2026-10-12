"""Stage a fresh Windows portable package; copy only tracked source and supplied fixtures."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--build', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--licenses', required=True, help='License notices for the same OpenCV/Qt versions')
    p.add_argument('--crt', required=True)
    p.add_argument('--legacy-fixture', required=True)
    p.add_argument('--mjpeg-fixture', required=True)
    p.add_argument('--evidence')
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    build, output = Path(a.build).resolve(), Path(a.output).resolve()
    version = re.search(r'project\([^\n]*VERSION\s+([\d.]+)',
                        (repo/'software/pc_pipeline/CMakeLists.txt').read_text(encoding='utf-8')).group(1)
    if output.exists():
        raise SystemExit('Choose a fresh output directory')
    for path in (build/'pipeline_cli.exe', build/'pipeline_gui.exe', Path(a.licenses),
                 Path(a.crt), Path(a.legacy_fixture)/'manifest.json', Path(a.mjpeg_fixture)/'manifest.json'):
        if not path.exists():
            raise SystemExit(f'Missing packaging dependency: {path}')
    output.mkdir(parents=True)
    for path in list(build.glob('*.dll')) + [build/'pipeline_cli.exe', build/'pipeline_gui.exe']:
        shutil.copy2(path, output/path.name)
    for name in ('platforms', 'styles', 'imageformats', 'generic', 'networkinformation', 'tls'):
        if (build/name).is_dir():
            shutil.copytree(build/name, output/name)
    crt = Path(a.crt)
    for path in crt.glob('*.dll'):
        shutil.copy2(path, output/path.name)
    openmp = crt.parent/'Microsoft.VC143.OpenMP/vcomp140.dll'
    if openmp.exists():
        shutil.copy2(openmp, output/openmp.name)
    shutil.copytree(a.licenses, output/'licenses')
    for name in ('configs', 'contracts'):
        shutil.copytree(repo/'software/pc_pipeline'/name, output/name)
    for original, name in ((a.legacy_fixture, 'fixtures'), (a.mjpeg_fixture, 'fixtures-mjpeg')):
        source = Path(original)
        target = output/name
        target.mkdir()
        manifest = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
        for frame in manifest['frames']:
            for key in ('file', 'left_file', 'right_file'):
                if key not in frame:
                    continue
                item = Path(frame[key])
                if not item.is_absolute():
                    item = source/item
                if hashlib.sha256(item.read_bytes()).hexdigest() != frame[key.replace('file', 'sha256')]:
                    raise RuntimeError(f'Fixture hash mismatch: {item}')
                shutil.copy2(item, target/item.name)
                frame[key] = item.name
        (target/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        for extra in ('replay.json', 'export.json', 'pairs.csv'):
            if (source/extra).is_file():
                shutil.copy2(source/extra, target/extra)
    # git ls-files excludes ignored build products, models, SDKs, media and local archives.
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=repo).decode('utf-8').split('\0')
    prefixes = ('software/pc_pipeline/', 'tools/a_pipeline/', 'fpga/rtl/a_motion/',
                'fpga/sim/a_motion/', 'fpga/projects/a_motion_td/')
    for name in tracked:
        path = repo/name
        if name.startswith(prefixes) and path.is_file():
            target = output/'source'/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    if a.evidence:
        shutil.copytree(a.evidence, output/'evidence')
    shutil.copy2(repo/'software/pc_pipeline/README.md', output/'使用与构建说明.md')
    (output/'qt.conf').write_text('[Paths]\nPlugins=.\n', encoding='ascii')
    (output/'启动回放界面.cmd').write_text('@echo off\ncd /d "%~dp0"\nstart "" "%~dp0pipeline_gui.exe"\n', encoding='ascii')
    for filename, fixture in (('检查固定样例.cmd', 'fixtures'), ('检查MJPEG样例.cmd', 'fixtures-mjpeg')):
        (output/filename).write_text('@echo off\ncd /d "%~dp0"\n"%~dp0pipeline_cli.exe" --input "%~dp0' +
            fixture + '\\manifest.json" --output "%~dp0results\\fixture-%RANDOM%" --motion mock-dma\npause\n', encoding='ascii')
    (output/'开始使用.md').write_text(f'''# A 双目处理工作台 {version}

双击“启动回放界面.cmd”，打开 fixtures-mjpeg/manifest.json 可检查 MJPEG；fixtures/manifest.json 是原有 YUY2/GRAY8 样例。含 export.json/pairs.csv 的文件夹可用“导入截图包”。播放、暂停、寻帧、阶段查看、ROI 和导出入口保持原样。

“检查MJPEG样例.cmd”运行人工 JPEG 的模拟 DMA 回归；“检查固定样例.cmd”运行原人工输入。人工框回放与实际模型分别标记。B/C 实际模块未随此输入补丁接入。

本包为 Windows x64。Linux V4L2 相机输入默认先尝试 YUYV 2560×720@60，再尝试 MJPG 同尺寸帧率。Windows 保留文件回放入口；本版未增加 Windows 实时相机后端。JPEG 解码为 GRAY8 后使用原七级算法，阈值与所有配置未变。真实相机吞吐、同步及压缩后的测量精度尚待实测。

源码在 source/；完整仓库源码另有 source ZIP。构建固定 OpenCV 4.13.0、Qt 6.8.3、C++17。Qt 采用可替换共享库，许可证见 licenses/，对应源码 https://download.qt.io/archive/qt/6.8/6.8.3/submodules/qtbase-everywhere-src-6.8.3.tar.xz 。OpenCV 来源 https://github.com/opencv/opencv/releases/tag/4.13.0 ，第三方通知在 licenses/opencv/。MSVC 运行库来自 Visual Studio 可再分发目录。
''', encoding='utf-8')
    hashes = {str(path.relative_to(output)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(output.rglob('*')) if path.is_file()}
    (output/'files-sha256.json').write_text(json.dumps({'version': version, 'files': hashes}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'staged', 'version': version, 'path': str(output), 'files': len(hashes)}))


if __name__ == '__main__':
    main()
