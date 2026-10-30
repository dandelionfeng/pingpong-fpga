"""Recover a missing contact segment from measured stereo image motion.

The NPU supplies an identity seed. Bidirectional LK image matching supplies
observations; no extrapolated point enters the motion fit. Existing stereo,
near-hand and observation-gap tolerances are retained.
"""
from pathlib import Path
import json,time,math
import cv2
import numpy as np
from release_motion import read,triangulate,profile,robust_fit


def _distance(pixel,box):
    x,y,w,h=box
    return math.hypot(max(x-pixel[0],0,pixel[0]-x-w),max(y-pixel[1],0,pixel[1]-y-h))


def _bic(points,candidate):
    t=np.array([p['timestamp_ns']-candidate['timestamp_ns'] for p in points])*1e-9
    xyz=np.array([p['world_m'] for p in points])
    target=xyz-np.c_[0*t,0*t,-4.903325*t*t]
    null=np.c_[np.ones(len(t)),t]
    contact=np.c_[null,np.minimum(t,0)**2,np.minimum(t,0)**3]
    _,null_loss=robust_fit(null,target);_,contact_loss=robust_fit(contact,target)
    # Six extra contact coefficients plus the selected changepoint are penalized.
    return float(3*len(t)*math.log(max(null_loss,1e-12)/max(contact_loss,1e-12))-7*math.log(3*len(t)))


def recover(receipt,event,calibration,output,seed_evidence):
    began=time.perf_counter();out=Path(output);out.mkdir(parents=True,exist_ok=True)
    app=read(receipt);manifest=Path(app['input_manifest']);frames=read(manifest)['frames']
    source_index={r['pair_id']:i for i,r in enumerate(frames)}
    rows={r['pair_id']:r for r in [json.loads(x) for x in (Path(app['result'])/'frames.jsonl').read_text('utf-8').splitlines()]}
    detections={(d['pair_id'],d['eye']):d for d in [json.loads(x) for x in (Path(app['result'])/'detections.jsonl').read_text('utf-8').splitlines()]}
    cal=read(calibration);seed_id=seed_evidence['seed_pair_ids'][0]
    sample=next(s for s in seed_evidence['samples'] if s['pair_id']==seed_id)
    seed=np.array([e['ball_center_px'] for e in sample['eyes']],np.float32)
    si=source_index[seed_id];end=source_index[max(event['used_pair_ids'])];begin=max(0,si-36)
    digest=event.get('measurement_calibration_sha256');images={};routes=[];accepted=[]
    def image(j):
        if j not in images:
            images[j]=cv2.imread(str(manifest.parent/frames[j]['file']),0)
            if images[j] is None or images[j].shape!=(720,2560):raise ValueError('Missing original stereo image')
        return images[j]
    def hand_state(point):
        known=False;near=False
        for eye,label in enumerate(('left','right')):
            boxes=[b['bbox'] for b in detections.get((point['pair_id'],label),{}).get('boxes',[]) if b['class']=='hand']
            if boxes:
                known=True;near|=min(_distance(point['pixels'][eye],b) for b in boxes)<=18
        return known,near
    for window in (11,15,21,31,41):
        track={si:seed.copy()};audits=[]
        lk=dict(winSize=(window,window),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
        for indices in (range(si-1,begin-1,-1),range(si+1,end+1)):
            lastj=si;last=seed.copy()
            for j in indices:
                pid=frames[j]['pair_id'];m=rows.get(pid,{}).get('measurement',{})
                if digest and m.get('measurement_calibration_sha256') not in (None,digest):
                    audits.append({'pair_id':pid,'rejected':'calibration_boundary'});break
                if abs(frames[j]['timestamp_ns']-frames[lastj]['timestamp_ns'])>80000000:
                    audits.append({'pair_id':pid,'rejected':'observation_time_gap'});break
                pixels=[];cycle=[]
                for e in (0,1):
                    previous=image(lastj)[:,e*1280:(e+1)*1280];current=image(j)[:,e*1280:(e+1)*1280]
                    next_pixel,ok,_=cv2.calcOpticalFlowPyrLK(previous,current,last[e].reshape(1,1,2),None,**lk)
                    if next_pixel is None or not ok[0,0]:break
                    back,ok2,_=cv2.calcOpticalFlowPyrLK(current,previous,next_pixel,None,**lk)
                    if back is None or not ok2[0,0]:break
                    error=float(np.linalg.norm(back.reshape(2)-last[e]));cycle.append(error)
                    if error>4:break
                    pixels.append(next_pixel.reshape(2))
                if len(pixels)!=2:
                    audits.append({'pair_id':pid,'rejected':'forward_backward_image_match','cycle_error_px':cycle});break
                world,depth,epi=triangulate(pixels,cal)
                if not np.isfinite(world).all() or not .1<depth<15 or epi>4:
                    audits.append({'pair_id':pid,'rejected':'stereo_audit','rectified_y_difference_px':float(epi)});break
                lastj=j;last=np.array(pixels,np.float32);track[j]=last.copy()
                audits.append({'pair_id':pid,'cycle_error_px':cycle,'rectified_y_difference_px':float(epi)})
        points=[]
        for j,pixels in sorted(track.items()):
            world,depth,epi=triangulate(pixels,cal)
            if not np.isfinite(world).all() or not .1<depth<15 or epi>4:continue
            points.append({'pair_id':frames[j]['pair_id'],'frame0':j,'timestamp_ns':frames[j]['timestamp_ns'],
                'world_m':world.tolist(),'pixels':pixels.tolist(),'rectified_y_difference_px':float(epi),
                'source':'original_image_bidirectional_LK_from_measured_ball_seed',
                'measurement_calibration_sha256':digest,'predicted':False,'independent_accuracy_validated':False})
        pre=[p for p in points if p['timestamp_ns']<=event['fit_origin_ns']+event['apex_s']*1e9]
        route={'window_px':window,'points':points,'pre_apex_observations':len(pre),'audits':audits,'accepted':False}
        try:
            candidates=profile(pre)
            for candidate in candidates:
                if candidate['weighted_rms_m']>.03:continue
                if candidate['timestamp_ns']>(event.get('release') or {}).get('end_ns',candidate['timestamp_ns']):continue
                index=next(i for i,p in enumerate(pre) if p['pair_id']==candidate['pair_id'])
                # Hand boxes verify contact context; they do not supply a 3D point
                # or impose a hand ROI on the preceding free-flight search.
                touching=[p for p in pre[:index+1] if hand_state(p)[1]]
                separated=[p for p in pre[index+1:] if hand_state(p)==(True,False)]
                if not touching or not separated:continue
                gain=_bic(pre,candidate)
                if gain<=0:continue
                route.update(accepted=True,candidate=candidate,ballistic_vs_contact_bic_gain=gain,
                    last_near_hand_pair=touching[-1]['pair_id'],first_separated_pair=separated[0]['pair_id'])
                accepted.append((gain,route,pre));break
            if not route['accepted']:route['reason']='no_contact_transition_with_stereo_and_hand_context'
        except (ValueError,IndexError) as error:route['reason']=str(error)
        (out/f'flow-window-{window}.json').write_text(json.dumps(route,indent=2),encoding='utf-8')
        routes.append({k:v for k,v in route.items() if k not in ('points','audits')})
    result={'method':'stereo_image_flow_motion_transition','status':'insufficient_evidence','routes':routes,
            'predictions_used_for_fit':False,'scope':'saved original stereo images; no extra NPU calls'}
    if accepted:
        _,route,points=max(accepted,key=lambda x:x[0]);candidate=route['candidate'];loo=[]
        for i in range(len(points)):
            if points[i]['pair_id']==candidate['pair_id']:continue
            try:loo.append(profile(points,drop=i)[0]['pair_id'])
            except (ValueError,IndexError):pass
        # Preserve the existing two-frame continuity tolerance for an uncertain
        # changepoint rather than publishing an unstable best-fit grid point.
        if loo and max(abs(pid-candidate['pair_id']) for pid in loo)<=2:
            index=next(i for i,p in enumerate(points) if p['pair_id']==candidate['pair_id'])
            boundary_limited=index==4
            result.update(status='candidate_only' if boundary_limited else 'estimated',candidate=candidate,window_px=route['window_px'],
                observations=len(points),ballistic_vs_contact_bic_gain=route['ballistic_vs_contact_bic_gain'],
                leave_one_out_pairs=loo,last_near_hand_pair=route['last_near_hand_pair'],
                first_separated_pair=route['first_separated_pair'],search_boundary_limited=boundary_limited)
            if boundary_limited:result['reason']='changepoint_at_earliest_search_boundary_contact_history_truncated'
            (out/'selected-motion-points.json').write_text(json.dumps(points,indent=2),encoding='utf-8')
        else:result['reason']='unstable_motion_transition_under_observation_removal'
    else:result['reason']='no_reliable_stereo_contact_segment'
    result['recovery_wall_ms']=(time.perf_counter()-began)*1000
    (out/'recovery.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
