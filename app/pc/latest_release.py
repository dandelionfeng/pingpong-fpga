"""Apply the current motion-transition release calculation to a completed case."""
from pathlib import Path
import argparse,json,math,sys,time
import numpy as np
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/'algorithms'))
from release_motion import read,track_pixels,profile
from case_io import calibration_for
from best_effort import complete_output

def main():
    import cv2
    cv2.setNumThreads(1)
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--no-replay',action='store_true');p.add_argument('--no-plot',action='store_true');p.add_argument('--recompute',action='store_true');p.add_argument('--replay-output',type=Path);a=p.parse_args()
    started=time.perf_counter();cpu_started=time.process_time()
    receipt=a.case/'app-run-receipt.json' if a.case.is_dir() else a.case
    app=read(receipt);event=app.get('final_event') or {}
    out=a.output or receipt.parent/'motion-current'
    if (out/'latest-release.json').exists() and not a.recompute:
        if not a.no_replay:
            from replay import build
            build(receipt,a.replay_output,read(out/'latest-release.json'))
        print('MEASUREMENT',out/'latest-release.json');return
    out.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(s) for s in (Path(app['result'])/'frames.jsonl').read_text('utf-8').splitlines()]
    attempt={'attempted':True,'legacy_fit_required_for_attempt':False,'status':'insufficient_evidence'}
    if not event.get('fit_valid'):
        from observed_flight import fit_visible_flight
        flight,refined=fit_visible_flight(app,receipt,rows,calibration_for,out)
        # Exercise motion fitting independently of the legacy hand event. Keep
        # actual observations from one calibration and one contiguous segment.
        groups=[]
        for i,row in enumerate(rows):
            m=row.get('measurement',{})
            if m.get('status')!='observed' or not m.get('semantic_ball_supported') or not m.get('world_xyz_m'):continue
            q={'pair_id':row['pair_id'],'frame0':i,'timestamp_ns':row['timestamp_ns'],'world_m':m['world_xyz_m'],
               'calibration':m.get('measurement_calibration_sha256')}
            if not groups or q['calibration']!=groups[-1][-1]['calibration'] or q['timestamp_ns']-groups[-1][-1]['timestamp_ns']>80000000:groups.append([])
            groups[-1].append(q)
        points=max(groups,key=len,default=[])
        if points:points=points[:max(range(len(points)),key=lambda i:points[i]['world_m'][2])+1]
        try:attempt.update(candidate=profile(points)[0],status='candidate_without_valid_flight')
        except (ValueError,IndexError) as error:attempt['reason']=str(error)
        attempt['observations']=len(points)
        result={'fit_valid':False,'motion_status':attempt['status'],'motion_attempt':attempt,
                'source_receipt':str(receipt.resolve()),'timing':{'measurement_wall_ms':(time.perf_counter()-started)*1000,
                'measurement_cpu_ms':(time.process_time()-cpu_started)*1000,'observations':len(points)}}
        if flight:
            result.update(fit_valid=True,release_valid=False,flight_event=flight,observations=refined,
                          method='original_pixel_stereo_free_flight_release_unresolved')
            if len(refined)>=2:
                from motion_recovery import recover
                evidence={'seed_pair_ids':[q['pair_id'] for q in refined[:2]],'samples':[
                    {'pair_id':q['pair_id'],'eyes':[{'ball_center_px':p} for p in q['pixels']]} for q in refined[:2]]}
                recovered=recover(receipt,flight,calibration_for(app,flight,receipt),out/'recovery',evidence)
                result['recovery_attempt']=recovered
                if recovered['status']=='estimated':
                    candidate=recovered['candidate'];dt=(candidate['timestamp_ns']-flight['fit_origin_ns'])*1e-9
                    x,y,z=(flight[k] for k in ('x_coefficients','y_coefficients','z_coefficients'))
                    release=[x[0]+x[1]*dt,y[0]+y[1]*dt,z[0]+z[1]*dt+z[2]*dt*dt];apex=flight['apex_world_m'];height=apex[2]-release[2]
                    if height>0:
                        result.update(release_valid=True,motion_status='estimated',candidate=candidate,
                            release_world_m=release,apex_world_m=apex,height_cm=height*100,
                            angle_deg=math.degrees(math.atan2(math.hypot(apex[0]-release[0],apex[1]-release[1]),height)),
                            method='stereo_image_flow_motion_transition_then_flight_curve')
                        attempt=dict(recovered,previous_attempt=attempt);result['motion_attempt']=attempt
                result['timing'].update(measurement_wall_ms=(time.perf_counter()-started)*1000,
                    measurement_cpu_ms=(time.process_time()-cpu_started)*1000,recovery_ms=recovered['recovery_wall_ms'])
        result=complete_output(result,app,rows)
        (out/'motion-attempt.json').write_text(json.dumps(attempt,indent=2),encoding='utf-8')
        (out/'latest-release.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        if not a.no_replay:
            from replay import build
            build(receipt,a.replay_output,result)
        print(json.dumps(result,indent=2));return
    evidence=event.get('release_pixel_evidence') or {}
    fallback_seed=not evidence.get('seed_pair_ids')
    if fallback_seed:
        actual=[r for r in rows if r['pair_id']<=event['used_pair_ids'][-1]
                and r['measurement'].get('status')=='observed'
                and r['measurement'].get('semantic_ball_supported')
                and r['measurement'].get('pixel_evidence_verified')
                and r['measurement'].get('measurement_calibration_sha256')==event.get('measurement_calibration_sha256')]
        seeds=next(([x,y] for x,y in zip(actual,actual[1:]) if y['pair_id']-x['pair_id']<=2),[])
        evidence={'seed_pair_ids':[r['pair_id'] for r in seeds],'samples':[
            {'pair_id':r['pair_id'],'eyes':[{'ball_center_px':r['measurement']['left_pixel']},
                                          {'ball_center_px':r['measurement']['right_pixel']}]} for r in seeds]}
    attempt['seed_source']='semantic_original_roi_centroids' if fallback_seed else 'mask_gray_pixels'
    points=track_pixels(receipt,calibration_for(app,event,receipt),out,seed_evidence=evidence) if len(evidence.get('seed_pair_ids',[]))==2 else []
    (out/'pixel-tracks.json').write_text(json.dumps(points,indent=2),encoding='utf-8')
    tracked=time.perf_counter()
    apex_ns=event['fit_origin_ns']+event['apex_s']*1e9
    apex_pair=min(rows,key=lambda r:abs(r['timestamp_ns']-apex_ns))['pair_id']
    points=[q for q in points if q['pair_id']<=apex_pair]
    breaks=[b['pair_id'] for a,b in zip(points,points[1:]) if b['pair_id']-a['pair_id']>2]
    if breaks:points=[q for q in points if q['pair_id']>=breaks[-1]]
    fit_started=time.perf_counter()
    try:
        candidate=profile(points)[0];attempt['candidate']=candidate
        if fallback_seed and candidate['timestamp_ns']>event['release']['end_ns']:
            raise ValueError('Motion candidate is later than observed hand separation; contact segment missing')
        attempt['status']='estimated'
    except (ValueError,IndexError) as error:
        attempt['reason']=str(error)
        stamp=int(event['fit_origin_ns']+event.get('release_offset_s',0)*1e9)
        nearest=min(rows,key=lambda r:abs(r['timestamp_ns']-stamp))
        candidate={'pair_id':nearest['pair_id'],'timestamp_ns':stamp,'source':'source_aligned_hand_release_and_stereo_flight_fit'}
    if attempt['status']!='estimated' and len(evidence.get('seed_pair_ids',[]))==2:
        from motion_recovery import recover
        recovered=recover(receipt,event,calibration_for(app,event,receipt),out/'recovery',evidence)
        attempt['recovery_attempt']=recovered
        if recovered['status']=='estimated':
            candidate=recovered['candidate'];attempt=dict(recovered,previous_attempt=attempt)
    attempt.setdefault('observations',len(points))
    (out/'motion-attempt.json').write_text(json.dumps(attempt,indent=2),encoding='utf-8')
    dt=(candidate['timestamp_ns']-event['fit_origin_ns'])*1e-9
    x,y,z=(event[k] for k in ('x_coefficients','y_coefficients','z_coefficients'))
    release=[x[0]+x[1]*dt,y[0]+y[1]*dt,z[0]+z[1]*dt+z[2]*dt*dt];apex=event['apex_world_m'];h=apex[2]-release[2]
    angle=math.degrees(math.atan2(math.hypot(apex[0]-release[0],apex[1]-release[1]),h));assert h>0
    result={'candidate':candidate,'height_cm':h*100,'angle_deg':angle,'release_world_m':release,'apex_world_m':apex,'method':'motion_transition_then_flight_curve_extrapolation','source_receipt':str(receipt.resolve())}
    result.update(fit_valid=True,motion_status=attempt['status'],motion_attempt=attempt)
    if attempt.get('method')=='stereo_image_flow_motion_transition':result['method']='stereo_image_flow_motion_transition_then_flight_curve'
    if attempt['status']!='estimated':result['method']='source_aligned_stereo_flight_fit_motion_unresolved'
    result['timing']={'tracking_ms':(tracked-started)*1000,'kinematic_fit_ms':(time.perf_counter()-fit_started)*1000,
                     'measurement_wall_ms':(time.perf_counter()-started)*1000,'measurement_cpu_ms':(time.process_time()-cpu_started)*1000,
                     'observations':attempt['observations'],'scope':'one completed flight; pixel tracking and motion-transition fitting'}
    result=complete_output(result,app,rows)
    if 'recovery_wall_ms' in attempt:result['timing']['recovery_ms']=attempt['recovery_wall_ms']
    if not a.no_plot:
        from plot_trajectory import make_plot
        make_plot(1,{'candidate_release_world_m':release,'apex_world_m':apex,'metric':{'height_m':h,'angle_deg':angle},'candidate':candidate,'title':Path(app['source_video']).stem},event,rows,out)
    (out/'latest-release.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if not a.no_replay:
        from replay import build
        import os
        webpage=build(receipt,a.replay_output,result)
        relative=os.path.relpath(webpage,out).replace('\\','/')
        (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+relative+'"><a href="'+relative+'">打开轨迹回放</a>',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));print('MEASUREMENT',out/'latest-release.json')
if __name__=='__main__':main()
