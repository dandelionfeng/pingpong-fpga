"""Readiness checks for the isolated quick field runtime; never choose CPU silently."""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys
from runtime_paths import OpenCVPathError, environment_with_opencv, ROOT as REPO_ROOT
ROOT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text('utf-8'))
def quiet():subprocess.run(['dmesg','-n','4'],check=True)
def identity():
    manifest=read(ROOT/'payload-sha256.json')
    for r in manifest['files']:
        p=ROOT/r['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:
            raise RuntimeError('Runtime file changed or missing: '+str(p))
    return manifest['version']
def cameras():
    result=[]
    for entry in sorted(Path('/sys/class/video4linux').glob('video*'),key=lambda p:int(p.name[5:])):
        device=Path('/dev')/entry.name
        try:
            driver=(entry/'device/driver').resolve().name
            if driver!='uvcvideo':continue
            text=subprocess.run(['v4l2-ctl','-d',str(device),'--list-formats-ext'],capture_output=True,text=True,timeout=5)
            if text.returncode or "'MJPG'" not in text.stdout or not re.search(r'2560\s*x\s*720',text.stdout):continue
            result.append({'device':str(device),'name':(entry/'name').read_text().strip(),'format':'MJPG 2560x720','driver':driver})
        except (OSError,ValueError,subprocess.TimeoutExpired):continue
    return result
def fpga(rebind=False):
    nodes=[Path('/dev/ANLOGIC-PCI0_'+n) for n in ['user','h2c_0','c2h_0']]
    if not all(p.is_char_device() for p in nodes) and rebind:
        attempt=subprocess.run(['sh',str(ROOT/'rebind_pcie.sh'),str(ROOT/'dependencies/anlogic_pci.ko')],capture_output=True,text=True,timeout=25)
        (ROOT/'last-pcie-preflight.log').write_text(attempt.stdout+attempt.stderr,encoding='utf-8')
    return all(p.is_char_device() for p in nodes)
def check(require_fpga=False,require_camera=False,rebind=False):
    quiet();version=identity()
    try:
        opencv_lib_dir,env=environment_with_opencv(REPO_ROOT)
    except OpenCVPathError as error:
        raise RuntimeError(str(error)) from error
    linked=subprocess.run(['ldd',str(ROOT/'build/motion7_chain_kinematic')],capture_output=True,text=True,env=env)
    if linked.returncode or 'not found' in linked.stdout:raise RuntimeError('RK shared libraries unavailable; OpenCV lib dir='+str(opencv_lib_dir)+'; ldd='+linked.stdout)
    sys.path.insert(0,str(ROOT/'pydeps'))
    import cv2,numpy
    ready=fpga(rebind);devices=cameras()
    info={'version':version,'rk':True,'console_loglevel':Path('/proc/sys/kernel/printk').read_text().split()[0],
        'fpga_ready':ready,'cameras':devices,'python':sys.version.split()[0],'cv2':cv2.__version__,'numpy':numpy.__version__,
        'opencv_lib_dir':str(opencv_lib_dir),'ld_library_path':env['LD_LIBRARY_PATH'],
        'capture': 'original MJPEG then batch inference','models':'V6 ball + Unified V2 hand/racket, INT8 640',
        'result_root':read(ROOT/'version.json')['result_root']}
    if require_fpga and not ready:raise RuntimeError('FPGA PCIe is unavailable. Check power, PCIe and the original motion7 bitstream; see last-pcie-preflight.log. No CPU fallback was selected.')
    if require_camera and not devices:raise RuntimeError('No USB UVC camera supporting MJPG2560x720 was found. Connect the stereo camera to RK.')
    return info
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--require-fpga',action='store_true');p.add_argument('--require-camera',action='store_true');p.add_argument('--rebind',action='store_true');a=p.parse_args()
    try:print(json.dumps(check(a.require_fpga,a.require_camera,a.rebind),ensure_ascii=False))
    except Exception as e:print('PREFLIGHT_FAILED: '+str(e),file=sys.stderr);sys.exit(2)
