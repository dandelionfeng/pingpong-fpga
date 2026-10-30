"""Separate per-pair queue latency from whole-recording wait, without clock mixing."""
from pathlib import Path
import json,math
def read(p):
    try:return json.loads(Path(p).read_text('utf-8-sig'))
    except (OSError,ValueError):return {}
def ms_s(value):
    return value/1000 if isinstance(value,(int,float)) and math.isfinite(value) and value>=0 else None
def describe_timing(case):
    case=Path(case);s=read(case/'summary.json');completion=read(case/'measurement-complete.json')
    profile=read(case.parent/(case.name+'-profile.json'));board=read(case/'workflow-timing.json');client=read(case/'client-timing.json')
    latency=s.get('timings',{}).get('load_to_measurement_latency' if s.get('mode')=='batch' else 'input_to_measurement_update',{})
    manifest=read(case/'input/manifest.json');frames=manifest.get('frames',[])
    sampled=(frames[-1]['timestamp_ns']-frames[0]['timestamp_ns'])/1e9 if len(frames)>1 else None
    capture=read(case/'camera-acquisition.json')
    capture_wall=board.get('stages_s',{}).get('capture',ms_s(capture.get('elapsed_ms')))
    main=ms_s(s.get('main_elapsed_ms'));post=ms_s(completion.get('measurement_wall_ms'))
    export=ms_s(read(case/'replay/replay-build.json').get('total_export_wall_ms'))
    return {'schema_version':1,'pair_latency_ms':latency.get('mean_ms'),'pair_latency_p95_ms':latency.get('p95_ms'),
        'pair_latency_scope':'文件帧入队→该帧在线结果，含排队；不含录制、整段等待和最终后处理',
        'analysis_main_s':main,'analysis_process_s':profile.get('wall_s'),'postprocess_s':post,
        'capture_s':capture_wall,'source_span_s':sampled,'board_total_s':board.get('total_wall_s'),
        'retrieve_s':client.get('retrieve_s'),'replay_build_s':client.get('replay_build_s'),'video_export_s':export,
        'recorded_phase_sum_s':sum(v for v in [capture_wall,profile.get('wall_s',main),post,client.get('retrieve_s'),client.get('replay_build_s',export)] if isinstance(v,(int,float))),
        'complete_end_to_end_available':False,'end_to_end_note':'人工换线和等待未自动计时；未将不同设备的时钟直接相减',
        'board_timing_available':bool(board),'pairs':s.get('pairs',len(frames))}
