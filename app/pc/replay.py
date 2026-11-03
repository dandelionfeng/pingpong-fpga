"""Build a portable, local-file HTML replay from a completed measurement case."""
from pathlib import Path
import argparse,base64,hashlib,json,math,subprocess,sys,os,time,platform
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from case_io import BASE,read,rows,receipt_path,calibration_for
from quick_common import CASE_ROOT

def write_pages(out,data):
    out=Path(out);template=(BASE/'pc/player.html').read_text(encoding='utf-8')
    icon='data:image/x-icon;base64,'+base64.b64encode((BASE/'ui/application.ico').read_bytes()).decode('ascii')
    template=template.replace('href="/application.ico?rev=20261031.02"','href="'+icon+'"')
    serialized=lambda d:json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    (out/'index.html').write_text(template,encoding='utf-8')
    (out/'data.js').write_text('window.REPLAY_DATA='+serialized(data)+';',encoding='utf-8')
    portable=dict(data);portable.pop('sessions',None)
    uri=lambda mime,path:'data:'+mime+';base64,'+base64.b64encode(Path(path).read_bytes()).decode('ascii')
    portable['video']=uri('video/mp4',out/'recording.mp4')
    standalone=template.replace('<script src="data.js"></script>','<script>window.REPLAY_DATA='+serialized(portable)+';</script>')
    if (out/'poster.jpg').exists():standalone=standalone.replace('poster="poster.jpg"','poster="'+uri('image/jpeg',out/'poster.jpg')+'"')
    standalone=standalone.replace('href="measurement.json" download','href="'+uri('application/json',out/'measurement.json')+'" download="measurement.json"')
    (out/'回放.html').write_text(standalone,encoding='utf-8')

def project(points,cal,eye):
    p=np.asarray(points,float).reshape(-1,3)
    camera=(np.asarray(cal['diagnostic_world_pose']['Rcw'])@p.T).T+cal['diagnostic_world_pose']['tcw']
    if eye:camera=(np.asarray(cal['R_left_to_right'])@camera.T).T+np.asarray(cal['T_m']).reshape(3)
    q,_=cv2.projectPoints(camera,np.zeros(3),np.zeros(3),np.asarray(cal['K_right' if eye else 'K_left'],float),np.asarray(cal['D_right' if eye else 'D_left'],float))
    return [xy.tolist() if z>0 and np.isfinite(xy).all() else None for xy,z in zip(q.reshape(-1,2),camera[:,2])]

def encode_video(manifest,path,out):
    signature=hashlib.sha256(path.read_bytes()).hexdigest()
    receipt=out/'replay-build.json';video=out/'recording.mp4'
    hardware=platform.machine()=='aarch64' and os.environ.get('REPLAY_ENCODER','mpp')=='mpp'
    if video.exists() and receipt.exists() and read(receipt).get('input_sha256')==signature:
        if not hardware or read(receipt).get('encoder')=='jpegdec-rk-mpp-h264':return
    began=time.perf_counter()
    if hardware:
        temporary=out/'recording.mpp.tmp.mp4'
        try:
            result=subprocess.run([sys.executable,str(BASE/'pc/encode_mpp.py'),str(path),str(temporary)],
                                  capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35)
            (out/'encoding-mpp.log').write_text(result.stdout+result.stderr,encoding='utf-8')
            if result.returncode:raise RuntimeError(result.stderr[-1600:])
            info=read(str(temporary)+'.json');temporary.replace(video)
            info.update(input_sha256=signature,video='recording.mp4',total_export_wall_ms=(time.perf_counter()-began)*1000)
            receipt.write_text(json.dumps(info,indent=2),encoding='utf-8')
            Path(str(temporary)+'.json').unlink(missing_ok=True)
            return
        except (OSError,RuntimeError,subprocess.TimeoutExpired) as error:
            (out/'encoding-mpp-fallback.log').write_text(str(error),encoding='utf-8')
            temporary.unlink(missing_ok=True)
    sys.path.insert(0,str(BASE/'tools/python'))
    import imageio_ffmpeg
    entries=manifest['frames'];concat=out/'encode-input.ffconcat'
    lines=['ffconcat version 1.0']
    stamps=[r['timestamp_ns'] for r in entries]
    durations=np.diff(stamps)*1e-9
    if len(durations) and (durations<=0).any():raise ValueError('Video timestamps are not increasing')
    tail=float(np.median(durations)) if len(durations) else 1/60
    for i,r in enumerate(entries):
        image=(path.parent/r['file']).resolve()
        if not image.is_file():raise FileNotFoundError(image)
        escaped=image.as_posix().replace("'","'\\''")
        lines.extend(["file '"+escaped+"'",'option framerate 1000','duration '+str(float(durations[i]) if i<len(durations) else tail)])
    concat.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    temporary=out/'recording.tmp.mp4'
    command=[imageio_ffmpeg.get_ffmpeg_exe(),'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(concat),
             '-an','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
             '-threads',os.environ.get('REPLAY_ENCODER_THREADS','2'),
             '-fps_mode','passthrough','-enc_time_base','1:1000','-x264-params','fps=60/1','-level:v','4.2',
             '-video_track_timescale','1000','-movflags','+faststart',str(temporary)]
    try:
        completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
        (out/'encoding.log').write_text(completed.stderr,encoding='utf-8')
        if completed.returncode:raise RuntimeError('Video export failed: '+completed.stderr[-1600:])
        temporary.replace(video)
    finally:concat.unlink(missing_ok=True)
    receipt.write_text(json.dumps({'input_sha256':signature,'frames':len(entries),'video':'recording.mp4','encoder':'libx264',
        'total_export_wall_ms':(time.perf_counter()-began)*1000,'timing':'V4L2/source sample timestamps, millisecond MP4 timebase'},indent=2),encoding='utf-8')

def build(case,output=None,latest=None):
    receipt=receipt_path(case).resolve();app=read(receipt)
    manifest_path=receipt.parent/'input/manifest.json'
    if not manifest_path.is_file():manifest_path=Path(app['input_manifest'])
    manifest=read(manifest_path)
    result_path=receipt.parent/'analysis/frames.jsonl'
    if not result_path.is_file():result_path=Path(app['result'])/'frames.jsonl'
    records=rows(result_path);by_id={r['pair_id']:r for r in records}
    event=app.get('final_event') or {};latest_path=receipt.parent/'motion-current/latest-release.json'
    if latest is None and latest_path.exists():latest=read(latest_path)
    event=(latest or {}).get('flight_event') or event
    out=Path(output) if output else receipt.parent/'replay';out.mkdir(parents=True,exist_ok=True)
    entries=manifest['frames'];start=entries[0]['timestamp_ns'];times=[(r['timestamp_ns']-start)*1e-9 for r in entries]
    step=float(np.median(np.diff(times))) if len(times)>1 else 1/60
    data={'title':app.get('display_name') or Path(app['source_video']).stem.removesuffix('.avi'),'video':'recording.mp4','times':times,'pairs':[r['pair_id'] for r in entries],
          'fps':1/step,'duration':times[-1]+step,'metrics':None,'curve':[[],[]],'keypoints':[{},{}],
          'observed':[[],[]],'geometry':{},'curveTimes':[],'observedTimes':[],
          'stop_reason':app.get('capture',{}).get('stop_reason','saved')}
    summary_path=receipt.parent/'summary.json'
    summary=read(summary_path) if summary_path.exists() else {}
    # Early synchronous runs did not stamp backend completion time. Retain the
    # raw board record and omit its invalid derived latency from presentation.
    summary['timings']={k:v for k,v in summary.get('timings',{}).items() if v.get('mean_ms',0)>=0}
    profile_path=receipt.parent.parent/(receipt.parent.name+'-profile.json')
    profile=read(profile_path) if profile_path.exists() else {}
    data['performance']={'host':'RK3576' if summary else 'PC','scope':summary.get('latency_scope','未记录逐模块时延'),
        'summary':summary,'cpu_percent':summary.get('main_process_cpu_percent_all_8_cores'),
        'release':(latest or {}).get('timing',{}),'profile_samples':len(profile.get('samples',[]))}
    from timing_report import describe_timing
    data['performance']['timing_report']=describe_timing(receipt.parent)
    data['processing']={'mode':summary.get('mode'),'hand_stride':summary.get('hand_schedule',{}).get('stride'),
        'motion_status':(latest or {}).get('motion_status'),'method':(latest or {}).get('method'),
        'measurement_host':read(receipt.parent/'measurement-complete.json').get('measurement_host') if (receipt.parent/'measurement-complete.json').exists() else None}
    data.update(measurementEstimated=(latest or {}).get('measurement_estimated',False),
                metricKind=(latest or {}).get('metric_kind'),qualityNote=(latest or {}).get('quality_note'))
    updates=rows(receipt.parent/'measurement-updates.jsonl')
    semantic={u['source_pair_id']:u.get('input_to_measurement_update_ms',u.get('input_to_semantic_measurement_ms'))
              for u in updates if 'source_pair_id' in u and ('input_to_measurement_update_ms' in u or 'input_to_semantic_measurement_ms' in u)}
    ai={}
    for d in rows(receipt.parent/'detections.jsonl'):
        pid=d.get('pair_id',d.get('meta',{}).get('pair_id'));t=d.get('diagnostics',{})
        if pid is not None:
            dest=ai.setdefault(pid,{})
            for key in ('infer_ms','input_to_detection_ms','submit_to_complete_ms'):
                if key in t and t[key]>=0:dest[key]=max(dest.get(key,0),t[key])
    data['latencyFrames']=[{'main':by_id.get(r['pair_id'],{}).get('timings_ms',{}),'ai':ai.get(r['pair_id'],{}),
                            'semantic_ms':semantic.get(r['pair_id'])} for r in entries]
    if latest and (event.get('fit_valid') or latest.get('trajectory_available')) and 'x_coefficients' in event:
        release_valid=latest.get('release_valid',True)
        display_metrics=release_valid or latest.get('measurement_available',False)
        release=np.asarray(latest['release_world_m'] if display_metrics else
                           [event['x_coefficients'][0],event['y_coefficients'][0],event['z_coefficients'][0]],float)
        apex=np.asarray(event['apex_world_m'],float)
        height=float(apex[2]-release[2]);horizontal=float(np.linalg.norm(apex[:2]-release[:2]))
        angle=float(latest['angle_deg']) if display_metrics else 0.
        if height<0 or not np.isfinite([height,angle]).all():raise ValueError('Invalid replay measurement')
        if display_metrics:data['metrics']={'height_cm':float(latest['height_cm']),'angle_deg':angle}
        data.update(curveValid=True,releaseValid=release_valid,motionStatus=latest.get('motion_status'))
        release_ns=latest['candidate']['timestamp_ns'] if display_metrics else event['fit_origin_ns']
        apex_ns=event['fit_origin_ns']+event['apex_s']*1e9
        data['releaseTime']=(release_ns-start)*1e-9;data['apexTime']=(apex_ns-start)*1e-9
        data['metricRevealTime']=min(max(data['releaseTime'],data['apexTime']),times[-1])
        selected=set(event['used_pair_ids']);observed=[]
        for r in records:
            m=r['measurement'];xyz=m.get('world_xyz_m')
            if r['pair_id'] in selected and m.get('semantic_ball_supported') and xyz and m.get('status')=='observed':
                observed.append(xyz);data['observedTimes'].append((r['timestamp_ns']-start)*1e-9)
        if not release_valid:
            observed=[r['world_m'] for r in latest.get('observations',[])]
            data['observedTimes']=[(r['timestamp_ns']-start)*1e-9 for r in latest.get('observations',[])]
        last=max([by_id[i]['timestamp_ns'] for i in selected if i in by_id]+[apex_ns])
        begin=min([release_ns]+[r['timestamp_ns'] for r in latest.get('observations',[])])
        t=np.linspace((begin-event['fit_origin_ns'])*1e-9,(last-event['fit_origin_ns'])*1e-9,100)
        x,y,z=(event[k] for k in ('x_coefficients','y_coefficients','z_coefficients'))
        curve=np.column_stack((x[0]+x[1]*t,y[0]+y[1]*t,z[0]+z[1]*t+z[2]*t*t))
        data['curveTimes']=((event['fit_origin_ns']-start)*1e-9+t).tolist()
        cal=read(calibration_for(app,event,receipt));foot=np.array([apex[0],apex[1],release[2]])
        for eye in (0,1):
            data['curve'][eye]=project(curve,cal,eye)
            keys=project([release,apex,foot],cal,eye);data['keypoints'][eye]=dict(zip(('release','apex','foot'),keys))
            if not display_metrics:data['keypoints'][eye].update(release=None,foot=None)
            data['observed'][eye]=project(observed,cal,eye) if observed else []
        unit=(apex[:2]-release[:2])/horizontal if horizontal else np.array([1.,0.])
        def plane(points):
            points=np.asarray(points,float).reshape(-1,3)
            return np.column_stack(((points[:,:2]-release[:2])@unit,points[:,2]-release[2])).tolist()
        data['geometry']={'curve':plane(curve),'points':plane(observed),'release':[0,0],
                          'apex':[horizontal,height],'foot':[horizontal,0]}
    elif latest and latest.get('observations'):
        points=latest['observations'];cal=read(calibration_for(app,{},receipt))
        data.update(curveValid=True,releaseValid=False,motionStatus=latest.get('motion_status'))
        data['observedTimes']=[(p['timestamp_ns']-start)*1e-9 for p in points]
        data['releaseTime']=data['observedTimes'][0]
        for eye in (0,1):data['observed'][eye]=project([p['world_m'] for p in points],cal,eye)
    encode_video(manifest,manifest_path,out)
    # Export may have just completed; refresh the timing snapshot afterwards.
    data['performance']['timing_report']=describe_timing(receipt.parent)
    data['performance']['export']=read(out/'replay-build.json')
    poster_i=min(range(len(times)),key=lambda i:abs(times[i]-data.get('releaseTime',times[len(times)//2])))
    # OpenCV's Windows filename API does not reliably accept Chinese paths.
    poster_source=manifest_path.parent/entries[poster_i]['file']
    poster=cv2.imdecode(np.fromfile(poster_source,dtype=np.uint8),cv2.IMREAD_COLOR) if poster_source.is_file() else None
    if poster is not None:
        ok,encoded=cv2.imencode('.jpg',poster,[cv2.IMWRITE_JPEG_QUALITY,88])
        if not ok:raise RuntimeError('Replay poster encoding failed')
        encoded.tofile(out/'poster.jpg')
    (out/'measurement.json').write_text(json.dumps(latest or {},ensure_ascii=False,indent=2),encoding='utf-8')
    write_pages(out,data)
    result_root=CASE_ROOT;result_root.mkdir(exist_ok=True)
    page=(out/'index.html').resolve()
    pointer=page.relative_to(result_root.resolve()) if page.is_relative_to(result_root.resolve()) else page
    (result_root/'latest-replay.txt').write_text(str(pointer),encoding='utf-8')
    print('REPLAY',out/'index.html')
    return out/'index.html'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('--output',type=Path);a=p.parse_args();build(a.case,a.output)
