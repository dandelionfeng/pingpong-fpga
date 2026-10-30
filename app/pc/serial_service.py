"""Local GUI J3 service. Same baud/line levels and idle-prompt guard as the CMD."""
from pathlib import Path
from datetime import datetime
import codecs,collections,os,re,sys,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/python'))
import serial
from serial.tools import list_ports
ANSI=re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)')
PROMPT=re.compile(r'(?:^|[\r\n])(?:root|linaro)@[^\r\n]*[#$] $')
class SerialService:
    def __init__(self,base,remote):
        self.base=Path(base);self.remote=remote;self.channel=None;self.ready=False;self.stage='idle';self.error=None
        self.lock=threading.RLock();self.events=collections.deque(maxlen=1200);self.seq=0;self.stop_event=threading.Event();self.thread=None
    def ports(self):return [{'port':p.device,'name':p.description} for p in list_ports.comports()]
    def emit(self,text):
        with self.lock:self.seq+=1;self.events.append({'seq':self.seq,'text':text})
    def status(self,after=0):
        with self.lock:return {'connected':bool(self.channel and self.channel.is_open),'port':self.channel.port if self.channel else None,
            'ready':self.ready,'stage':self.stage,'error':self.error,'seq':self.seq,'events':[e for e in self.events if e['seq']>after]}
    def connect(self,port=None):
        with self.lock:
            if self.channel and self.channel.is_open:return self.status()
            candidates=[p for p in list_ports.comports() if p.vid==0x1a86]
            if not port:
                if len(candidates)!=1:raise ValueError('请选择RK J3串口。')
                port=candidates[0].device
            if not re.fullmatch(r'COM\d+',port,re.I):raise ValueError('串口名应为COM8这类格式。')
            c=serial.Serial(port=None,baudrate=1500000,timeout=.1,rtscts=False,dsrdtr=False);c.dtr=False;c.rts=False;c.port=port
            try:c.open()
            except serial.SerialException as e:raise ValueError(f'{port}无法打开。若旧CMD仍占用串口，请在旧窗口按Ctrl+]返回菜单。{e}')
            folder=self.base.parent/'logs/terminal';folder.mkdir(exist_ok=True,parents=True)
            self.log=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_')+port+'_gui.log')
            self.channel=c;self.ready=False;self.error=None;self.stage='shell';self.stop_event.clear()
            self.thread=threading.Thread(target=self.reader,daemon=True);self.thread.start();c.write(b'\r')
            self.emit('\n已连接 '+port+' · 1500000 / 8N1\n');return self.status()
    def reader(self):
        decoder=codecs.getincrementaldecoder('utf-8')(errors='replace');tail='';quiet_sent=False;marker_tail=''
        try:
            with self.log.open('ab') as log:
                while not self.stop_event.is_set():
                    data=self.channel.read(max(1,self.channel.in_waiting))
                    if not data:continue
                    log.write(data);log.flush();text=decoder.decode(data);clean=ANSI.sub('',text)
                    self.emit(clean.replace('\r\n','\n').replace('\r',''));tail=(tail+text)[-4096:]
                    scan=marker_tail+clean
                    markers={'CAPTURE_RUNNING':'capture','ANALYSIS_RUNNING':'analysis','MEASUREMENT_SAVED':'measurement','RECORDING_SAVED':'complete','FIELD_FAILED':'failed'}
                    consumed=0
                    for match in re.finditer('|'.join(markers),scan):self.stage=markers[match[0]];consumed=match.end()
                    marker_tail=scan[consumed:][-24:]
                    if PROMPT.search(ANSI.sub('',tail)):
                        with self.lock:
                            if not quiet_sent:
                                self.channel.write(b'dmesg -n 4; stty cols 110 rows 28\r');quiet_sent=True;self.ready=False
                            else:self.ready=True
        except Exception as e:
            if not self.stop_event.is_set():self.error=str(e);self.emit('\n串口连接中断：'+str(e)+'\n')
        finally:
            self.ready=False
            if self.channel:self.channel.close()
    def command(self,text):
        with self.lock:
            if not self.channel or not self.channel.is_open:raise ValueError('请先连接J3串口。')
            if not self.ready:raise ValueError('等待RK空闲Shell提示符；当前任务尚未结束。')
            if not isinstance(text,str) or len(text)>2048 or '\n' in text or '\r' in text:raise ValueError('每次发送一行命令。')
            self.ready=False;self.channel.write((text+'\r').encode('utf-8'));return {'sent':True}
    def capture(self,seconds=30):
        seconds=float(seconds)
        if not 0<seconds<=300:raise ValueError('录制时长须大于0且不超过300秒。')
        result=self.command(f'sh {self.remote}/run_capture.sh /dev/video73 auto {seconds:g}')
        self.stage='capture_starting';return result
    def interrupt(self):
        with self.lock:
            if not self.channel or not self.channel.is_open:raise ValueError('串口尚未连接。')
            if not self.ready:self.channel.write(b'\x03');self.emit('\n已请求正常提前停录；请等待RK保存和分析。\n')
            return {'sent':not self.ready}
    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(1)
        with self.lock:
            if self.channel:self.channel.close()
            self.channel=None;self.ready=False;self.stage='idle'
        return {'connected':False}
