"""Same frozen two-stage capture flow with the validated30.92 executable."""
from pathlib import Path
import argparse,fcntl,json,math,os,re,signal,subprocess,sys,time
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from preflight import check,quiet
from capture_session import allocate
VERSION=json.loads((ROOT/'version.json').read_text());RESULTS=Path(VERSION['result_root'])
STATE=RESULTS/'active-session.json';child=None;phase='starting';state={};log=None
job_started=time.perf_counter();stage_times={}
def persist(**kw):
    state.update(kw);tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2));tmp.replace(STATE)
def emit(text):print(text,flush=True)
def interrupted(signum,frame):
    if phase=='capture' and child is not None and child.poll() is None:
        child.send_signal(signal.SIGINT);emit('STOP_REQUESTED: saving captured frames, then analysis continues')
    else:emit('ANALYSIS_CONTINUES: saved inputs are being processed; results will be retained')
def execute(args,env=None,capture=False):
    global child
    stage_started=time.perf_counter()
    log.write(('\nCOMMAND '+json.dumps([str(x) for x in args])+'\n').encode());log.flush()
    child=subprocess.Popen([str(x) for x in args],env=env,stdout=log,stderr=subprocess.STDOUT)
    if capture:persist(capture_pid=child.pid)
    code=child.wait();child=None
    stage_times[phase]=stage_times.get(phase,0)+(time.perf_counter()-stage_started)
    if code:
        log.flush()
        recent=Path(state['log']).read_bytes()[-2400:].decode('utf-8',errors='replace').splitlines()
        reason=' | '.join(s.strip()[:180] for s in recent[-5:] if s.strip())
        raise RuntimeError(f'Stage {phase} failed ({code}); {reason}; details: {state["log"]}')
def process_manifest(name,manifest,frontend='fpga',capture_path=None):
    global phase
    case=RESULTS/name;phase='analysis';persist(stage=phase,capture_pid=None)
    emit('ANALYSIS_RUNNING '+name+'; NPU ball on every pair; hand stops after kinematic candidate')
    execute([sys.executable,'-B',ROOT/'board_case.py','--root',ROOT,'--output-root',RESULTS,'--name',name,
        '--input',manifest,'--model-config',ROOT/'model-config-int8.json','--mode','batch','--frontend',frontend,
        '--pace','0','--teso-stride','30','--performance','--timeout','7200'])
    import shutil
    for n in ['calibration.json','model-config-int8.json','version.json']:shutil.copyfile(ROOT/n,case/n)
    phase='save_inputs';persist(stage=phase)
    execute([sys.executable,'-B',ROOT/'save_case_input.py',case,manifest])
    if capture_path:
        for a,b in [('capture-complete.json','camera-acquisition.json'),('camera-settings.json','camera-settings.json')]:shutil.copyfile(capture_path/a,case/b)
    phase='measurement';persist(stage=phase)
    execute(['taskset','-c','6',sys.executable,'-B',ROOT/'finish_measurement.py',case])
    result=json.loads((case/'measurement-complete.json').read_text())
    summary=json.loads((case/'summary.json').read_text())
    receipt={'version':VERSION['version'],'input_manifest':str(manifest),'frontend':frontend,
        'original_capture_preserved':str(capture_path) if capture_path else None,
        'model_config':'model-config-int8.json','model_stop':'kinematic candidate stops only hand/racket',
        'run_status':summary['status'],'fit_valid':result['fit_valid'],'release_valid':result['release_valid'],
        'measurement_estimated':result['measurement_estimated']}
    (case/'field-run.json').write_text(json.dumps(receipt,indent=2))
    timing={'schema_version':1,'clock':'single RK process time.perf_counter; no PC/RK clock subtraction',
        'total_wall_s':time.perf_counter()-job_started,'stages_s':stage_times,
        'analysis_main_s':summary['main_elapsed_ms']/1000,'source':'recording job start through final RK measurement save',
        'includes_preflight_setup_capture_analysis_and_postprocess':True,
        'excludes':['human cable switching','USB retrieval','PC replay generation']}
    (case/'workflow-timing.json').write_text(json.dumps(timing,indent=2))
    status='MEASURED' if result['fit_valid'] and not result['measurement_estimated'] else ('ESTIMATED' if result.get('measurement_available') else 'NO_VALID_FIT')
    emit('MEASUREMENT_SAVED '+status+' name='+name+' main_seconds='+str(round(summary['main_elapsed_ms']/1000,3)))
    persist(stage='complete',status='complete',case=str(case),measurement=receipt,capture_pid=None)
    emit('RECORDING_SAVED '+str(case));emit('PC_REPLAY_REQUIRED name='+name)
def main():
    global phase,log
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('camera');c.add_argument('--device',required=True);c.add_argument('--exposure',default='auto');c.add_argument('--seconds',type=float,default=30);c.add_argument('--name',default='auto')
    r=sub.add_parser('recorded');r.add_argument('--input',type=Path,required=True);r.add_argument('--name',required=True)
    d=sub.add_parser('diagnostic');d.add_argument('--input',type=Path,required=True);d.add_argument('--name',required=True)
    a=p.parse_args();quiet();RESULTS.mkdir(exist_ok=True,parents=True)
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.name):raise ValueError('Invalid recording name')
    with Path('/run/lock/pingpong-quick-field-3092.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('A quick field session is already running')
        check(require_fpga=a.action!='diagnostic',require_camera=a.action=='camera',rebind=a.action!='diagnostic')
        if a.action=='camera':
            if not math.isfinite(a.seconds) or not 0<a.seconds<=300:raise ValueError('Recording duration must be0..300seconds')
            if a.exposure!='auto' and (not a.exposure.isdigit() or int(a.exposure)<=0):raise ValueError('Invalid exposure')
            if not re.fullmatch(r'/dev/video\d+',a.device):raise ValueError('Select a UVC /dev/videoN node')
            devices=check()['cameras']
            if a.device not in [d['device'] for d in devices]:raise ValueError('Selected node is not a supported USB stereo camera')
            name=allocate(RESULTS,ROOT,a.name,a.seconds)
        else:
            if not a.input.is_file():raise FileNotFoundError(a.input)
            if (RESULTS/a.name).exists():raise FileExistsError('Result already exists; choose a new name')
            name=a.name
        persist(version=VERSION['version'],workflow_pid=os.getpid(),stage='starting',status='running',name=name,
            log=str(RESULTS/(name+'-session.log')),capture_pid=None)
        signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
        try:
            with Path(state['log']).open('ab') as session_log:
                log=session_log
                if a.action=='camera':
                    phase='setup';persist(stage=phase);execute(['sh',ROOT/'camera.sh','setup',a.device,a.exposure,'0'])
                    capture_path=RESULTS/(name+'_input');phase='capture';persist(stage=phase)
                    emit('RECORDING_NAME '+name);emit('CAPTURE_RUNNING seconds='+str(a.seconds)+' exposure='+a.exposure)
                    env=os.environ.copy();env.update(CHAIN_CAMERA=a.device,CHAIN_CAMERA_EXPOSURE=a.exposure,CHAIN_CAPTURE_MAX_SECONDS=str(a.seconds),
                        CHAIN_TESO='0',CHAIN_PARALLEL_EYES='0',CHAIN_HAND_KINEMATIC_MODE='off')
                    execute([ROOT/'build/motion7_chain_kinematic','@camera',ROOT/'calibration.json',ROOT/'model-config-int8.json',capture_path,'none','1','0','1','0'],env,capture=True)
                    emit('CAPTURE_SAVED '+str(capture_path))
                    process_manifest(name,capture_path/'input/manifest.json','fpga',capture_path)
                else:process_manifest(name,a.input,'cpu' if a.action=='diagnostic' else 'fpga')
        except BaseException as e:
            persist(status='failed',stage=phase,error=str(e));raise
if __name__=='__main__':
    try:main()
    except Exception as e:print('FIELD_FAILED: '+str(e),file=sys.stderr);sys.exit(2)
