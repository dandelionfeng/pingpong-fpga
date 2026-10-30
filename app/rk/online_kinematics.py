"""Run the unchanged motion calculation on a causally bounded processed prefix."""
from pathlib import Path
import json,os,sys,time
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algorithms'))
import cv2
cv2.setNumThreads(1)
from release_motion import track_pixels,profile
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def rows(p):return [json.loads(s) for s in Path(p).read_text('utf-8-sig').splitlines() if s.strip()]
def dump(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
context=read(sys.argv[1]);target=Path(sys.argv[2]);started=time.perf_counter()
os.sched_setaffinity(0,{7})
current=context['current_pair_id'];out=Path(context['output']);out.mkdir(exist_ok=False)
try:
    source_manifest=Path(context['input_manifest']);manifest=read(source_manifest)
    source_frames=manifest['frames'];allowed=[r for r in source_frames if r['pair_id']<=current]
    assert allowed[-1]['pair_id']==current
    raw=rows(context['raw_frames']);assert all(r['meta']['pair_id']<current for r in raw)
    raw.append(context['current_frame'])
    assert [r['meta']['pair_id'] for r in raw]==[r['pair_id'] for r in allowed]
    ds=rows(context['raw_detections']);assert len(ds)==2*len(allowed)
    assert all(d['meta']['pair_id']<=current for d in ds)
    normalized=[{'pair_id':r['meta']['pair_id'],'timestamp_ns':r['meta']['timestamp_ns'],'measurement':r['measurement']} for r in raw]
    (out/'frames.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in normalized),encoding='utf-8')
    (out/'detections.jsonl').write_text(''.join(json.dumps({'pair_id':r['meta']['pair_id'],'eye':'right' if r['eye'] else 'left','boxes':r['boxes']})+'\n' for r in ds),encoding='utf-8')
    prefix_manifest=dict(manifest)
    prefix_manifest['frames']=[dict(r,file=str((source_manifest.parent/r['file']).resolve())) for r in allowed]
    dump(out/'input-manifest.json',prefix_manifest)
    event=context['current_frame']['measurement']['events']
    assert event['fit_valid'] and event['release_pixel_evidence']['accepted']
    assert max(event['used_pair_ids'])<=current
    receipt={'result':str(out),'input_manifest':str(out/'input-manifest.json'),'final_event':event}
    dump(out/'app-run-receipt.json',receipt)
    evidence=event['release_pixel_evidence']
    assert max(evidence['seed_pair_ids'])<=current
    tracking_start=time.perf_counter()
    points=track_pixels(out/'app-run-receipt.json',context['calibration'],out,seed_evidence=evidence,end_pair_id=current)
    dump(out/'pixel-tracks-prefix.json',points)
    apex_ns=event['fit_origin_ns']+event['apex_s']*1e9
    apex_pair=min(normalized,key=lambda r:abs(r['timestamp_ns']-apex_ns))['pair_id']
    points=[q for q in points if q['pair_id']<=apex_pair]
    breaks=[b['pair_id'] for a,b in zip(points,points[1:]) if b['pair_id']-a['pair_id']>2]
    if breaks:points=[q for q in points if q['pair_id']>=breaks[-1]]
    tracked=time.perf_counter()
    candidates=profile(points);candidate=candidates[0]
    assert candidate['pair_id']<=current and max(q['pair_id'] for q in points)<=current
    dump(out/'kinematic-input-points.json',points)
    dump(out/'kinematic-candidates.json',candidates)
    result={'status':'candidate','observed_at_pair_id':current,'candidate':candidate,
            'max_source_pair_id':max(r['pair_id'] for r in prefix_manifest['frames']),
            'source_pairs':len(allowed),'source_eye_tasks':len(ds),'seed_pair_ids':evidence['seed_pair_ids'],
            'point_pair_ids':[q['pair_id'] for q in points],'observations':len(points),'apex_pair_id':apex_pair,
            'future_frames_available_to_tracker':False,'model_inference_in_helper':False,
            'tracking_ms':(tracked-tracking_start)*1000,'fit_ms':(time.perf_counter()-tracked)*1000,
            'method':'unchanged release_motion.track_pixels and profile; prefix only'}
except Exception as error:
    result={'status':'no_candidate','observed_at_pair_id':current,'reason':str(error),'future_frames_available_to_tracker':False}
result['helper_wall_ms']=(time.perf_counter()-started)*1000
dump(target,result)
print('ONLINE_KINEMATIC_RESULT',json.dumps(result),flush=True)
