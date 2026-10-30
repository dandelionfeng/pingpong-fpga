"""Retrieve a stopped RK recording over USB and create its local HTML replay."""
from pathlib import Path
import argparse,re,subprocess,sys,os
from case_io import BASE,normalize_board,read
import json
from command_log import run_logged

def prepare_replay(case):
    """Relocate saved RK paths; leave release calculation and results on RK."""
    case=Path(case).resolve()
    completion=read(case/'measurement-complete.json')
    if completion.get('measurement_host')!='RK' or completion.get('execution_host')!='aarch64':
        raise ValueError('Recording has no completed RK motion-release result')
    if completion['status'] not in ('measured','estimated','no_valid_fit'):
        raise ValueError('RK motion-release calculation did not complete')
    receipt=normalize_board(case)
    app=read(receipt)
    app.update(input_manifest=str(case/'input/manifest.json'),result=str(case/'analysis'),
               calibration=str(case/'calibration.json'))
    manifest=read(case/'input/manifest.json')
    app['source_video']=manifest.get('provenance',{}).get('video_path',app.get('source_video',case.name))
    if (app.get('final_event') or {}).get('fit_valid'):
        if completion['status'] not in ('measured','estimated') or not (case/'motion-current/latest-release.json').is_file():
            raise ValueError('RK motion-release result is missing; finish measurement on RK first')
    receipt.write_text(json.dumps(app,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--remote-root');a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.name):raise ValueError('Use the recording name shown on RK')
    destination=BASE/'results'/a.name
    if destination.exists():raise FileExistsError('This recording already exists: '+str(destination))
    log=BASE/'results/run-logs'/(a.name+'-retrieve.log')
    adb=[str(BASE/'tools/adb/adb.exe'),'-s','2342f1aa3c720c76']
    roots=[a.remote_root] if a.remote_root else ['/root/pingpong-field-test-results','/userdata/pingpong-field-test']
    remote=None
    for root in roots:
        candidate=root+'/'+a.name
        if subprocess.run(adb+['shell','test -f '+candidate+'/measurement-complete.json'],capture_output=True).returncode==0:
            remote=candidate;break
    if remote is None:raise FileNotFoundError('No completed RK measurement found for '+a.name)
    print('Retrieving completed RK recording:',a.name,flush=True)
    run_logged(adb+['shell','test -f '+remote+'/measurement-complete.json'],log)
    run_logged(adb+['pull',remote,str(destination)],log)
    receipt=prepare_replay(destination)
    env=os.environ.copy();env.setdefault('REPLAY_ENCODER_THREADS','8')
    print('Generating HTML replay on PC...',flush=True)
    run_logged([sys.executable,str(BASE/'pc/replay.py'),str(receipt)],log,env=env)
    print('OPEN',destination/'replay/index.html')
if __name__=='__main__':main()
