"""Convert 3D points or a measured stereo pixel pair using a specific capture pose."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pose', type=Path, required=True)
    ap.add_argument('--point', type=float, nargs=3, help='3D point in meters')
    ap.add_argument('--frame', choices=['left_camera', 'right_camera', 'rectified_left'], default='left_camera')
    ap.add_argument('--pixels', type=float, nargs=4, metavar=('UL', 'VL', 'UR', 'VR'))
    ap.add_argument('--calibration', type=Path, help='Original camera calibration JSON, required for --pixels')
    args = ap.parse_args()
    if (args.point is None) == (args.pixels is None):
        ap.error('Supply exactly one of --point or --pixels')
    pose = json.loads(args.pose.read_text(encoding='utf-8'))
    field = {'left_camera': 'T_left_camera_to_world', 'right_camera': 'T_right_camera_to_world', 'rectified_left': 'T_rectified_left_to_world'}
    result = dict(pose_capture=pose['capture'], unit='m', validity=pose['status'],
                  caution='Numerical conversion for this capture pose; matching actual camera mount is required.')
    frame = args.frame
    if args.pixels is not None:
        if args.calibration is None:
            ap.error('--pixels requires --calibration')
        c = json.loads(args.calibration.read_text(encoding='utf-8'))
        k1, d1, k2, d2, r1, r2, p1, p2 = [np.array(c[key], float) for key in
            ('K_left', 'D_left', 'K_right', 'D_right', 'R1', 'R2', 'P1', 'P2')]
        ul, vl, ur, vr = args.pixels
        if not (0 <= ul < 1280 and 0 <= ur < 1280 and 0 <= vl < 720 and 0 <= vr < 720):
            ap.error('Coordinates must be in each eye ORIGINAL 1280x720 image, not the stitched image')
        left = cv2.undistortPoints(np.array([[[ul, vl]]]), k1, d1, R=r1, P=p1).reshape(1, 2)
        right = cv2.undistortPoints(np.array([[[ur, vr]]]), k2, d2, R=r2, P=p2).reshape(1, 2)
        h = cv2.triangulatePoints(p1, p2, left.T, right.T).ravel()
        if abs(h[3]) < 1e-12:
            raise ValueError('Degenerate stereo point')
        point = h[:3] / h[3]
        if point[2] <= 0:
            raise ValueError('Point behind camera')
        result['rectified_vertical_error_px'] = float(abs(left[0, 1] - right[0, 1]))
        result['disparity_px'] = float(left[0, 0] - right[0, 0])
        result['input_scope'] = 'numerical triangulation only; semantic ball identity/sync not checked'
        frame = 'rectified_left'
    else:
        point = np.array(args.point)
    if not np.isfinite(point).all():
        raise ValueError('Nonfinite input')
    mapped = np.array(pose[field[frame]]) @ np.r_[point, 1.]
    result['world_xyz_m'] = mapped[:3].tolist()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
