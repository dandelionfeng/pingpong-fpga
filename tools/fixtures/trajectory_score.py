"""Scores C++ outputs against isolated truth. Does not modify measurements."""
from pathlib import Path
import argparse
import json
import numpy as np


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--truth',required=True);ap.add_argument('--results',required=True);ap.add_argument('--report',required=True);args=ap.parse_args()
    truth=read(Path(args.truth));folder=Path(args.results);rows=[];exact_errors=[];clear_heights=[]
    for item in truth['cases']:
        r=read(folder/(item['name']+'.json'));event=r['event'];problems=[];geometry=[]
        if event['status']!=item['status']:problems.append(f"event status {event['status']} != {item['status']}")
        if len(r['frames'])!=len(item['frames']):problems.append('frame count')
        for expected,frame in zip(item['frames'],r['frames']):
            if frame['pair_id']!=expected['pair_id'] or frame['sample_time_ns']!=expected['sample_time_ns']:problems.append('frame identity')
            if not expected['geometry_expected']:
                if frame['geometry_valid'] or 'observed_world_m' in frame:problems.append('invalid frame exported observation')
            if frame['geometry_valid']:
                if 'observed_world_m' not in frame:problems.append('valid geometry missing observation')
                else:
                    error=float(np.linalg.norm(np.array(frame['observed_world_m'])-expected['world_m']));geometry.append(error)
                    if item['noise']==0 and not item['image'] and not(item['kind']=='outlier' and frame['pair_id']=='115'):
                        exact_errors.append(error)
                        if error>1e-5:problems.append('noiseless world error >1e-5m')
            if frame['track_reason']=='prediction_only' and 'filtered_world_m' in frame:problems.append('missing point exported filter as measurement')
        if item['status']=='complete':
            for key in ['release','apex','contact']:
                if key not in event:problems.append('missing '+key);continue
                target=int(item[key+'_ns']);begin,end=int(event[key]['begin_ns']),int(event[key]['end_ns'])
                if not begin<=target<=end:problems.append(key+' interval excludes truth')
                if item['name'].startswith('clean') and end-begin>16666668:problems.append('clean event interval >1 frame')
            if not event['fit']['valid']:problems.append('fit missing')
        if item['status']=='cancelled' and 'contact' in event:problems.append('cancelled contact')
        if item['kind'] in ['no_racket','no_contact','missing_release','expired_boxes','no_hand'] and 'contact' in event:problems.append('contact without evidence')
        height_error=None
        if event['fit']['valid']:
            height_error=abs(event['fit']['height_m']-item['height_m'])
            if item['name'].startswith('clean'):
                clear_heights.append(height_error)
                if height_error>.001:problems.append('clean height error >1mm')
            used=set(event['fit']['used_pair_ids'])
            for frame in r['frames']:
                if frame['pair_id'] in used and (not frame['geometry_valid'] or not frame['track_accepted']):problems.append('unaccepted point used by fit')
        if item['image']:
            for frame in r['frames'][18:23]:
                if not frame['geometry_valid'] or not frame.get('prediction_roi_requested'):problems.append('zero Mask prediction remeasurement failed')
        if item['kind']=='time_jump' and not any(f['track_reset'] for f in r['frames']):problems.append('time gap not reset')
        if item['kind']=='outlier' and r['frames'][15]['track_accepted']:problems.append('outlier not gated')
        if item['kind']=='expired_boxes' and event['associated_detections']:problems.append('expired boxes associated')
        rows.append(dict(name=item['name'],passed=not problems,status=event['status'],reason=event['reason'],geometry_count=len(geometry),geometry_p95_m=float(np.percentile(geometry,95)) if geometry else None,height_error_m=height_error,errors=problems))
    score=dict(total=len(rows),passed=sum(r['passed'] for r in rows),failed=sum(not r['passed'] for r in rows),noiseless_geometry_count=len(exact_errors),noiseless_geometry_max_error_m=max(exact_errors,default=None),clean_height_max_error_m=max(clear_heights,default=None),scope='fixed project-generated synthetic regression; pixel replay and image modes separated; not C independent review',cases=rows)
    Path(args.report).write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in score.items() if k!='cases'}))
    for row in rows:
        if not row['passed']:print('FAIL',row['name'],row['errors'])
    raise SystemExit(bool(score['failed']))


if __name__=='__main__':main()
