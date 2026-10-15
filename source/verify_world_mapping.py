"""Check serialized matrices against saved measured pixels and meter controls."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    root = args.output
    cal = load(root / 'camera_calibration_results_20261014.json')
    k1, d1, k2, d2, r1, r2, p1, p2 = [np.array(cal[key], float) for key in
        ('K_left', 'D_left', 'K_right', 'D_right', 'R1', 'R2', 'P1', 'P2')]
    controls = np.array(load(root / 'evidence/world_control_points_m.json'))
    assert controls.shape == (88, 3)
    np.testing.assert_allclose(controls[0], [-.105, .58, 0], atol=1e-12)
    np.testing.assert_allclose(controls[-1], [.105, .88, 0], atol=1e-12)
    index = load(root / 'table_world_extrinsics.json')
    assert index['active_world_mapping'] is False and index['selected_capture'] is None
    results = []
    for p in sorted((root / 'poses').glob('table_world_*.json')):
        pose = load(p)
        label = p.stem.removeprefix('table_world_')
        measurements = load(root / 'evidence' / f'corners_{label}.json')
        lp, rp = np.array(measurements['left_px']), np.array(measurements['right_px'])
        hcw, hwc = np.array(pose['T_world_to_left_camera']), np.array(pose['T_left_camera_to_world'])
        hrc = np.array(pose['T_world_to_right_camera'])
        np.testing.assert_allclose(hwc @ hcw, np.eye(4), atol=1e-12)
        np.testing.assert_allclose(hcw[:3, :3].T @ hcw[:3, :3], np.eye(3), atol=1e-12)
        assert abs(np.linalg.det(hcw[:3, :3]) - 1) < 1e-12 and hwc[2, 3] > 0
        # Check inverse on off-plane 3D points as well as the fitted plane.
        points = np.vstack([controls, [[0, 0, 0], [.2, .7, .16], [-.3, 1., .4]]])
        homogeneous = np.column_stack([points, np.ones(len(points))])
        np.testing.assert_allclose((hwc @ (hcw @ homogeneous.T)).T, homogeneous, atol=1e-11)
        u = cv2.undistortPoints(lp[:, None], k1, d1, R=r1, P=p1).reshape(-1, 2)
        v = cv2.undistortPoints(rp[:, None], k2, d2, R=r2, P=p2).reshape(-1, 2)
        h = cv2.triangulatePoints(p1, p2, u.T, v.T)
        rect = (h[:3] / h[3]).T
        cam = rect @ r1
        measured_world = (cam - hcw[:3, 3]) @ hcw[:3, :3]
        np.testing.assert_allclose(measured_world, measurements['triangulated_world_m'], atol=1e-11)
        via_direct = np.column_stack([rect, np.ones(len(rect))]) @ np.array(pose['T_rectified_left_to_world']).T
        np.testing.assert_allclose(via_direct[:, :3], measured_world, atol=1e-11)
        fit = cv2.projectPoints(controls, cv2.Rodrigues(hcw[:3, :3])[0], hcw[:3, 3], k1, d1)[0].reshape(-1, 2)
        rms = float(np.sqrt(np.mean(np.sum((fit - lp) ** 2, axis=1))))
        metric = pose['metrics']
        assert abs(rms - metric['delivered_left_reprojection_px']['rms']) < 1e-10
        error3 = float(np.sqrt(np.mean(np.sum((measured_world - controls) ** 2, axis=1))))
        assert abs(error3 - metric['stereo_control_point_error_m']['rms']) < 1e-10
        # Disk compatibility: OpenCV FileStorage reads all matrices and the
        # existing pipeline schema. Unselected configs must remain disabled.
        fs = cv2.FileStorage(str(p.with_suffix('.yml')), cv2.FILE_STORAGE_READ)
        assert fs.isOpened()
        np.testing.assert_allclose(fs.getNode('Rcw').mat(), hcw[:3, :3], atol=1e-12)
        np.testing.assert_allclose(fs.getNode('tcw').mat().ravel(), hcw[:3, 3], atol=1e-12)
        fs.release()
        fs = cv2.FileStorage(str(root / 'poses' / f'pipeline_calibration_{label}.json'), cv2.FILE_STORAGE_READ)
        assert fs.isOpened() and fs.getNode('world_valid').real() == 0
        assert fs.getNode('schema').string() == 'b-calibration-v1-draft'
        np.testing.assert_allclose(fs.getNode('Rcw').mat(), hcw[:3, :3], atol=1e-12)
        fs.release()
        hm = load(root / 'poses' / f'table_plane_homography_{label}.json')
        a, b = np.array(hm['H_world_XY_to_undistorted_pixel']), np.array(hm['H_undistorted_pixel_to_world_XY'])
        np.testing.assert_allclose(a @ b, np.eye(3), atol=1e-10)
        results.append(dict(capture=pose['capture'], checks='PASS', left_reprojection_rms_px=rms, stereo_control_rms_m=error3))
        print(pose['capture'], 'PASS: units / roundtrip / rectification / measured metrics / JSON / YAML / inactive config')
    assert len(results) == 5
    output = dict(numerical_and_serialization_checks='PASS', captures=results,
                  independent_real_world_accuracy='NOT_CERTIFIED',
                  active_video_mapping='NOT_ESTABLISHED', board_placement_confirmed=index['placement_confirmed'])
    (root / 'evidence/verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('5/5 capture records passed; real-world accuracy and video applicability remain unapproved.')


if __name__ == '__main__':
    main()
