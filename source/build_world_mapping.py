"""Reproduce per-capture table mappings without averaging different camera poses."""
import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path

import cv2
import numpy as np
import scipy
from scipy.optimize import least_squares


def read_image(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project(points, rv, tv, k, d):
    return cv2.projectPoints(points, rv, tv, k, d)[0].reshape(-1, 2)


def detect(eye, crop):
    flags = cv2.CALIB_CB_NORMALIZE_IMAGE
    ok, corners = cv2.findChessboardCornersSB(cv2.cvtColor(eye, cv2.COLOR_BGR2GRAY), (11, 8), flags)
    if ok:
        return corners.reshape(8, 11, 2).astype(np.float64), 'full_frame_SB_normalize'
    x0, y0, x1, y1 = crop
    grey = cv2.cvtColor(eye[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    for scale in (1, 2, 3):
        up = cv2.resize(grey, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ok, corners = cv2.findChessboardCornersSB(up, (11, 8), flags | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
        if ok:
            # Resize changes pixel-center coordinates: invert that change before
            # using the ORIGINAL 1280x720 intrinsics. No image scaling of K.
            corners = (corners.astype(np.float64) + 0.5) / scale - 0.5 + [x0, y0]
            return corners.reshape(8, 11, 2), f'crop_SB_{crop}_scale_{scale}_coordinates_restored'
    raise RuntimeError('Cannot detect all 88 corners')


def canonicalize(grid, near, world, k, d):
    # Long-axis column 0 must be the inner-corner row nearest the net.
    a, b = grid[:, 0].mean(axis=0), grid[:, -1].mean(axis=0)
    if (near == 'top' and a[1] > b[1]) or (near == 'bottom' and a[1] < b[1]) or (near == 'right' and a[0] < b[0]):
        grid = grid[:, ::-1].copy()
    ok, rv, tv = cv2.solvePnP(world, grid.reshape(-1, 2), k, d)
    if not ok:
        raise RuntimeError('solvePnP failed')
    r = cv2.Rodrigues(rv)[0]
    # Select the printed/top normal, giving camera center Z > 0 in a
    # right-handed X,Y,Z coordinate system. This also fixes transverse order.
    if (-r.T @ tv)[2, 0] < 0:
        grid = grid[::-1].copy()
        ok, rv, tv = cv2.solvePnP(world, grid.reshape(-1, 2), k, d)
        if not ok:
            raise RuntimeError('solvePnP failed after ordering')
    return grid, rv, tv


def rt_matrix(r, t):
    h = np.eye(4)
    h[:3, :3], h[:3, 3] = r, np.asarray(t).reshape(3)
    return h


def stats(error):
    v = np.asarray(error)
    return dict(rms=float(np.sqrt(np.mean(v * v))), max=float(np.max(np.abs(v))))


def calibration_config(cal, rv, tv, valid, label):
    out = dict(schema='b-calibration-v1-draft', version=f'ov9281-20261014-world-{label}', unit='m',
               provenance='real images; declared 30mm grid and 0.55m board edge; camera-pose-specific; see REPORT.md',
               width=1280, height=720, world_valid=int(valid),
               mono_rms_left=cal['left_rms_px'], mono_rms_right=cal['right_rms_px'], stereo_rms=cal['stereo_rms_px'])
    mapping = dict(K1='K_left', D1='D_left', K2='K_right', D2='D_right', R='R_left_to_right', T='T_m',
                   R1='R1', R2='R2', P1='P1', P2='P2')
    matrices = {key: np.array(cal[source], np.float64) for key, source in mapping.items()}
    matrices['T'] = matrices['T'].reshape(3, 1)
    matrices['D1'] = matrices['D1'].reshape(1, -1)
    matrices['D2'] = matrices['D2'].reshape(1, -1)
    matrices['Rcw'], matrices['tcw'] = cv2.Rodrigues(rv)[0], tv.reshape(3, 1)
    for key, mat in matrices.items():
        out[key] = {'type_id': 'opencv-matrix', 'rows': mat.shape[0], 'cols': mat.shape[1], 'dt': 'd', 'data': mat.ravel().tolist()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True, help='PartV directory')
    ap.add_argument('--calibration', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--placement-confirmed', action='store_true', help='All PartV views use the same declared board placement')
    args = ap.parse_args()
    out = args.output
    for sub in ('poses', 'previews', 'evidence', 'source'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    c = json.loads(args.calibration.read_text(encoding='utf-8'))
    k1, d1, k2, d2, rs, ts, r1, r2, p1, p2 = [np.array(c[key], np.float64) for key in
        ('K_left', 'D_left', 'K_right', 'D_right', 'R_left_to_right', 'T_m', 'R1', 'R2', 'P1', 'P2')]
    ts = ts.reshape(3, 1)
    # 12 long x 9 short squares => 11 long x 8 short INTERNAL corners.
    # 0.55m is measured to the BLACK/WHITE GRID EDGE, excluding white margin.
    world = np.array([[-0.135 + (j + 1) * 0.03, 0.55 + (i + 1) * 0.03, 0.0]
                      for j in range(8) for i in range(11)], np.float64)
    dump(out / 'evidence/world_control_points_m.json', world.tolist())
    # Coarse crops only help detection. They do not define world geometry.
    capture = {
        '20261014204558': ('bottom', [(510, 90, 810, 290), (420, 50, 690, 230)]),
        '20261014204646': ('top', [(470, 370, 830, 720), (320, 300, 680, 700)]),
        '20261014204705': ('top', [(330, 20, 930, 720), (50, 0, 700, 720)]),
        '20261014204733': ('top', [(500, 300, 810, 550), (390, 240, 710, 500)]),
        '20261014204804': ('right', [(280, 300, 740, 670), (180, 250, 600, 620)]),
    }
    results = []
    inputs = []
    for label, (near, boxes) in capture.items():
        path = args.source / (label + '.bmp')
        im = read_image(path)
        if im is None or im.shape[:2] != (720, 2560):
            raise RuntimeError(f'Invalid input dimensions: {path}')
        eyes = [im[:, :1280].copy(), im[:, 1280:].copy()]
        lp, methodl = detect(eyes[0], boxes[0])
        rp, methodr = detect(eyes[1], boxes[1])
        lp, rv, tv = canonicalize(lp, near, world, k1, d1)
        rp, rvr, tvr = canonicalize(rp, near, world, k2, d2)
        lp, rp = lp.reshape(-1, 2), rp.reshape(-1, 2)

        def residual(v):
            rot = cv2.Rodrigues(v[:3])[0]
            rright = rs @ rot
            tright = rs @ v[3:].reshape(3, 1) + ts
            l = project(world, v[:3], v[3:], k1, d1) - lp
            r = project(world, cv2.Rodrigues(rright)[0], tright, k2, d2) - rp
            return np.concatenate([l.ravel(), r.ravel()])

        opt = least_squares(residual, np.r_[rv.ravel(), tv.ravel()], method='lm', xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=500)
        rvj, tvj = opt.x[:3], opt.x[3:].reshape(3, 1)
        # The route specifies solvePnP(world -> LEFT camera). Keep that as
        # the delivered mapping. Joint two-eye fitting is DIAGNOSTIC only.
        rcw = cv2.Rodrigues(rv)[0]
        rwc, twc = rcw.T, -rcw.T @ tv
        hcw, hwc = rt_matrix(rcw, tv), rt_matrix(rwc, twc)
        hright = rt_matrix(rs @ rcw, rs @ tv + ts)
        # Rectified left coordinates are rotated camera coordinates.
        hrw = rt_matrix(rwc @ r1.T, twc)
        ul = cv2.undistortPoints(lp.reshape(-1, 1, 2), k1, d1, R=r1, P=p1).reshape(-1, 2)
        ur = cv2.undistortPoints(rp.reshape(-1, 1, 2), k2, d2, R=r2, P=p2).reshape(-1, 2)
        hom = cv2.triangulatePoints(p1, p2, ul.T, ur.T)
        xrect = (hom[:3] / hom[3]).T
        xcam = xrect @ r1
        xworld = xcam @ rwc.T + twc.ravel()
        error3 = np.linalg.norm(xworld - world, axis=1)
        left_error = np.linalg.norm(project(world, rv, tv, k1, d1) - lp, axis=1)
        right_error = np.linalg.norm(project(world, cv2.Rodrigues(hright[:3, :3])[0], hright[:3, 3], k2, d2) - rp, axis=1)
        joint_rcw = cv2.Rodrigues(rvj)[0]
        joint_left_error = np.linalg.norm(project(world, rvj, tvj, k1, d1) - lp, axis=1)
        joint_right_error = np.linalg.norm(project(world, cv2.Rodrigues(rs @ joint_rcw)[0], rs @ tvj + ts, k2, d2) - rp, axis=1)
        single_l = np.linalg.norm(project(world, rv, tv, k1, d1) - lp, axis=1)
        single_r = np.linalg.norm(project(world, rvr, tvr, k2, d2) - rp, axis=1)
        left_h = rt_matrix(cv2.Rodrigues(rv)[0], tv)
        right_implied = rt_matrix(rs.T @ cv2.Rodrigues(rvr)[0], rs.T @ (tvr - ts))
        discrep_rot = cv2.Rodrigues(left_h[:3, :3].T @ right_implied[:3, :3])[0]
        metrics = dict(left_single_view_reprojection_px=stats(single_l), right_single_view_reprojection_px=stats(single_r),
                       delivered_left_reprojection_px=stats(left_error), delivered_right_reprojection_px=stats(right_error),
                       diagnostic_joint_left_reprojection_px=stats(joint_left_error), diagnostic_joint_right_reprojection_px=stats(joint_right_error),
                       rectified_vertical_error_px=stats(ul[:, 1] - ur[:, 1]),
                       stereo_control_point_error_m=stats(error3), stereo_table_plane_z_error_m=stats(xworld[:, 2]),
                       independent_eye_pose_translation_difference_m=float(np.linalg.norm(left_h[:3, 3] - right_implied[:3, 3])),
                       independent_eye_pose_rotation_difference_deg=float(np.degrees(np.linalg.norm(discrep_rot))),
                       matrix_inverse_max_error=float(np.max(np.abs(hcw @ hwc - np.eye(4)))),
                       rotation_orthogonality_max_error=float(np.max(np.abs(rcw.T @ rcw - np.eye(3)))),
                       rotation_determinant=float(np.linalg.det(rcw)), all_triangulated_points_in_front=bool(np.all(xcam[:, 2] > 0)),
                       camera_height_above_assumed_board_plane_m=float(twc[2, 0]), optimizer_success=bool(opt.success))
        assert np.isfinite(xworld).all() and twc[2, 0] > 0 and metrics['all_triangulated_points_in_front']
        assert metrics['matrix_inverse_max_error'] < 1e-10 and metrics['rotation_orthogonality_max_error'] < 1e-10
        # Numerical closure: rectified->world equals left-camera->world.
        assert np.max(np.abs(xrect @ hrw[:3, :3].T + hrw[:3, 3] - xworld)) < 1e-10
        data = dict(schema='b-table-world-per-capture-v1', capture=path.name, unit='m', placement_confirmed=args.placement_confirmed,
                    status='per_capture_only' if args.placement_confirmed else 'conditional_on_declared_board_placement',
                    source_sha256=digest(path), detector_left=methodl, detector_right=methodr,
                    world_origin='table surface at net x longitudinal centerline',
                    axes={'X': 'transverse, chosen so X cross Y = Z', 'Y': 'from net toward board half', 'Z': 'up; board printed surface approximated as table surface'},
                    geometry={'square_m': 0.03, 'squares_long_short': [12, 9], 'inner_long_short': [11, 8],
                              'black_white_grid_near_edge_Y_m': 0.55, 'inner_corner_near_row_Y_m': 0.58,
                              'grid_width_X_m': [-0.135, 0.135], 'grid_length_Y_m': [0.55, 0.91], 'assumed_printed_plane_Z_m': 0.0},
                    T_world_to_left_camera=hcw.tolist(), T_left_camera_to_world=hwc.tolist(),
                    T_world_to_right_camera=hright.tolist(), T_right_camera_to_world=np.linalg.inv(hright).tolist(),
                    T_rectified_left_to_world=hrw.tolist(), Rcw=rcw.tolist(), tcw_m=tv.ravel().tolist(),
                    R_camera_to_table=rwc.tolist(), translation_camera_to_table_m=twc.ravel().tolist(),
                    rvec_world_to_left=rv.ravel().tolist(), camera_center_world_m=twc.ravel().tolist(), metrics=metrics,
                    diagnostic_joint_world_to_left=rt_matrix(joint_rcw, tvj).tolist(),
                    single_eye_diagnostics={'T_world_to_left_from_left_only': left_h.tolist(), 'T_world_to_left_from_right_only': right_implied.tolist()},
                    application='Use only with matching unchanged camera mount; never select by filename proximity to a video.')
        dump(out / 'poses' / f'table_world_{label}.json', data)
        yml = out / 'poses' / f'table_world_{label}.yml'
        fs = cv2.FileStorage(str(yml), cv2.FILE_STORAGE_WRITE)
        fs.write('schema', data['schema']); fs.write('capture', path.name); fs.write('unit', 'm')
        fs.write('placement_confirmed', int(args.placement_confirmed)); fs.write('requires_matching_camera_pose', 1)
        fs.write('Rcw', rcw); fs.write('tcw', tv); fs.write('R_camera_to_table', rwc); fs.write('translation_camera_to_table', twc)
        fs.write('T_world_to_left_camera', hcw); fs.write('T_left_camera_to_world', hwc)
        fs.write('T_rectified_left_to_world', hrw); fs.write('T_world_to_right_camera', hright)
        fs.write('T_right_camera_to_world', np.linalg.inv(hright))
        fs.write('board_edge_to_net_m', 0.55); fs.write('square_size_m', 0.03)
        fs.release()
        # Default safety state is unselected: do not silently promote any moved
        # camera pose into the production trajectory pipeline.
        dump(out / 'poses' / f'pipeline_calibration_{label}.json', calibration_config(c, rv, tv, False, label))
        dump(out / 'evidence' / f'corners_{label}.json', dict(left_px=lp.tolist(), right_px=rp.tolist(), world_m=world.tolist(), triangulated_world_m=xworld.tolist()))
        # Plane homography is for Z=0 only and UNDISTORTED original-K pixels.
        homography = k1 @ np.column_stack([rcw[:, :2], tv])
        dump(out / 'poses' / f'table_plane_homography_{label}.json',
             dict(input='left pixels undistorted with P=K_left; table plane Z=0 only',
                  H_world_XY_to_undistorted_pixel=homography.tolist(), H_undistorted_pixel_to_world_XY=np.linalg.inv(homography).tolist()))
        for e, (eye, pts, k, d, rr, tt) in enumerate(((eyes[0], lp, k1, d1, rcw, tv), (eyes[1], rp, k2, d2, hright[:3, :3], hright[:3, 3]))):
            for pt in pts:
                cv2.circle(eye, tuple(np.round(pt).astype(int)), 2, (0, 220, 0), -1)
            # Use visible board-center axes; full world origin may lie outside image.
            base = np.array([0., 0.73, 0.])
            axis = np.array([base, base + [0.12, 0, 0], base + [0, 0.12, 0], base + [0, 0, 0.12]])
            pixels = project(axis, cv2.Rodrigues(rr)[0], tt, k, d)
            origin = tuple(np.round(pixels[0]).astype(int))
            for point, color, title in zip(pixels[1:], [(0, 0, 255), (0, 220, 0), (255, 150, 0)], ['+X', '+Y away net', '+Z up']):
                end = tuple(np.round(point).astype(int)); cv2.arrowedLine(eye, origin, end, color, 3, tipLength=.15)
                cv2.putText(eye, title, end, cv2.FONT_HERSHEY_SIMPLEX, .6, color, 2)
            near_pts = project(np.array([[-.135, .55, 0], [.135, .55, 0]], float), cv2.Rodrigues(rr)[0], tt, k, d)
            cv2.line(eye, tuple(np.round(near_pts[0]).astype(int)), tuple(np.round(near_pts[1]).astype(int)), (255, 0, 255), 3)
            cv2.putText(eye, f'{label} {"L" if e == 0 else "R"}  purple: grid edge Y=0.55m', (15, 30), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 255), 2)
        cv2.imwrite(str(out / 'previews' / f'axes_{label}.jpg'), np.hstack(eyes))
        results.append(dict(capture=path.name, camera_center_world_m=twc.ravel().tolist(), metrics=metrics))
        inputs.append(dict(file=path.name, sha256=digest(path)))
        print(label, json.dumps(metrics, ensure_ascii=False), flush=True)

    metadata = dict(schema='b-table-world-mapping-index-v1', created_local_date='2026-10-15', unit='m',
                    selected_capture=None, active_world_mapping=False, placement_confirmed=args.placement_confirmed,
                    reason='PartV contains different camera poses. Select matching capture only after mount/placement confirmation. Video pose is not established.',
                    controls='88 points per capture; 5 captures; solvePnP world -> left camera, invert to world; fixed supplied intrinsics/stereo; joint optimization retained only as diagnostic',
                    caveats=['No average across camera poses.', 'Board thickness unknown; Z=0 is the printed board plane approximation.',
                             'Reprojection is fit residual, not independent world accuracy.', 'Existing 6 validation images validate stereo calibration, not table origin.',
                             '0.55m measured edge and centerline alignment are declared inputs, not independently verified.',
                             'Intrinsics/stereo matrices reused from 2026-10-14; no intrinsic refit.',
                             'Video camera is not a confirmed match and shows possible camera motion. No video-world mapping exported.'],
                    captures=results)
    dump(out / 'table_world_extrinsics.json', metadata)
    fs = cv2.FileStorage(str(out / 'table_world_extrinsics.yml'), cv2.FILE_STORAGE_WRITE)
    fs.write('schema', metadata['schema']); fs.write('active_world_mapping', 0); fs.write('unit', 'm')
    fs.write('placement_confirmed', int(args.placement_confirmed)); fs.write('reason', metadata['reason'])
    fs.release()
    dump(out / 'evidence/input_manifest.json', dict(calibration_sha256=digest(args.calibration), PartV=inputs))
    dump(out / 'evidence/tool_versions.json', dict(python=platform.python_version(), opencv=cv2.__version__, numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform()))
    shutil.copy2(args.calibration, out / 'camera_calibration_results_20261014.json')
    for fname in ('calibration_arrays.npz', 'corners.npz', 'failed.json', 'used.txt'):
        shutil.copy2(args.calibration.parent / fname, out / fname)
    source = out / 'source' / Path(__file__).name
    if source.resolve() != Path(__file__).resolve():
        shutil.copy2(__file__, source)
    (out / 'source/requirements.txt').write_text(f'numpy=={np.__version__}\nopencv-python=={cv2.__version__}.84\nscipy=={scipy.__version__}\n', encoding='utf-8')
    print('Wrote', out, flush=True)


if __name__ == '__main__':
    main()
