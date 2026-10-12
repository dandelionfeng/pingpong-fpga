"""Independent Pillow JPEG inputs; synthetic timing and geometry, no model truth."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--pairs', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.pairs <= 10000:
        parser.error('pairs must be 1..10000')
    root = Path(args.output).resolve()
    if root.exists():
        parser.error('choose a fresh output directory')
    root.mkdir(parents=True)
    y, x = np.indices((720, 1280))
    frames, rows, detections = [], [], []
    for index in range(args.pairs):
        eyes = []
        for eye in range(2):
            image = (24 + ((x // 32 + y // 32 + eye * 30) % 90)).astype(np.uint8)
            cx, cy = 240 + (index * 7 % 800) - eye * 24, 340 - (index * 3 % 200)
            image[(x - cx) ** 2 + (y - cy) ** 2 <= 18 ** 2] = 235
            eyes.append(image)
            detections.append({'source_pair_id': index + 1, 'eye': 'right' if eye else 'left',
                               'model_version': 'synthetic-box-replay-v1',
                               'boxes': [{'class': 'ball', 'confidence': 1.0, 'bbox': [cx-18, cy-18, 37, 37]}]})
        name = f'双目_{index+1:06d}.jpg'
        Image.fromarray(np.concatenate(eyes, axis=1)).save(root / name, quality=95)
        time_ns = (index + 1) * 16000000
        frames.append({'pair_id': index + 1, 'timestamp_ns': time_ns,
                       'eye_timestamp_ns': [time_ns, time_ns], 'camera_frame_id': [index+1, index+1],
                       'format': 'MJPG', 'width': 2560, 'height': 720, 'stride': 0,
                       'file': str(root / name), 'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest(),
                       'config_version': 'a-int-v1', 'calibration_version': 'unavailable',
                       'model_version': 'unavailable', 'time_source': 'synthetic_16ms_fixture',
                       'source': 'synthetic_mjpeg_fixture'})
        rows.append([index+1, index+1, index+1, f'{time_ns / 1e9:.9f}', f'{time_ns / 1e9:.9f}', name])
    (root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'mode': 'file',
        'geometry_status': 'synthetic_not_metric_stereo', 'generator_version': 'a-mjpeg-fixture-v1',
        'frames': frames}, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'export.json').write_text(json.dumps({'pixel_format': 'MJPG', 'geometry_status': 'synthetic_not_metric_stereo',
        'source': 'Pillow generated artificial JPEGs; no camera/video',
        'time_source': 'synthetic_16ms_fixture'}, indent=2), encoding='utf-8')
    with (root / 'pairs.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['pair_index', 'left_index', 'right_index', 'left_requested_time_seconds',
                         'right_requested_time_seconds', 'pair_file'])
        writer.writerows(rows)
    (root / 'replay.json').write_text(json.dumps({'schema_version': 1, 'provenance': 'synthetic_fixture_not_model',
        'detections': detections}, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'generated', 'pairs': args.pairs, 'manifest': str(root / 'manifest.json')}))


if __name__ == '__main__':
    main()
