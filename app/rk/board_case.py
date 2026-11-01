"""Measured RK case: real inputs, bounded queues, CPU/NPU/thermal telemetry.

One Linux process per case. Governor changes are temporary and restored in finally.
100% process CPU means one busy core; the RK3576 has eight cores.
"""
import argparse, hashlib, json, os, platform, resource, subprocess, time
from pathlib import Path
from runtime_paths import OpenCVPathError, environment_with_opencv

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--name',required=True)
    p.add_argument('--output-root',type=Path)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--model-config',type=Path,required=True)
    p.add_argument('--frontend',choices=['fpga','cpu'],default='fpga')
    p.add_argument('--mode',choices=['none','async','batch'],default='async')
    p.add_argument('--no-teso',action='store_true');p.add_argument('--teso-stride',type=int,default=30)
    p.add_argument('--pace',type=float,default=60);p.add_argument('--limit',type=int,default=0)
    p.add_argument('--verify-mask',action='store_true');p.add_argument('--performance',action='store_true')
    p.add_argument('--timeout',type=float,default=240)
    a=p.parse_args();assert platform.machine()=='aarch64';assert a.name and all(c.isalnum() or c in '-_' for c in a.name)
    output_root=a.output_root or a.root;output_root.mkdir(parents=True,exist_ok=True)
    out=output_root/a.name;assert not out.exists(),'Use a new case name'
    exe=a.root/'build/motion7_chain_kinematic';cal=a.root/'calibration.json'
    for x in [exe,cal,a.input,a.model_config]:assert x.is_file(),x
    cmd=[str(exe),str(a.input),str(cal),str(a.model_config),str(out),a.mode,str(int(a.frontend=='fpga')),str(a.limit),'1','0']
    try:
        repo_root=a.root.resolve().parents[1]
        opencv_lib_dir,env=environment_with_opencv(repo_root)
    except OpenCVPathError as error:
        raise SystemExit('BOARD_CASE_FAILED: '+str(error))
    # Clear mode switches inherited from interactive experiments.
    for key in ['CHAIN_TESO','CHAIN_VERIFY_FPGA_MASK','CHAIN_BALL_MODEL','PIPELINE_TESO_SYNC_EVAL']:
        env.pop(key,None)
    env.update(CHAIN_STREAMING='1',CHAIN_PIN='1',CHAIN_CV_THREADS='1',CHAIN_FAST_BINARY_MORPH='1',
               PIPELINE_B_DIAGNOSTIC_RELAX='1',PIPELINE_MASK_RELEASE='1',CHAIN_PACE_FPS=str(a.pace),CHAIN_TESO_STRIDE=str(a.teso_stride))
    if not a.no_teso:env['CHAIN_TESO']='1'
    if a.verify_mask:assert a.frontend=='fpga';env['CHAIN_VERIFY_FPGA_MASK']='1'
    governors=[Path(x) for x in ['/sys/devices/system/cpu/cpufreq/policy0/scaling_governor',
               '/sys/devices/system/cpu/cpufreq/policy4/scaling_governor',
               '/sys/class/devfreq/27700000.npu/governor','/sys/class/devfreq/dmc/governor']]
    saved={str(x):x.read_text().strip() for x in governors}
    samples=[];proc=None;started=time.monotonic();rc=None
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        if a.performance:
            for x in governors:x.write_text('performance')
        with (output_root/(a.name+'.log')).open('w') as log:
            proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
            while proc.poll() is None:
                if time.monotonic()-started>a.timeout:raise TimeoutError('bounded hardware case timeout')
                row={'monotonic_elapsed_s':time.monotonic()-started}
                for key,path in [('thermal_millicelsius','/sys/class/thermal/thermal_zone0/temp'),
                  ('npu_load','/sys/kernel/debug/rknpu/load'),('big_khz','/sys/devices/system/cpu/cpufreq/policy4/scaling_cur_freq'),
                  ('little_khz','/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq'),
                  ('npu_hz','/sys/class/devfreq/27700000.npu/cur_freq'),('dmc_hz','/sys/class/devfreq/dmc/cur_freq'),
                  ('proc_stat',f'/proc/{proc.pid}/stat'),('proc_io',f'/proc/{proc.pid}/io'),
                  ('proc_status',f'/proc/{proc.pid}/status'),('system_cpu','/proc/stat')]:
                    try:row[key]=Path(path).read_text().strip()
                    except OSError:pass
                samples.append(row);time.sleep(.5)
            rc=proc.returncode
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        if proc is not None and rc is None:rc=proc.returncode
        if a.performance:
            for path,value in saved.items():Path(path).write_text(value)
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt={'args':vars(a)|{'root':str(a.root),'input':str(a.input),'model_config':str(a.model_config),'output_root':str(output_root)},
          'command':cmd,'exit_code':rc,'wall_s':time.monotonic()-started,
          'cpu_user_s':after.ru_utime-before.ru_utime,'cpu_system_s':after.ru_stime-before.ru_stime,
          'governors_before':saved,'governors_after':{str(x):x.read_text().strip() for x in governors},
          'sha256':{str(x):sha(x) for x in [exe,cal,a.input,a.model_config]},'samples':samples,
          'opencv_lib_dir':str(opencv_lib_dir),'ld_library_path':env.get('LD_LIBRARY_PATH',''),
          'clock':'monotonic; board civil clock is not used for latency or algorithm sampling'}
        (output_root/(a.name+'-profile.json')).write_text(json.dumps(receipt,indent=2))
    assert saved==receipt['governors_after']
    if rc:raise SystemExit(rc)
    s=json.loads((out/'summary.json').read_text())
    print(json.dumps({'case':a.name,'status':s['status'],'main_pairs_s':s['main_pairs_per_second'],
         'eye_tasks_s':s['eye_tasks_per_second'],'cpu_one_core_pct':s['main_process_cpu_percent_one_core'],
         'teso':s.get('online_teso'),'governors_restored':True}),flush=True)
if __name__=='__main__':main()
