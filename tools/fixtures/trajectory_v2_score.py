"""Truth-isolated scoring of C++ geometry and online replay. B regression only."""
import argparse
import json
from pathlib import Path
import numpy as np


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);args=ap.parse_args();root=Path(args.root)
    truth=read(root/'truth/expected_v2.json');manifest=read(root/'inputs/manifest_v2.json');inputs={c['name']:c for c in manifest['cases']};rows=[]
    for item in truth['cases']:
        name=item['name'];r=read(root/'results'/f'{name}.json');event=r['event'];problems=[];errors=[];height_error=None;case=inputs[name];actual={f['pair_id']:f for f in r['frames']}
        if event['status']!=item['status']:problems.append(f"status={event['status']} expected={item['status']}")
        if len(r['frames'])!=len(item['frames']):problems.append('frame count')
        for expected,f in zip(item['frames'],r['frames']):
            if (f['pair_id'],f['sample_time_ns'])!=(expected['pair_id'],expected['sample_time_ns']):problems.append('frame identity')
            if not expected['geometry_expected'] and (f['geometry_valid'] or 'observed_world_m' in f):problems.append('invalid frame exported observation')
            if f['geometry_valid']:
                error=float(np.linalg.norm(np.array(f['observed_world_m'])-expected['world_m']));errors.append(error)
                if not item['image'] and item['noise']==0 and not(item['kind']=='outlier' and f['pair_id']=='115') and error>1e-5:problems.append('ideal geometry >1e-5m')
            if f['track_reason']=='prediction_only' and 'filtered_world_m' in f:problems.append('prediction exported as measured filter')
        if item['status']=='complete':
            for key in ['release','apex','contact']:
                target=int(item[key+'_ns']);interval=event.get(key)
                if not interval or not int(interval['begin_ns'])<=target<=int(interval['end_ns']):problems.append(key+' excludes truth')
                elif name.startswith(('clean','varied')) and int(interval['end_ns'])-int(interval['begin_ns'])>16666668:problems.append('clean interval >1frame')
            if not event['fit']['valid']:problems.append('complete missing fit')
        if item['status']=='cancelled' and 'contact' in event:problems.append('cancelled contact')
        if item['kind'] in ['no_racket','no_contact','missing_release','severe_occlusion','no_apex','no_hand','invisible_hand','wrong_model','wrong_source','expired_boxes','arrival_expired'] and 'contact' in event:problems.append('unsupported contact')
        if event['fit']['valid']:
            height_error=abs(event['fit']['height_m']-item['height_m'])
            if name.startswith(('clean','varied')) and height_error>.001:problems.append('clean height >1mm')
            for pid in event['fit']['used_pair_ids']:
                f=actual[pid]
                if not f['geometry_valid'] or not f['track_accepted']:problems.append('fit uses unaccepted observation')
        # Check publication causality with source metadata and actual arrivals.
        for u in r['online_updates']:
            used=set(u.get('fit',{}).get('used_pair_ids',[]))
            if not used.issubset(set(u['source_pair_ids'])):problems.append('revision fit outside source window')
            for key,label in [('release','hand'),('contact','racket')]:
                if key not in u:continue
                interval=u[key];available=[]
                for d in case['detections']:
                    arrival=int(d.get('arrival_time_ns',d['completed_time_ns']));source=int(d['sample_time_ns'])
                    if d['label']==label and d['pair_id'] in u['source_pair_ids'] and d['visible'] and d['model_version'] and source<=arrival<=int(u['published_time_ns']) and arrival-source<=250000000:available.append(d)
                if not available:problems.append('online event precedes semantic availability')
        finals=[u for u in r['online_updates'] if u['finalized']]
        if item['status']=='complete' and not any(u['status']=='complete' for u in finals):problems.append('no finalized online complete event')
        if r['online_stats']['peak_frames']>256 or r['online_stats']['peak_detections']>2048:problems.append('unbounded queue')
        if item['image']:
            if len(errors)<50:problems.append('image observation coverage below 50/56')
            for f in r['frames'][18:23]:
                if not f['geometry_valid'] or not f.get('prediction_roi_requested'):problems.append('zeroMask image remeasurement')
            if item['status']=='complete' and not any(f['track_reason']=='contact_velocity_reset' for f in r['frames']):problems.append('image lacks contact velocity reset')
            if item['status']=='complete' and not all(f['geometry_valid'] for f in r['frames'][44:]):problems.append('postcontact image reacquisition incomplete')
        rows.append(dict(name=name,passed=not problems,status=event['status'],reason=event['reason'],mode=r['mode'],estimated_calibration=bool(item.get('estimated_calibration')),geometry_count=len(errors),geometry_p95_m=float(np.percentile(errors,95)) if errors else None,height_error_m=height_error,online_revisions=len(r['online_updates']),finalized_events=[dict(event_id=u['event_id'],status=u['status'],reason=u['reason'])for u in finals],errors=sorted(set(problems))))
    name='continuous_two_serves';r=read(root/'results'/f'{name}.json');finals=[u for u in r['online_updates']if u['finalized'] and u['status']=='complete'];problems=[]
    if len(finals)!=2 or len({u['event_id']for u in finals})!=2:problems.append('expected two distinct online serves')
    if len(finals)==2 and set(finals[0]['fit']['used_pair_ids'])&set(finals[1]['fit']['used_pair_ids']):problems.append('serve observations overlap')
    rows.append(dict(name=name,passed=not problems,status='online_two_serves',reason='two separated event windows',online_revisions=len(r['online_updates']),errors=problems))
    score=dict(total=len(rows),passed=sum(r['passed']for r in rows),failed=sum(not r['passed']for r in rows),scope='B generated synthetic regression, not C frozen/independent review, no real model or hardware evidence',cases=rows)
    (root/'score-v2.json').write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in score.items()if k!='cases'}))
    for r in rows:
        if not r['passed']:print('FAIL',r['name'],r['errors'])
    raise SystemExit(bool(score['failed']))


if __name__=='__main__':main()
