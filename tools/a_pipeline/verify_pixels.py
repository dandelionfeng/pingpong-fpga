"""Independent NumPy/Pillow checks of all exported pixels and metadata."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from PIL import Image
from verify_rtl import gaussian, morphology


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--manifest', required=True)
    p.add_argument('--run', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--gui')
    a = p.parse_args()
    manifest = json.loads(Path(a.manifest).read_text(encoding='utf-8'))
    root = Path(a.run)
    report = {'status': 'running', 'pairs': 0, 'images_checked': 0,
              'pixels_checked': 0, 'first_difference': None,
              'oracle': 'NumPy direct 9-tap convolution and boolean windows',
              'manifest_sha256': hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest()}
    names = ['gaussian', 'difference', 'threshold', 'erode1', 'dilate1', 'dilate2', 'erode2']
    previous = [None, None]
    records = [json.loads(x) for x in (root / 'frames.jsonl').read_text().splitlines()]

    def check(path, expected):
        actual = np.asarray(Image.open(path))
        if actual.shape != expected.shape:
            raise AssertionError(f'shape: {path}: {actual.shape} != {expected.shape}')
        differences = np.argwhere(actual != expected)
        if len(differences):
            y, x = map(int, differences[0])
            report['first_difference'] = {'path': str(path), 'x': x, 'y': y,
                                          'expected': int(expected[y, x]), 'actual': int(actual[y, x]),
                                          'different_pixels': len(differences)}
            raise AssertionError(f'pixel difference: {path}')
        report['images_checked'] += 1
        report['pixels_checked'] += expected.size

    try:
        assert len(records) == len(manifest['frames']) == 125
        for i, entry in enumerate(manifest['frames']):
            record = records[i]
            assert record['pair_id'] == entry['pair_id']
            assert record['timestamp_ns'] == entry['timestamp_ns']
            assert record['motion_valid']
            raw_bytes = Path(entry['file']).read_bytes()
            assert hashlib.sha256(raw_bytes).hexdigest() == entry['sha256']
            raw = np.frombuffer(raw_bytes, np.uint8).reshape(720, entry['stride'])[:, :5120:2]
            assert np.array_equal(raw[:, :1280], raw[:, 1280:])
            for e, eye in enumerate(('left', 'right')):
                directory = root / 'images' / f"pair_{entry['pair_id']:08d}" / eye
                original = raw[:, e*1280:(e+1)*1280]
                im = original.astype(np.uint16)
                search = ((im[::2, ::2] + im[::2, 1::2] + im[1::2, ::2] + im[1::2, 1::2] + 2)//4).astype(np.uint8)
                g = gaussian(search)
                diff = np.abs(g.astype(np.int16) - previous[e].astype(np.int16)).astype(np.uint8) if i else np.zeros_like(g)
                threshold = (diff > 12).astype(np.uint8)*255
                stages = [g, diff, threshold]
                for dilation in (False, True, True, False):
                    stages.append(morphology(stages[-1], dilation))
                check(directory/'original.png', original)
                check(directory/'search.png', search)
                for name, image in zip(names, stages):
                    check(directory/(name+'.png'), image)
                check(directory/'mask.png', stages[-1])
                check(directory/'roi_inspection_center.png', original[232:488, 512:768])
                assert (directory/'mask_lsb.bin').read_bytes() == np.packbits(stages[-1].ravel() != 0, bitorder='little').tobytes()
                metadata = record['eyes'][e]
                assert metadata['reference_valid'] == (i != 0)
                assert metadata['reference_id'] == (manifest['frames'][i-1]['pair_id'] if i else 0)
                assert metadata['mask_sha256'] == hashlib.sha256(stages[-1].tobytes()).hexdigest()
                previous[e] = g
                if a.gui and i == 56:
                    gui = Path(a.gui)/'snapshot'/'images'/f"pair_{entry['pair_id']:08d}"/eye
                    for name, image in zip(names, stages):
                        check(gui/(name+'.png'), image)
            report['pairs'] += 1
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = str(exc)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
