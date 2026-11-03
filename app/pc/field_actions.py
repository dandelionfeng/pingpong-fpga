from pathlib import Path
import json,os,re,shlex,subprocess,sys,time,webbrowser
sys.path.insert(0,str(Path(__file__).resolve().parent))
from quick_common import *
from deploy_quick_field import deploy
def status():
    info=deploy()
    if not info['fpga_ready']:info=json.loads(shell(['python3','-B',REMOTE+'/preflight.py','--rebind'],True,40).stdout)
    print(json.dumps(info,ensure_ascii=False,indent=2));return info
def resolve_recording_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('Invalid recording name')
    index=read(CASE_ROOT/'index.json') if (CASE_ROOT/'index.json').exists() else {}
    mappings=index.get('renumbering',[])
    local_name=next((r['case'] for r in mappings if r['original_case']==name),name)
    if local_name==name and any(r['case']==name and r['original_case']!=name for r in mappings):local_name='rk_'+name
    return local_name

def rebuild_local(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('Invalid local case name')
    case=CASE_ROOT/name;validate_case(case)
    from pull_recording import prepare_replay
    receipt=prepare_replay(case)
    logged([sys.executable,'-B',str(BASE/'pc/replay.py'),str(receipt)],log_path('rebuild_'+name))
    return case/'replay/回放.html'

def _remote_case_signature(remote):
    names=['measurement-complete.json','summary.json','input/manifest.json']
    response=shell(['sha256sum',*[remote+'/'+name for name in names]],True)
    lines=response.stdout.decode('utf-8','replace').splitlines()
    if len(lines)!=len(names):raise ValueError('板端结果校验清单不完整')
    signature={}
    for name,line in zip(names,lines):
        digest=line.split()[0] if line.split() else ''
        if not re.fullmatch(r'[0-9a-fA-F]{64}',digest):raise ValueError('板端结果校验值无效')
        signature[name]=digest.lower()
    return signature

def _matches_remote(case,signature):
    return all((case/name).is_file() and sha(case/name)==digest for name,digest in signature.items())

def retrieve(name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('结果名仅允许字母、数字、下划线及短横线。')
    local_name=resolve_recording_name(name)
    # Historical exhibition aliases stay read-only. New board results retain
    # their original ID under rk_ when an alias would collide with a sample.
    if local_name!=name:local_name='rk_'+name
    case=CASE_ROOT/local_name;remote=RESULT_ROOT+'/'+name
    signature=_remote_case_signature(remote)
    reusable=_matches_remote(case,signature)
    if reusable:
        try:validate_case(case)
        except (OSError,ValueError,KeyError):reusable=False
    client=read(case/'client-timing.json') if reusable and (case/'client-timing.json').exists() else {}
    if not reusable:
        retrieval_started=time.perf_counter()
        incoming=CASE_ROOT/'.incoming';incoming.mkdir(parents=True,exist_ok=True)
        stage=incoming/(name+'-'+str(time.time_ns()))
        logged(ADB+['pull',remote,str(stage)],log_path('retrieve_'+name))
        validate_case(stage)
        if not _matches_remote(stage,signature):raise ValueError('板端结果在取回期间发生变化，请重新取回')
        root=CASE_ROOT.resolve();backup=None
        assert stage.resolve().is_relative_to(root) and case.resolve().is_relative_to(root)
        if case.exists():
            backup=CASE_ROOT/'.history'/(case.name+'-'+str(time.time_ns()))
            assert backup.resolve().is_relative_to(root)
            backup.parent.mkdir(parents=True,exist_ok=True);case.rename(backup)
        try:stage.rename(case)
        except BaseException:
            if backup and backup.exists() and not case.exists():backup.rename(case)
            raise
        client['retrieve_s']=time.perf_counter()-retrieval_started
        for suffix in ['-profile.json','-session.log']:
            remote_file=RESULT_ROOT+'/'+name+suffix
            exists=subprocess.run(ADB+['shell','test -f '+shlex.quote(remote_file)],capture_output=True)
            if exists.returncode==0:logged(ADB+['pull',remote_file,str(CASE_ROOT/(case.name+suffix))],log_path('sidecar_'+name))
    validate_case(case)
    (case/'client-timing.json').write_text(json.dumps(client,indent=2),encoding='utf-8')
    from pull_recording import prepare_replay
    receipt=prepare_replay(case)
    env=os.environ.copy();env['REPLAY_ENCODER_THREADS']='8'
    rebuild_started=time.perf_counter()
    logged([sys.executable,'-B',str(BASE/'pc/replay.py'),str(receipt)],log_path('replay_'+name),env=env)
    client['replay_build_s']=time.perf_counter()-rebuild_started
    (case/'client-timing.json').write_text(json.dumps(client,indent=2),encoding='utf-8')
    page=case/'replay/回放.html';print('回放已生成：',page,flush=True)
    completion=read(case/'measurement-complete.json')
    if completion['fit_valid'] and not completion['measurement_estimated']:print('结果：有效离手/拟合；具体数值见回放。')
    else:print('结果：未确认有效拟合；回放中的估算已标记。')
    return page

def validate_case(case):
    for name in ['measurement-complete.json','summary.json','input/manifest.json','version.json']:
        if not (case/name).is_file():raise ValueError('结果尚未保存完整：'+str(case/name))
    if read(case/'version.json')['version']!=VERSION['version']:raise ValueError('结果版本不属于当前快速现场版。')
    summary=read(case/'summary.json');manifest=read(case/'input/manifest.json')
    if summary['status']!='passed' or summary['pairs']!=len(manifest['frames']):raise ValueError('处理未完整覆盖录制帧，保留原结果供排查。')
    for row in manifest['frames']:
        if sha(case/'input'/row['file'])!=row['sha256']:raise ValueError('输入JPEG校验失败：'+row['file'])
def latest():
    page=latest_path();webbrowser.open(page.resolve().as_uri());return page

def latest_path():
    root=(CASE_ROOT).resolve();pointer=root/'latest-replay.txt'
    if pointer.exists():
        candidate=Path(pointer.read_text('utf-8-sig').strip())
        if not candidate.is_absolute():candidate=root/candidate
        if candidate.is_file() and candidate.resolve().is_relative_to(root):return candidate.resolve()
    candidates=[p for pattern in ('*/replay/回放.html','*/replay/index.html') for p in root.glob(pattern) if (p.parents[1]/'measurement-complete.json').exists()]
    if not candidates:raise ValueError('暂无本版本回放，请先用选项8取回已完成结果。')
    page=max(candidates,key=lambda p:p.stat().st_mtime_ns).resolve()
    pointer.write_text(str(page),encoding='utf-8');return page
def camera(seconds=30,exposure='auto',device=None):
    info=deploy()
    if not info['fpga_ready']:
        print('正在检查FPGA PCIe……',flush=True)
        info=json.loads(shell(['python3','-B',REMOTE+'/preflight.py','--require-fpga','--rebind'],True,40).stdout)
    devices=info['cameras']
    if not devices:raise ValueError('未发现支持2560×720 MJPG的USB双目相机，请将相机连接RK。')
    if device is None:
        if len(devices)==1:device=devices[0]['device']
        else:
            for i,r in enumerate(devices,1):print(i,r['device'],r['name'])
            device=devices[int(input('选择相机编号：'))-1]['device']
    if device not in [d['device'] for d in devices]:raise ValueError('相机节点不在本次检测列表中。')
    print(f'相机 {device}；录制 {seconds} 秒；曝光 {exposure}。开始后按 Ctrl+C 可正常提前停录。',flush=True)
    remote_job(['sh',REMOTE+'/run_capture.sh',device,exposure,str(seconds)],'camera',cancellable=True)
    state=json.loads(shell(['cat',RESULT_ROOT+'/active-session.json'],True).stdout)
    if state['status']!='complete':raise ValueError('板端结果未完成：'+str(state))
    return retrieve(state['name'])
def replay_serve10(diagnostic=False):
    deploy();name=('diagnostic_serve10_' if diagnostic else 'serve10_')+now()
    script='diagnostic_recorded.sh' if diagnostic else 'run_recorded.sh'
    remote_job(['sh',REMOTE+'/'+script,name,'/root/pingpong-field-test-results/serve_10/input/manifest.json'],name,cancellable=True)
    return retrieve(name)
def video(path):
    deploy();path=Path(path).resolve()
    if not path.is_file():raise FileNotFoundError(path)
    name='video_'+now();inp=CASE_ROOT/'imported'/name;inp.parent.mkdir(parents=True,exist_ok=True)
    logged([str(BASE/'bin/pc/pipeline_cli.exe'),'--import-video',str(path),'--manifest',str(inp/'manifest.json')],log_path('import_'+name))
    manifest=read(inp/'manifest.json');manifest['provenance']={**manifest.get('provenance',{}),'video_path':str(path),'video_sha256':sha(path)}
    (inp/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    remote_input=REMOTE+'/inputs/'+name
    shell(['mkdir','-p',REMOTE+'/inputs'],True)
    logged(ADB+['push',str(inp),remote_input],log_path('send_'+name))
    remote_job(['sh',REMOTE+'/run_recorded.sh',name,remote_input+'/manifest.json'],name,cancellable=True)
    return retrieve(name)
def stop_capture():
    quiet()
    result=subprocess.run(ADB+['shell','python3 -B '+REMOTE+'/stop_capture.py'],capture_output=True)
    print((result.stdout+result.stderr).decode('utf-8','replace').strip())
