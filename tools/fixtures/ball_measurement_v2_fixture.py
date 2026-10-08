"""Generate pixel/metadata fixtures; truth is never a CLI input."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def generate(root: Path):
    inputs = root / 'inputs'
    truth_dir = root / 'truth'
    inputs.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    cases, truth = [], []
    seed = 106006
    rng = np.random.default_rng(seed)
    version = 'b-measure-v2-draft'

    def stamp(eye='left'):
        return dict(pair_id='10', eye=eye, sample_time_ns='1000000000', mode_id='gray1280-search640',
                    config_version=version, calibration_version='synthetic-v1')

    def images(center=(640, 360), radius=12, bright=True, with_ball=True, with_mask=True, noise=False):
        bg, fg = (25, 235) if bright else (230, 25)
        gray = np.full((720, 1280), bg, np.uint8)
        mask = np.zeros((360, 640), np.uint8)
        if with_ball:
            cv2.circle(gray, tuple(center), radius, fg, -1)
        if with_mask:
            cv2.circle(mask, (center[0] // 2, center[1] // 2), max(3, radius // 2), 255, -1)
        if noise:
            gray = np.clip(gray.astype(np.int16) + rng.integers(-3, 4, gray.shape), 0, 255).astype(np.uint8)
        return gray, mask

    def add(name, gray, mask, source='observed', center=None, reason=None, eye='left', prediction=None, change=None, quality=None):
        image_path = name + '_gray.png'
        mask_path = name + '_mask.png'
        if not cv2.imwrite(str(inputs / image_path), gray) or not cv2.imwrite(str(inputs / mask_path), mask):
            raise RuntimeError('image output failed')
        image = dict(path=image_path, **stamp(eye))
        motion = dict(path=mask_path, valid=1, reference_valid=1, reference_id='9', **stamp(eye))
        if change:
            change(image, motion)
        case = dict(name=name, image=image, motion=motion)
        if prediction is not None:
            case['prediction'] = dict(target=stamp(eye), source_pair_id='9', source_sample_time_ns='983333333',
                                      image_center=list(prediction), previous_diameter_px=24,
                                      predictor_version='external-fixture-predictor')
        cases.append(case)
        item = dict(name=name, expected_source=source, category='clear' if center is not None and quality is None else 'fault_or_quality')
        if center is not None:
            item['center'] = list(center)
            item['max_error_px'] = 1.0
        if reason:
            item['reason'] = reason
        if quality:
            item['quality'] = quality
        truth.append(item)

    # Diameters 12/20/32/40, both polarities, both eyes and padded/unpadded ROIs.
    for bright in (True, False):
        for radius in (6, 10, 16, 20):
            for i, center in enumerate(((640, 360), (60, 60), (1208, 650))):
                gray, mask = images(center, radius, bright, noise=True)
                add(f'clear_{"bright" if bright else "dark"}_d{2*radius}_p{i}', gray, mask,
                    center=center, eye='right' if i == 2 else 'left')
    # Independent 8x8 pixel-area renderer for fractional, antialiased centers.
    # The C++ algorithm sees only these pixels and a coarse search component.
    for bright in (True, False):
        for radius in (6, 10, 16, 20):
            center = (640.25, 360.75)
            bg, fg = (25, 235) if bright else (230, 25)
            gray = np.full((720, 1280), bg, np.uint8)
            ys, xs = np.mgrid[326:396, 606:676]
            coverage = np.zeros(xs.shape, np.float64)
            offsets = (np.arange(8) + 0.5) / 8 - 0.5
            for oy in offsets:
                for ox in offsets:
                    coverage += ((xs + ox - center[0]) ** 2 + (ys + oy - center[1]) ** 2 <= radius ** 2)
            gray[326:396, 606:676] = np.rint(bg + (fg - bg) * coverage / 64).astype(np.uint8)
            mask = np.zeros((360, 640), np.uint8)
            cv2.circle(mask, (320, 180), max(3, radius // 2), 255, -1)
            add(f'subpixel_{"bright" if bright else "dark"}_d{2*radius}', gray, mask, center=center)
    gray, mask = images(with_ball=False)
    add('uniform_false_mask', gray, mask, 'invalid', reason='low_local_contrast')
    gray, mask = images(bright=False, with_ball=False)
    add('uniform_bright_background_false_mask', gray, mask, 'invalid', reason='low_local_contrast')
    gray, mask = images()
    gray[:] = 100
    cv2.circle(gray, (640, 360), 12, 105, -1)
    add('low_contrast', gray, mask, 'invalid', reason='low_local_contrast')
    gray, mask = images(radius=8)
    cv2.circle(gray, (661, 374), 5, 235, -1)
    add('nearby_distractor_selected_region', gray, mask, center=(640, 360))
    gray, mask = images(with_ball=False)
    gray[:, 640:] = 235
    add('background_step', gray, mask, 'invalid', reason='no_ball_component')
    gray, mask = images(with_ball=False)
    cv2.rectangle(gray, (621, 354), (658, 365), 235, -1)
    add('elongated_foreground', gray, mask, 'invalid', reason='non_ball_shape')
    gray, mask = images(with_ball=False)
    for center in ((626, 360), (654, 360)):
        cv2.circle(gray, center, 8, 235, -1)
    add('local_two_equal_balls', gray, mask, 'invalid', reason='ambiguous_local_components')
    gray, mask = images((700, 360))
    cv2.circle(mask, (300, 180), 8, 255, -1)
    add('old_mask_position', gray, mask, center=(700, 360))
    gray, mask = images((5, 360))
    add('image_clipped_ball', gray, mask, 'invalid', reason='image_boundary_truncation', quality='image_boundary')
    gray, mask = images(with_ball=False)
    cv2.circle(gray, (661, 360), 16, 235, -1)
    add('local_window_clipped_ball', gray, mask, 'invalid', reason='local_boundary_truncation')
    gray, mask = images(radius=16)
    cv2.rectangle(gray, (635, 340), (664, 379), 25, -1)
    add('severe_occlusion', gray, mask, 'invalid', reason='non_ball_shape')
    gray, mask = images(radius=16)
    cv2.rectangle(gray, (650, 342), (664, 377), 25, -1)
    add('partial_occlusion', gray, mask, 'observed', quality='reduced')
    gray, mask = images((643, 359), with_mask=False)
    add('apex_zero_mask_remeasure', gray, mask, center=(643, 359), prediction=(640, 360))
    gray, mask = images(with_ball=False, with_mask=False)
    add('apex_no_ball_prediction_only', gray, mask, 'predicted', reason='prediction_only_no_observation', prediction=(640, 360))
    add('empty_without_prediction', gray, mask, 'invalid', reason='no_motion_candidates')
    gray, mask = images((900, 360))
    add('distant_object_prediction_gate', gray, mask, 'predicted', reason='prediction_only_no_observation', prediction=(640, 360))
    for field, value, reason in (
        ('pair_id', '11', 'pair_id_mismatch'), ('eye', 'right', 'eye_mismatch'),
        ('sample_time_ns', '1000000001', 'sample_time_mismatch'), ('mode_id', 'other', 'mode_mismatch'),
        ('config_version', 'other', 'config_version_mismatch'), ('calibration_version', 'other', 'calibration_version_mismatch')):
        gray, mask = images()
        add('fault_' + field, gray, mask, 'invalid', reason=reason,
            change=lambda image, motion, f=field, v=value: motion.update({f: v}))
    (inputs / 'manifest.json').write_text(json.dumps(dict(interface_version=version, cases=cases), indent=2), encoding='utf-8')
    (truth_dir / 'expected.json').write_text(json.dumps(dict(seed=seed, cases=truth), indent=2), encoding='utf-8')
    sources = [dict(path=p.relative_to(root).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
               for folder in (inputs, truth_dir) for p in sorted(folder.rglob('*')) if p.is_file()]
    (root / 'INPUT_SHA256.json').write_text(json.dumps(dict(source='synthetic, generated locally', license='project-generated test fixtures',
        purpose='2D center and identity checks only; no stereo geometry evidence', seed=seed, files=sources), indent=2), encoding='utf-8')
    print(f'FIXTURES_GENERATED cases={len(cases)} input={inputs / "manifest.json"} truth={truth_dir / "expected.json"}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    generate(parser.parse_args().output)
