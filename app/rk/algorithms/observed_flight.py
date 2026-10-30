"""Fit a visible free-flight segment without requiring a hand-release event.

The release remains unresolved. Every fitted point is measured in both original
images near a V6 proposal; predictions and detector box midpoints are excluded.
"""
from pathlib import Path
import json
import cv2
import numpy as np
from release_motion import blob, triangulate, robust_fit, read


def fit_visible_flight(app, receipt, records, calibration_for, output):
    manifest_path=Path(app['input_manifest']);manifest=read(manifest_path)
    inputs={r['pair_id']:r for r in manifest['frames']}
    detections={}
    for line in (Path(app['result'])/'detections.jsonl').read_text('utf-8').splitlines():
        d=json.loads(line);detections[d['pair_id'],d['eye']]=d['boxes']
    groups=[];all_points=[];rejected=[];calibrations={}
    for row in records:
        m=row.get('measurement',{});pid=row['pair_id']
        if m.get('status')!='observed' or not m.get('semantic_ball_supported') or pid not in inputs:continue
        digest=m.get('measurement_calibration_sha256')
        if digest not in calibrations:
            calibrations[digest]=read(calibration_for(app,{'measurement_calibration_sha256':digest},receipt))
        image=cv2.imread(str(manifest_path.parent/inputs[pid]['file']),0)
        if image is None:raise ValueError('Cannot read original stereo image '+str(pid))
        pixels=[]
        for eye,label in enumerate(('left','right')):
            seed=m.get(label+'_pixel')
            found=blob(image[:,eye*1280:(eye+1)*1280],seed) if seed else None
            boxes=[b['bbox'] for b in detections.get((pid,label),[]) if b['class']=='ball']
            if found is None or not any(b[0]<=found[1][0]<=b[0]+b[2] and b[1]<=found[1][1]<=b[1]+b[3] for b in boxes):break
            pixels.append(found[1])
        if len(pixels)!=2:
            rejected.append({'pair_id':pid,'reason':'original_pixel_centroid_missing_in_V6_box'});continue
        xyz,depth,epipolar=triangulate(pixels,calibrations[digest])
        # Reuse the original pixel tracker's 4px stereo audit and depth bounds.
        if not np.isfinite(xyz).all() or not .1<depth<15 or epipolar>4:
            rejected.append({'pair_id':pid,'reason':'stereo_pixel_audit','epipolar_px':float(epipolar)});continue
        point={'pair_id':pid,'timestamp_ns':row['timestamp_ns'],'world_m':xyz.tolist(),
               'pixels':[p.tolist() for p in pixels],'rectified_y_difference_px':float(epipolar),
               'calibration_sha256':digest,'status':'observed','source':'V6_ROI_original_bright_blob_centroid',
               'independent_accuracy_validated':False}
        all_points.append(point)
        # Same observation-gap policy as EventConfig; never bridge a lost ball.
        if not groups or digest!=groups[-1][-1]['calibration_sha256'] or point['timestamp_ns']-groups[-1][-1]['timestamp_ns']>80000000:groups.append([])
        groups[-1].append(point)
    Path(output,'stereo-pixel-audit.json').write_text(json.dumps({'observed':all_points,'rejected':rejected},indent=2),encoding='utf-8')
    candidates=[]
    for points in groups:
        if len(points)<6:continue
        origin=points[0]['timestamp_ns'];t=np.array([p['timestamp_ns']-origin for p in points])*1e-9
        if t[-1]<.08:continue
        xyz=np.array([p['world_m'] for p in points])
        xy,_=robust_fit(np.c_[np.ones(len(t)),t],xyz[:,:2])
        z,_=robust_fit(np.c_[np.ones(len(t)),t,t*t],xyz[:,2:3]);z=z[:,0]
        if z[2]>=-.1:continue
        apex=-z[1]/(2*z[2])
        if not 0<apex<t[-1]:continue
        curve=np.c_[np.c_[np.ones(len(t)),t]@xy,np.c_[np.ones(len(t)),t,t*t]@z]
        residual=float(np.sqrt(np.mean(np.sum((curve-xyz)**2,axis=1))))
        # Existing strict fit_flight residual bound, even in diagnostic mode.
        if residual>.03:continue
        apex_world=[float(xy[0,j]+xy[1,j]*apex) for j in (0,1)]+[float(z[0]+z[1]*apex+z[2]*apex*apex)]
        event={'fit_valid':True,'release_valid':False,'fit_kind':'observed_free_flight_release_unresolved',
               'fit_origin_ns':origin,'apex_s':float(apex),'apex_world_m':apex_world,
               'x_coefficients':xy[:,0].tolist(),'y_coefficients':xy[:,1].tolist(),'z_coefficients':z.tolist(),
               'used_pair_ids':[p['pair_id'] for p in points],'measurement_calibration_sha256':points[0]['calibration_sha256'],
               'fit_residual_rms_m':residual,'actual_stereo_frames':len(points),
               'predictions_used_for_fit':False,'accuracy_validated':False,
               'reason':'visible_flight_fitted_without_held_ball_or_release_evidence'}
        candidates.append((len(points),-residual,event,points))
    if not candidates:return None,[]
    _,_,event,points=max(candidates,key=lambda c:c[:2])
    return event,points
