"""Import original MJPEG packets, run both INT8 models on RK, then render on PC."""
from pathlib import Path
from datetime import datetime
import argparse, hashlib, json, re, shlex, subprocess, sys
from case_io import BASE
from command_log import run_logged

ADB=[str(BASE/'tools/adb/adb.exe'),'-s','2342f1aa3c720c76']
REMOTE='/userdata/pingpong-field-test'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path,nargs='?')
    p.add_argument('--name')
    a=p.parse_args()
    if a.video is None:
        a.video=Path(input('Stereo AVI path (2560x720 MJPEG): ').strip().strip('"'))
    video=a.video.resolve()
    if not video.is_file():raise FileNotFoundError(video)
    name=a.name or ('int8_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('Use letters, numbers, _ or - for the case name')
    if (BASE/'results'/name).exists():raise FileExistsError('Use a new case name')
    log=BASE/'results/run-logs'/(name+'.log')
    print('CASE',name,flush=True)
    print('[1/4] Importing original stereo frames on PC...',flush=True)
    run_logged(ADB+['get-state'],log)
    inp=BASE/'results/board-inputs'/name
    if inp.exists():raise FileExistsError('Use a new case name: input already exists')
    run_logged([str(BASE/'bin/pc/pipeline_cli.exe'),'--import-video',str(video),
                    '--manifest',str(inp/'manifest.json')],log)
    manifest=json.loads((inp/'manifest.json').read_text('utf-8'))
    (inp/'source.json').write_text(json.dumps({'video':str(video),
        'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'pairs':len(manifest['frames']),
        'processing':'original JPEG packet extraction on PC; FPGA, INT8 models, TESO and fitting on RK'},indent=2),encoding='utf-8')
    remote_input='/root/pingpong-field-test-inputs/'+name
    print('[2/4] Sending',len(manifest['frames']),'stereo pairs to RK...',flush=True)
    run_logged(ADB+['shell','test ! -e '+shlex.quote(remote_input)+' && mkdir -p /root/pingpong-field-test-inputs'],log)
    run_logged(ADB+['push',str(inp),remote_input],log)
    # Rebind a programmed FPGA after RK restart; no bitstream or boot change.
    print('[3/4] RK: FPGA + full-frame INT8 + TESO + motion release. Please wait.',flush=True)
    run_logged(ADB+['shell','test -c /dev/ANLOGIC-PCI0_h2c_0 || sh '+REMOTE+
                    '/rebind_pcie.sh /userdata/codex-full-project-20261017/pcie-audit/driver-inflight-guard/anlogic_pci.ko'],log)
    run_logged(ADB+['shell','sh '+REMOTE+'/run_recorded.sh '+shlex.quote(name)+' '+
                    shlex.quote(remote_input+'/manifest.json')+' batch 0'],log)
    print('[4/4] Retrieving RK result and generating replay on PC...',flush=True)
    run_logged([sys.executable,str(BASE/'pc/pull_recording.py'),name],log)
    print('DONE. Details:',log,flush=True)
    print('READY',BASE/'results'/name/'replay/index.html')

if __name__=='__main__':main()
