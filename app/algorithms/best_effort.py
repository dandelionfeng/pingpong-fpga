"""Keep measured trajectories and explicitly labelled estimates available."""
import math
import numpy as np


def _points(records):
    groups = {}
    for row in records:
        m = row.get('measurement', {})
        xyz = m.get('world_xyz_m')
        if m.get('status') != 'observed' or xyz is None:
            continue
        if len(xyz) != 3 or not np.isfinite(xyz).all():
            continue
        digest = m.get('measurement_calibration_sha256')
        groups.setdefault(digest, []).append({
            'pair_id': row['pair_id'], 'timestamp_ns': row['timestamp_ns'],
            'world_m': xyz, 'status': 'observed', 'calibration_sha256': digest,
            'semantic_ball_supported': bool(m.get('semantic_ball_supported')),
            'source': 'saved_stereo_observation',
        })
    return sorted(max(groups.values(), key=len, default=[]), key=lambda p: p['timestamp_ns'])


def complete_output(result, app, records, errors=None):
    """Never replace good values; loosen presentation without relabelling validity."""
    result = dict(result or {})
    if errors:
        result['optional_stage_errors'] = list(errors)
    if all(isinstance(result.get(k), (int, float)) and math.isfinite(result[k])
           for k in ('height_cm', 'angle_deg')):
        result.setdefault('measurement_estimated', result.get('motion_status') != 'estimated')
        if result['measurement_estimated']:
            result.setdefault('quality_note', '离手采用已有手框区间估算，运动转折未确认')
        result.update(trajectory_available=True, measurement_available=True)
        return result

    points = result.get('observations') or _points(records)
    points = [p for p in points if np.isfinite(p.get('world_m', [])).all()]
    result['observations'] = points
    event = result.get('flight_event') or app.get('final_event') or {}
    strict = bool(event.get('fit_valid'))
    if not all(k in event for k in ('x_coefficients', 'y_coefficients', 'z_coefficients', 'fit_origin_ns')):
        unique = {p['timestamp_ns']: p for p in points}
        points = [unique[t] for t in sorted(unique)]
        if len(points) < 2:
            result.update(fit_valid=False, release_valid=False,
                          trajectory_available=bool(points), measurement_available=False,
                          motion_status=result.get('motion_status', 'insufficient_evidence'),
                          output_status='point_only' if points else 'no_observations',
                          quality_note='仅有一个实测球点' if points else '没有可用的实测三维球点')
            return result
        origin = points[0]['timestamp_ns']
        t = np.array([(p['timestamp_ns'] - origin) * 1e-9 for p in points])
        xyz = np.array([p['world_m'] for p in points], dtype=float)
        a = np.c_[np.ones(len(t)), t]
        xy = np.linalg.lstsq(a, xyz[:, :2], rcond=None)[0]
        # Fixed gravity also fits a short visible arc. High residual is reported,
        # rather than used to remove its curve and estimates from the output.
        z01 = np.linalg.lstsq(a, xyz[:, 2] + 4.903325 * t * t, rcond=None)[0]
        z = np.r_[z01, -4.903325]
        if len(points) >= 3:
            free = np.linalg.lstsq(np.c_[a, t*t], xyz[:, 2], rcond=None)[0]
            if np.isfinite(free).all() and free[2] < -.05:
                z = free
        apex = -z[1] / (2 * z[2])
        curve = np.c_[a @ xy, np.c_[a, t*t] @ z]
        event = {
            'fit_valid': False, 'display_available': True,
            'fit_kind': 'best_effort_observed_arc', 'fit_origin_ns': origin,
            'x_coefficients': xy[:, 0].tolist(), 'y_coefficients': xy[:, 1].tolist(),
            'z_coefficients': z.tolist(), 'apex_s': float(apex),
            'apex_world_m': [float(xy[0, j]+xy[1, j]*apex) for j in (0, 1)]
                            + [float(z[0]+z[1]*apex+z[2]*apex*apex)],
            'used_pair_ids': [p['pair_id'] for p in points],
            'measurement_calibration_sha256': points[0].get('calibration_sha256'),
            'fit_residual_rms_m': float(np.sqrt(np.mean(np.sum((curve-xyz)**2, axis=1)))),
            'predictions_used_for_fit': False, 'actual_stereo_frames': len(points),
            'accuracy_validated': False,
        }
        result['observations'] = points

    x, y, z = (event[k] for k in ('x_coefficients', 'y_coefficients', 'z_coefficients'))
    origin = event['fit_origin_ns']
    apex = np.array(event['apex_world_m'], dtype=float)
    apex_ns = int(origin + event['apex_s'] * 1e9)
    rising = [p for p in points if p['timestamp_ns'] <= apex_ns]
    candidate = (result.get('motion_attempt') or {}).get('candidate')
    if candidate and points and not points[0]['timestamp_ns'] <= candidate['timestamp_ns'] < apex_ns:
        candidate = None
    if not candidate and strict and event.get('release'):
        candidate = {'timestamp_ns': int(origin+event.get('release_offset_s',0)*1e9),
                     'source': 'native_flight_release_reference'}
    if candidate and 'source' not in candidate:
        candidate = dict(candidate, source='unconfirmed_motion_candidate')
    candidate = candidate or (dict(rising[0], source='first_visible_ascending_point') if rising else None)
    kind = 'release_reference_estimate'
    if candidate:
        stamp = candidate['timestamp_ns']
        dt = (stamp-origin)*1e-9
        release = np.array([x[0]+x[1]*dt, y[0]+y[1]*dt, z[0]+z[1]*dt+z[2]*dt*dt])
        height = float(apex[2]-release[2])
    else:
        height = -1
    if height <= 0 or not math.isfinite(height):
        # A descending-only clip measures its visible spatial span, not an
        # invented release. Keep this distinct in both JSON and the webpage.
        if not points:
            result.update(trajectory_available=False, measurement_available=False, output_status='no_observations')
            return result
        low = min(points, key=lambda p: p['world_m'][2])
        high = max(points, key=lambda p: p['world_m'][2])
        release, apex = np.array(low['world_m']), np.array(high['world_m'])
        height = float(apex[2]-release[2]);stamp = low['timestamp_ns'];apex_ns = high['timestamp_ns']
        candidate = {'pair_id': low['pair_id'], 'timestamp_ns': stamp, 'source': 'visible_span_reference'}
        event = dict(event, apex_s=(apex_ns-origin)*1e-9, apex_world_m=apex.tolist())
        kind = 'visible_span'
    horizontal = float(np.linalg.norm(apex[:2]-release[:2]))
    angle = math.degrees(math.atan2(horizontal, height))
    result.update(fit_valid=strict, release_valid=False, trajectory_available=True,
                  measurement_available=True, measurement_estimated=True,
                  output_status='estimated', metric_kind=kind,
                  height_cm=height*100, angle_deg=angle,
                  candidate=candidate, release_world_m=release.tolist(), apex_world_m=apex.tolist(),
                  flight_event=event, method='best_effort_' + kind,
                  motion_status=result.get('motion_status', 'insufficient_evidence'),
                  quality_note=('仅测量可见段的高度变化与偏角，离手未确定' if kind == 'visible_span' else
                                '参考首个可见上升球点估算；画面外的离手可能更早，高度可能低估'
                                if candidate.get('source') == 'first_visible_ascending_point' else
                                '采用已有离手参考估算，运动转折未确认'))
    return result
