"""Windowed executable entry: resolve the installation from the EXE, then start the local UI."""
from pathlib import Path
import argparse,ctypes,json,os,re,socket,subprocess,sys,time,urllib.request,webbrowser
def installation_root():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text('utf-8-sig'))
def health(url,root):
    try:
        with urllib.request.urlopen(url+'/api/health',timeout=.5) as f:info=json.load(f)
        return info.get('app')=='stereo-serve-app' and Path(info.get('ui_root','')).resolve()==root
    except Exception:return False
def start_server(root,testing=False):
    root=root.resolve();python=root/'runtime/python/python.exe';server=root/'app/pc/gui_server.py'
    for p in [python,server,root/'app/ui/index.html',root/'release.json']:
        if not p.is_file():raise FileNotFoundError('缺少运行文件：'+str(p))
    logs=root/'logs';logs.mkdir(exist_ok=True)
    saved=logs/'gui-session.json'
    if not testing and saved.exists():
        prior=read(saved).get('url','')
        if re.fullmatch(r'http://127\.0\.0\.1:\d{4,5}',prior) and health(prior,root):return prior,None
    ports=range(18969,18980) if testing else range(8769,8782)
    for port in ports:
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',port));break
            except OSError:continue
    else:raise RuntimeError('本机工作台端口已被占用。')
    env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    with (logs/'application.log').open('ab') as log:
        process=subprocess.Popen([str(python),'-B',str(server),'--no-open','--port',str(port)],cwd=str(root),env=env,
            stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    url=f'http://127.0.0.1:{port}'
    for _ in range(150):
        if health(url,root):return url,process
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
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--report',type=Path);parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
    root=installation_root();report=args.report or root/'logs/launcher-check.json'
    try:
        if args.self_test:
            result=subprocess.run([str(root/'runtime/python/python.exe'),'-B',str(root/'app/pc/check_install.py')],capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace')[-3000:])
            installation=json.loads(result.stdout)
        url,process=start_server(root,args.self_test)
        if args.self_test:
            try:
                state=read_response(url+'/api/state');expected=set(installation['reference_case_names']);assert expected.issubset({c['name'] for c in state['cases']})
                assert state['release']['software_version']==read(root/'release.json')['software_version']
                video_ranges=0
                for case in state['cases']:
                    if case['name'] not in expected:continue
                    request=urllib.request.Request(url+'/replay/'+case['name']+'/recording.mp4',headers={'Range':'bytes=0-63'})
                    with urllib.request.urlopen(request,timeout=5) as response:assert response.status==206 and len(response.read())==64
                    video_ranges+=1
                report.parent.mkdir(parents=True,exist_ok=True)
                report.write_text(json.dumps({'passed':True,'root':str(root),'entry':sys.executable,'cases':len(state['cases']),'video_ranges':video_ranges,'installation':installation},ensure_ascii=False,indent=2),encoding='utf-8')
            finally:
                if process:stop_server(url);process.wait(timeout=8)
        elif not args.no_open:open_window(root,url)
        return 0
    except Exception as e:
        report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps({'passed':False,'error':str(e)},ensure_ascii=False,indent=2),encoding='utf-8')
        if not args.self_test:ctypes.windll.user32.MessageBoxW(None,str(e),'发球测量系统',0x10)
        return 2
if __name__=='__main__':sys.exit(main())
