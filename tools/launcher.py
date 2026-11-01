"""Windowed executable entry for both source and complete packages."""
from pathlib import Path
import argparse,ctypes,hashlib,json,os,re,runpy,socket,subprocess,sys,time,urllib.request,webbrowser
def installation_root():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text('utf-8-sig'))
def runtime_mode(root):
    return 'complete' if (Path(root)/'runtime/python/python.exe').is_file() else 'source-embedded'
def source_installation(root):
    root=Path(root).resolve()
    required=[root/'app/pc/gui_server.py',root/'app/ui/index.html',root/'app/ui/application.ico',
              root/'app/version.json',root/'data/index.json',root/'release.json']
    missing=[str(p) for p in required if not p.is_file()]
    if missing:raise FileNotFoundError('源码包缺少运行文件：'+'；'.join(missing))
    release=read(root/'release.json');version=read(root/'app/version.json');index=read(root/'data/index.json')
    if release['runtime_profile']!=version['version']:raise RuntimeError('release.json 与 app/version.json 的运行配置不一致。')
    return {'mode':'source-embedded','reference_case_names':[r['case'] for r in index['renumbering']],
        'recordings_included':sum(1 for p in (root/'data').iterdir() if p.is_dir() and (p/'measurement-complete.json').is_file()),
        'configuration_sha256':hashlib.sha256((root/'app/version.json').read_bytes()).hexdigest(),
        'full_runtime_present':False}
def run_embedded_server(root,arguments):
    root=Path(root).resolve();server=root/'app/pc/gui_server.py'
    if not server.is_file():raise FileNotFoundError('缺少运行文件：'+str(server))
    sys.path.insert(0,str(server.parent));os.environ['FIELD_INSTALL_ROOT']=str(root)
    sys.argv=[str(server),*arguments]
    runpy.run_path(str(server),run_name='__main__')
    return 0
def health(url,root):
    try:
        with urllib.request.urlopen(url+'/api/health',timeout=.5) as f:info=json.load(f)
        return info.get('app')=='stereo-serve-app' and Path(info.get('ui_root','')).resolve()==root
    except Exception:return False
def start_server(root,testing=False):
    root=root.resolve();python=root/'runtime/python/python.exe';server=root/'app/pc/gui_server.py';mode=runtime_mode(root)
    required=[server,root/'app/ui/index.html',root/'release.json']
    if mode=='complete':required.insert(0,python)
    else:required.extend([root/'app/version.json',root/'data/index.json'])
    for p in required:
        if not p.is_file():raise FileNotFoundError('缺少运行文件：'+str(p))
    logs=root/'logs';logs.mkdir(exist_ok=True)
    saved=logs/'gui-session.json'
    if not testing and saved.exists():
        prior=read(saved).get('url','')
        if re.fullmatch(r'http://127\.0\.0\.1:\d{4,5}',prior) and health(prior,root):return prior,None,mode
    ports=range(18969,18980) if testing else range(8769,8782)
    for port in ports:
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',port));break
            except OSError:continue
    else:raise RuntimeError('本机工作台端口已被占用。')
    env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',FIELD_INSTALL_ROOT=str(root))
    if mode=='source-embedded' and getattr(sys,'frozen',False):env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    command=[str(python),'-B',str(server),'--no-open','--port',str(port)] if mode=='complete' else (
        [sys.executable,'--embedded-server','--no-open','--port',str(port)] if getattr(sys,'frozen',False)
        else [sys.executable,'-B',str(server),'--no-open','--port',str(port)])
    with (logs/'application.log').open('ab') as log:
        process=subprocess.Popen(command,cwd=str(root),env=env,
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    url=f'http://127.0.0.1:{port}'
    for _ in range(150):
        if health(url,root):return url,process,mode
        if process.poll() is not None:raise RuntimeError('工作台启动失败，日志：'+str(logs/'application.log'))
        time.sleep(.1)
    raise RuntimeError('工作台启动超时，日志：'+str(logs/'application.log'))
def stop_server(url):
    html=urllib.request.urlopen(url,timeout=5).read().decode();token=re.search(r'name="field-token" content="([^"]+)"',html)[1]
    request=urllib.request.Request(url+'/api/action',data=b'{"action":"shutdown"}',headers={'Content-Type':'application/json','X-Field-Token':token})
    return read_response(request)
def read_response(request):
    with urllib.request.urlopen(request,timeout=10) as f:return json.load(f)
def open_window(root,url):
    candidates=[Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
                Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe']
    edge=next((p for p in candidates if p.is_file()),None)
    if edge:
        from window_icon import owned_windows,retain_window_icon
        previous=owned_windows(edge)
        subprocess.Popen([str(edge),'--app='+url,'--window-size=1440,1040'])
        retain_window_icon(root,edge,previous)
    else:webbrowser.open(url)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--report',type=Path);parser.add_argument('--no-open',action='store_true')
    parser.add_argument('--embedded-server',action='store_true',help=argparse.SUPPRESS);args,extra=parser.parse_known_args()
    root=installation_root()
    if args.embedded_server:return run_embedded_server(root,extra)
    if extra:parser.error('无法识别的参数：'+' '.join(extra))
    report=args.report or root/'logs/launcher-check.json'
    try:
        if args.self_test:
            if runtime_mode(root)=='complete':
                result=subprocess.run([str(root/'runtime/python/python.exe'),'-B',str(root/'app/pc/check_install.py')],capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace')[-3000:])
                installation=json.loads(result.stdout)
            else:installation=source_installation(root)
        url,process,mode=start_server(root,args.self_test)
        if args.self_test:
            try:
                state=read_response(url+'/api/state');expected=set(installation['reference_case_names'])
                if mode=='complete':assert expected.issubset({c['name'] for c in state['cases']})
                assert state['release']['software_version']==read(root/'release.json')['software_version']
                with urllib.request.urlopen(url+'/',timeout=5) as response:assert response.status==200 and '发球测量系统' in response.read().decode('utf-8')
                video_ranges=0
                if mode=='complete':
                    for case in state['cases']:
                        if case['name'] not in expected:continue
                        request=urllib.request.Request(url+'/replay/'+case['name']+'/recording.mp4',headers={'Range':'bytes=0-63'})
                        with urllib.request.urlopen(request,timeout=5) as response:assert response.status==206 and len(response.read())==64
                        video_ranges+=1
                report.parent.mkdir(parents=True,exist_ok=True)
                report.write_text(json.dumps({'passed':True,'mode':mode,'root':str(root),'entry':sys.executable,
                    'cases':len(state['cases']),'video_ranges':video_ranges,'installation':installation},ensure_ascii=False,indent=2),encoding='utf-8')
            finally:
                if process:stop_server(url);process.wait(timeout=8)
        elif not args.no_open:open_window(root,url)
        return 0
    except Exception as e:
        report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps({'passed':False,'error':str(e)},ensure_ascii=False,indent=2),encoding='utf-8')
        if not args.self_test:ctypes.windll.user32.MessageBoxW(None,str(e),'发球测量系统',0x10)
        return 2
if __name__=='__main__':sys.exit(main())
