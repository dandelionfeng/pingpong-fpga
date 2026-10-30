"""Offline local-only graphical workbench; no account, remote service or upload."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import argparse,contextlib,json,mimetypes,os,re,secrets,subprocess,sys,threading,time,traceback,urllib.parse,webbrowser
REVISION=Path(__file__).resolve().parents[2]
BACKEND=REVISION/'app'
sys.path.insert(0,str(BACKEND/'pc'))
import field_actions as actions
from quick_common import BASE,VERSION,REMOTE,ADB,read,log_path,CASE_ROOT
from timing_report import describe_timing
from serial_service import SerialService
UI=BASE/'ui';TOKEN=secrets.token_hex(24);SERIAL=SerialService(BASE,REMOTE)
JOB={'running':False,'action':None,'message':'准备就绪','error':None};JOB_LOCK=threading.Lock()
def optional(p):
    try:return read(p)
    except (OSError,ValueError):return {}
def catalog():
    result=[]
    for case in (CASE_ROOT).glob('*'):
        if not case.is_dir() or not (case/'measurement-complete.json').exists():continue
        s=optional(case/'summary.json');m=optional(case/'motion-current/latest-release.json');c=optional(case/'measurement-complete.json')
        estimated=c.get('measurement_estimated',False)
        kind='valid' if c.get('release_valid') and c.get('fit_valid') and not estimated else 'estimated' if estimated else 'no_fit'
        stamp=(case/'measurement-complete.json').stat()
        result.append({'name':case.name,'created':datetime.fromtimestamp(stamp.st_mtime,timezone(timedelta(hours=8))).strftime('%m-%d %H:%M'),
            'order':stamp.st_mtime_ns,'kind':kind,'pairs':s.get('pairs',0),'height_cm':m.get('height_cm'),'angle_deg':m.get('angle_deg'),
            'rate':s.get('main_pairs_per_second'),'timing':describe_timing(case),'has_replay':(case/'replay/index.html').exists(),
            'poster':'/replay/'+urllib.parse.quote(case.name)+'/poster.jpg' if (case/'replay/poster.jpg').exists() else None})
    return sorted(result,key=lambda x:x['order'],reverse=True)
def run_action(action,args):
    if action=='connect':return SERIAL.connect(args.get('port'))
    if action=='disconnect':return SERIAL.close()
    if action=='capture':return SERIAL.capture(args.get('seconds',30))
    if action=='interrupt':return SERIAL.interrupt()
    if action=='command':return SERIAL.command(args.get('text',''))
    if action=='latest':return {'case':actions.latest_path().parents[1].name}
    if action=='folder':os.startfile(CASE_ROOT);return {'opened':True}
    if action=='manual':webbrowser.open((UI/'操作说明.html').as_uri());return {'opened':True}
    if action=='legacy':webbrowser.open((UI/'操作说明.html').as_uri());return {'opened':True}
    if action=='bitwriter':
        tool=Path('C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/bw.exe')
        if not tool.exists():raise ValueError('未找到BitWriter，请使用已安装的TD工具。')
        os.startfile(BASE/'fpga');subprocess.Popen([str(tool)],cwd=str(tool.parent));return {'opened':True}
    if action=='archive':os.startfile(REVISION/'manifests');return {'opened':True}
    if action in ['deploy','retrieve','rebuild']:
        if JOB['running']:raise ValueError('上一项操作尚未完成。')
        serial_state=SERIAL.status()
        if serial_state['connected'] and not serial_state['ready'] and action=='deploy':raise ValueError('等待RK空闲Shell提示符后再部署。')
        name=args.get('name','')
        if action!='deploy' and not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('请输入正确的RK结果名，例如serve_16。')
        def work():
            path=log_path('gui_'+action)
            try:
                with path.open('a',encoding='utf-8') as f,contextlib.redirect_stdout(f),contextlib.redirect_stderr(f):
                    if action=='deploy':
                        info=actions.status();message='设备检查完成：'+('FPGA就绪' if info.get('fpga_ready') else 'FPGA未枚举')
                    elif action=='rebuild':actions.rebuild_local(name);message='回放已就绪：'+name
                    else:actions.retrieve(name);message='回放已就绪：'+name
                JOB.update(running=False,message=message,error=None,log=str(path))
            except Exception as e:JOB.update(running=False,message='操作未完成',error=str(e),log=str(path))
        JOB.update(running=True,action=action,message={'deploy':'正在通过J4检查与部署','retrieve':'正在取回并生成回放','rebuild':'正在重建回放'}[action],error=None)
        threading.Thread(target=work,daemon=True).start();return {'started':True}
    raise ValueError('未知操作。')
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def valid_host(self):
        return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']
    def send_json(self,value,status=200):
        b=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.end_headers()
        try:self.wfile.write(b)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def do_GET(self):
        if not self.valid_host():self.send_json({'error':'仅允许本机访问'},403);return
        route=urllib.parse.urlsplit(self.path);path=urllib.parse.unquote(route.path)
        if path=='/api/state':
            cases=catalog();self.send_json({'version':VERSION,'release':optional(REVISION/'release.json'),'cases':cases,'serial':{k:v for k,v in SERIAL.status().items() if k!='events'},'ports':SERIAL.ports(),'job':dict(JOB)});return
        if path=='/api/serial':
            after=int(urllib.parse.parse_qs(route.query).get('after',['0'])[0]);self.send_json(SERIAL.status(after));return
        if path=='/api/health':self.send_json({'app':'stereo-serve-app','pid':os.getpid(),'base':str(BASE),'ui_root':str(REVISION),'version':optional(REVISION/'release.json')['version']});return
        if path in ['/','/index.html']:
            b=(UI/'index.html').read_text('utf-8').replace('__FIELD_TOKEN__',TOKEN).encode('utf-8');self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        if path.startswith('/replay/'):
            parts=path.split('/');case=parts[2] if len(parts)>2 else ''
            if not re.fullmatch(r'[A-Za-z0-9_-]+',case):self.send_error(404);return
            root=(CASE_ROOT/case/'replay').resolve();target=(root/('/'.join(parts[3:]) or 'index.html')).resolve()
            if not target.is_relative_to(root):self.send_error(403);return
            if target.name=='index.html' and target.is_file():target=UI/'player.html'
        else:
            target=(UI/path.lstrip('/')).resolve()
            if not target.is_relative_to(UI.resolve()):self.send_error(403);return
        if not target.is_file():self.send_error(404);return
        size=target.stat().st_size;begin,end=0,size-1;range_=self.headers.get('Range','');match=re.fullmatch(r'bytes=(\d+)-(\d*)',range_)
        if match:begin=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
        if begin>end or begin>=size:self.send_error(416);return
        self.send_response(206 if match else 200);self.send_header('Content-Type',mimetypes.guess_type(target.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(end-begin+1));self.send_header('Accept-Ranges','bytes')
        if match:self.send_header('Content-Range',f'bytes {begin}-{end}/{size}')
        self.end_headers()
        with target.open('rb') as f:
            f.seek(begin);remaining=end-begin+1
            while remaining:
                b=f.read(min(65536,remaining))
                if not b:break
                try:self.wfile.write(b)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):break
                remaining-=len(b)
    def do_POST(self):
        if not self.valid_host():self.send_json({'error':'仅允许本机访问'},403);return
        if self.headers.get('X-Field-Token')!=TOKEN:self.send_json({'error':'无效的本机会话令牌'},403);return
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{self.headers.get("Host")}':self.send_json({'error':'不允许跨站操作'},403);return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<8192:raise ValueError('请求大小不正确。')
            value=json.loads(self.rfile.read(size))
            if value.get('action')=='shutdown':
                if JOB['running'] or SERIAL.status()['stage'] in ['capture_starting','capture','analysis','measurement']:raise ValueError('请等待当前采集或处理完成后退出。')
                self.send_json({'stopped':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            with JOB_LOCK:result=run_action(value['action'],value.get('args',{}))
            self.send_json(result)
        except Exception as e:self.send_json({'error':str(e)},400)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-open',action='store_true');parser.add_argument('--port',type=int,default=8769);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);url=f'http://127.0.0.1:{server.server_port}'
    state=REVISION/'logs/gui-session.json';state.parent.mkdir(exist_ok=True,parents=True);state.write_text(json.dumps({'url':url,'pid':os.getpid()}),encoding='utf-8')
    print('FIELD_GUI '+url,flush=True)
    if not args.no_open:webbrowser.open(url)
    try:server.serve_forever()
    finally:SERIAL.close();server.server_close()
if __name__=='__main__':main()
