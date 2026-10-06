"""Verify and package generated A-to-B inputs; no metric or model truth."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np
from PIL import Image

from verify_rtl import gaussian, morphology


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-dir', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--code-commit', required=True)
    args = parser.parse_args()
    root = Path(args.fixture_dir).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit('Choose a fresh ZIP output; existing packages are preserved')
    manifest = json.loads((root / 'inputs/manifest.json').read_text(encoding='utf-8'))
    records = [json.loads(line) for line in (root / 'cpu/frames.jsonl').read_text().splitlines()]
    mock = [json.loads(line) for line in (root / 'mock/frames.jsonl').read_text().splitlines()]
    cpu_run = json.loads((root / 'cpu/run.json').read_text(encoding='utf-8'))
    mock_run = json.loads((root / 'mock/run.json').read_text(encoding='utf-8'))
    assert cpu_run['status'] == mock_run['status'] == 'passed'
    assert cpu_run['errors'] == mock_run['errors'] == 0
    assert cpu_run['mask_sequence_sha256'] == mock_run['mask_sequence_sha256']
    assert len(manifest['frames']) == len(records) == len(mock) == 8
    assert manifest['geometry_status'] == 'synthetic_not_metric_stereo'
    stages = ['gaussian', 'difference', 'threshold', 'erode1', 'dilate1', 'dilate2', 'erode2']
    previous = [None, None]
    image_count = pixel_count = 0
    entries, extra = [], {}

    def check_image(path, expected):
        nonlocal image_count, pixel_count
        actual = np.asarray(Image.open(path))
        assert actual.shape == expected.shape, f'Shape mismatch: {path}'
        assert np.array_equal(actual, expected), f'Pixel mismatch: {path}'
        image_count += 1
        pixel_count += expected.size

    for position, (frame, record, simulated) in enumerate(zip(manifest['frames'], records, mock)):
        assert record['motion_valid'] and simulated['motion_valid']
        assert record['pair_id'] == simulated['pair_id'] == frame['pair_id']
        assert record['timestamp_ns'] == simulated['timestamp_ns'] == frame['timestamp_ns']
        if frame['format'] == 'YUY2':
            raw = (root / 'inputs' / frame['file']).read_bytes()
            assert digest(raw) == frame['sha256']
            y = np.frombuffer(raw, np.uint8).reshape(720, frame['stride'])[:, :5120:2]
            originals = [y[:, :1280], y[:, 1280:]]
        else:
            originals = []
            for eye in ('left', 'right'):
                raw = (root / 'inputs' / frame[eye + '_file']).read_bytes()
                assert digest(raw) == frame[eye + '_sha256']
                originals.append(np.frombuffer(raw, np.uint8).reshape(720, frame['stride'])[:, :1280])
        assert not np.array_equal(*originals), 'Fixture eyes must differ'
        sample = {key: frame[key] for key in ('pair_id', 'timestamp_ns', 'eye_timestamp_ns',
                                             'config_version', 'calibration_version', 'model_version',
                                             'time_source', 'source')}
        sample['eyes'] = []
        for eye_index, (eye, original) in enumerate(zip(('left', 'right'), originals)):
            folder = f"cpu/images/pair_{frame['pair_id']:08d}/{eye}"
            values = original.astype(np.uint16)
            search = ((values[::2, ::2] + values[::2, 1::2] +
                       values[1::2, ::2] + values[1::2, 1::2] + 2) >> 2).astype(np.uint8)
            blurred = gaussian(search)
            difference = (np.abs(blurred.astype(np.int16) - previous[eye_index].astype(np.int16))
                          .astype(np.uint8) if position else np.zeros_like(blurred))
            expected = [blurred, difference, (difference > 12).astype(np.uint8) * 255]
            for dilation in (False, True, True, False):
                expected.append(morphology(expected[-1], dilation))
            check_image(root / folder / 'original.png', original)
            check_image(root / folder / 'search.png', search)
            for name, pixels in zip(stages, expected):
                check_image(root / folder / (name + '.png'), pixels)
            check_image(root / folder / 'mask.png', expected[-1])
            check_image(root / folder / 'roi_inspection_center.png', original[232:488, 512:768])
            packed = np.packbits(expected[-1].ravel() != 0, bitorder='little').tobytes()
            assert (root / folder / 'mask_lsb.bin').read_bytes() == packed
            meta = record['eyes'][eye_index]
            other = simulated['eyes'][eye_index]
            for key in ('reference_valid', 'reference_id', 'reference_timestamp_ns', 'mask_sha256'):
                assert meta[key] == other[key], f'CPU/mock metadata mismatch: {key}'
            assert meta['reference_valid'] == (position != 0)
            assert meta['reference_id'] == (manifest['frames'][position - 1]['pair_id'] if position else 0)
            assert meta['mask_sha256'] == digest(expected[-1].tobytes())
            threshold_path = folder + '/threshold_lsb.bin'
            extra[threshold_path] = np.packbits(expected[2].ravel() != 0, bitorder='little').tobytes()
            sample['eyes'].append({
                'eye': eye, 'original': folder + '/original.png',
                'search': folder + '/search.png', 'threshold': folder + '/threshold.png',
                'threshold_lsb': threshold_path, 'mask': folder + '/mask.png',
                'mask_lsb': folder + '/mask_lsb.bin',
                'stages': {name: folder + '/' + name + '.png' for name in stages},
                **{key: meta[key] for key in ('reference_valid', 'reference_id',
                                              'reference_timestamp_ns', 'mask_sha256')}})
            previous[eye_index] = blurred
        entries.append(sample)
    index = {'schema_version': 1, 'purpose': 'A/B file integration evidence index',
             'code_commit': args.code_commit, 'geometry_status': manifest['geometry_status'],
             'model_status': 'unavailable', 'hardware_status': 'not_executed',
             'coordinate_mapping': 'original_center = 2 * search_center + 0.5',
             'mask_layout': 'row-major, pixel 0 = byte bit 0, draft', 'frames': entries}
    extra['sample-index.json'] = json.dumps(index, ensure_ascii=False, indent=2).encode('utf-8')
    extra['README.md'] = (
        '# A/B 人工输入与黄金输出\n\n'
        '8 对独立双眼人工图；输入含 YUY2/GRAY8、中文文件名与行填充。16 ms 为人工采样间隔。'
        '没有米制标定、模型推理或相机实测真值。\n\n'
        '`inputs/manifest.json` 供 A CLI 导入；`sample-index.json` 是便携文件索引，供 B 适配层读取。'
        '索引中的原图、阈值、七级阶段、Mask、参考身份均属于同一来源帧。'
        '首帧 `reference_valid=false`，不得作为球观测。二值 PNG 为 0/255；LSB 文件每字节低位对应较早像素。\n\n'
        '`cpu/` 是本次实际 CLI 导出，`mock/` 为模拟 DMA 结果；NumPy/Pillow 独立像素核对后打包。'
        '检测框 `inputs/replay.json` 是人工回放提示，不能作为测量真值。'
        '`SHA256SUMS.txt` 覆盖每个文件。\n\n'
        '复现从仓库 `docs/B接入A交付材料.md` 进入；无需使用本包日志中的原电脑绝对路径。\n'
    ).encode('utf-8')
    files = {path.relative_to(root).as_posix(): path.read_bytes()
             for name in ('inputs', 'cpu', 'mock') for path in (root / name).rglob('*') if path.is_file()}
    files.update(extra)
    checksums = {name: digest(content) for name, content in sorted(files.items())}
    files['SHA256SUMS.txt'] = ''.join(f'{sha}  {name}\n' for name, sha in checksums.items()).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as package:
        for name, content in sorted(files.items()):
            entry = ZipInfo(name, date_time=(2026, 10, 6, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, content, compresslevel=9)
    report = {'schema_version': 1, 'status': 'passed', 'pairs': len(entries),
              'eyes_are_distinct': True, 'images_checked': image_count, 'pixels_checked': pixel_count,
              'oracle': 'NumPy direct convolution/boolean windows, Pillow decode, independent Y extraction',
              'cpu_mock_equivalent': True, 'code_commit': args.code_commit,
              'mask_sequence_sha256': cpu_run['mask_sequence_sha256'],
              'zip_name': output.name, 'zip_bytes': output.stat().st_size,
              'zip_sha256': digest(output.read_bytes()), 'file_count': len(files),
              'input_hashes': {name: sha for name, sha in checksums.items() if name.startswith('inputs/')},
              'scope': 'synthetic input and A CPU/mock front end; B measurement/model/metric accuracy not asserted'}
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
