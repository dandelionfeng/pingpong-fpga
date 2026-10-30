from pathlib import Path
from datetime import datetime,timedelta,timezone
import hashlib,json,os,shlex,subprocess,sys
BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parent
CASE_ROOT=ROOT/'data'
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
VERSION=read(BASE/'version.json');REMOTE=VERSION['board_root'];RESULT_ROOT=VERSION['result_root']
ADB=[str(BASE/'tools/adb/adb.exe'),'-s',VERSION['adb_serial']]
def now():return datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def log_path(label):
    path=ROOT/'logs'/(now()+'_'+label+'.log');path.parent.mkdir(parents=True,exist_ok=True);return path
def adb(args,capture=False,timeout=30):
    return subprocess.run(ADB+args,check=True,capture_output=capture,timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
def shell(args,capture=False,timeout=30):
    return adb(['shell',' '.join(shlex.quote(str(x)) for x in args)],capture,timeout)
def quiet(best_effort=False):
    try:shell(['dmesg','-n','4'],True,2 if best_effort else 8);return True
    except (OSError,subprocess.SubprocessError):
        if best_effort:return False
        raise RuntimeError('RK ADB未连接：检查J4数据线和开发板供电。')
def verify_local():
    manifest=read(BASE/'files-sha256.json')
    for r in manifest['files']:
        p=BASE/r['path']
        if not p.is_file() or sha(p)!=r['sha256']:raise RuntimeError('快速现场版文件缺失或被修改：'+str(p))
    final_manifest=BASE.parent/'最终版文件清单.json'
    if final_manifest.exists():
        root=BASE.parent.resolve()
        for r in read(final_manifest)['files']:
            p=(root/r['path']).resolve()
            if not p.is_relative_to(root) or not p.is_file() or sha(p)!=r['sha256']:raise RuntimeError('最终版文件缺失或被修改：'+str(p))
    return len(manifest['files'])
def logged(command,path,env=None,cancellable=False):
    from command_log import run_logged
    if not cancellable:return run_logged(command,path,env=env)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('ab') as out:
        out.write(('\nCOMMAND '+json.dumps(command)+'\n').encode());out.flush()
        process=subprocess.Popen(command,stdout=out,stderr=subprocess.STDOUT,env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
        last_stage=None
        while True:
            try:code=process.wait(timeout=2);break
            except subprocess.TimeoutExpired:
                try:
                    state=json.loads(shell(['cat',RESULT_ROOT+'/active-session.json'],True,5).stdout)
                    stage=state.get('stage')
                    if stage!=last_stage and state.get('status')=='running':
                        print({'setup':'配置相机……','capture':'正在录制原始视频……','analysis':'正在逐对识别与跟踪……','measurement':'正在完成离手与轨迹测量……'}.get(stage,'准备板端测试……'),flush=True)
                        last_stage=stage
                except (ValueError,OSError,subprocess.SubprocessError):pass
            except KeyboardInterrupt:
                print('\n正在请求正常停录；已采集帧随后会继续分析和保存。',flush=True)
                try:shell(['python3','-B',REMOTE+'/stop_capture.py'],True,10)
                except subprocess.SubprocessError:print('当前可能已进入分析阶段；请等待保存完成。',flush=True)
    if code:
        tail=path.read_text('utf-8',errors='replace').splitlines()[-10:]
        raise RuntimeError('板端步骤失败，日志：'+str(path)+'\n'+'\n'.join(tail))
def remote_job(args,label,cancellable=False):
    path=log_path(label);print('详细日志：',path,flush=True)
    command=ADB+['shell',' '.join(shlex.quote(str(x)) for x in args)]
    if not cancellable:return logged(command,path)
    # Report stages without forwarding per-frame kernel/runtime output to CMD.
    return logged(command,path,cancellable=True)
