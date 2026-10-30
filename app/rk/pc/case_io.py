from pathlib import Path
import hashlib,json

BASE=Path(__file__).resolve().parents[1]
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def rows(path):
    path=Path(path)
    return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()] if path.exists() else []
def receipt_path(case):
    case=Path(case)
    return case/'app-run-receipt.json' if case.is_dir() else case
def calibration_for(app,event,receipt):
    wanted=event.get('measurement_calibration_sha256')
    result=Path(app['result'])
    choices=[Path(app.get('calibration',BASE/'config/calibration.json')),
             Path(receipt).parent/'calibration.json',BASE/'config/calibration.json']
    if wanted:
        choices=[result/f'teso-calibration-{wanted}.json',Path(receipt).parent/f'teso-calibration-{wanted}.json']+choices
    for p in choices:
        if p.is_file() and (not wanted or hashlib.sha256(p.read_bytes()).hexdigest()==wanted):return p
    raise ValueError('Cannot locate the calibration used by this flight: '+str(wanted))
def normalize_board(case,input_manifest=None):
    case=Path(case).resolve();receipt=case/'app-run-receipt.json'
    if receipt.exists():return receipt
    capture=read(case/'capture-complete.json') if (case/'capture-complete.json').exists() else read(case/'summary.json')
    manifest_path=Path(input_manifest) if input_manifest else case/'input/manifest.json'
    manifest=read(manifest_path)
    if not manifest['frames']:raise ValueError('The recording contains no complete camera frames')
    raw=rows(case/'frames.jsonl')
    by_id={r['meta']['pair_id']:{**r,**r['meta'],'measurement':r['measurement']} for r in raw}
    for u in rows(case/'measurement-updates.jsonl'):
        if 'measurement' in u and 'source_pair_id' in u and u['source_pair_id'] in by_id:
            by_id[u['source_pair_id']]['measurement']=u['measurement']
    target=case/'analysis';target.mkdir(exist_ok=True)
    normalized=[]
    for meta in manifest['frames']:
        row=by_id.get(meta['pair_id'],{**meta,'measurement':{'status':'invalid'}})
        normalized.append(row)
    (target/'frames.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in normalized),encoding='utf-8')
    detections=[]
    for d in rows(case/'detections.jsonl'):
        detections.append({**d,**d['meta'],'eye':'right' if d['eye']==1 else 'left'})
    (target/'detections.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in detections),encoding='utf-8')
    event=capture.get('final_event') or {}
    if not event.get('fit_valid'):
        for row in normalized:
            m=row.get('measurement',{});e=(m.get('latest_valid_flight') or {}).get('event') or m.get('events') or {}
            if e.get('fit_valid'):event=e
    app={'source_video':case.name,'input_manifest':str(manifest_path.resolve()),'result':str(target),
         'calibration':str(case/'calibration.json'),'final_event':event,
         'processed':len(normalized),'capture':capture,'run_status':capture.get('run_status','saved')}
    receipt.write_text(json.dumps(app,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt
