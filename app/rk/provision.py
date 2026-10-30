from pathlib import Path
import hashlib,json,os,platform,stat,subprocess,sys,zipfile
ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'payload-sha256.json').read_text())
assert platform.machine()=='aarch64' and sys.version_info[:2]==(3,11),'Use the validated RK Python3.11 image'
for item in manifest['files']:
    p=ROOT/item['path'];assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'],str(p)
target=ROOT/'pydeps';target.mkdir(exist_ok=True)
for wheel in sorted((ROOT/'wheels').glob('*.whl')):
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            dest=(target/info.filename).resolve()
            assert dest.is_relative_to(target.resolve()),info.filename
            z.extract(info,target)
            mode=info.external_attr>>16
            if mode & stat.S_IXUSR and dest.is_file():dest.chmod(0o755)
(ROOT/'build/motion7_chain_kinematic').chmod(0o755)
sys.path.insert(0,str(target));import cv2,numpy
subprocess.run(['dmesg','-n','4'],check=True)
(ROOT/'deployment-receipt.json').write_text(json.dumps({'version':manifest['version'],'machine':platform.machine(),
    'kernel':platform.release(),'python':sys.version,'cv2':cv2.__version__,'numpy':numpy.__version__,
    'source':'exact validated30.92 executable and same640 INT8 models; no C++ rebuild',
    'console_loglevel':Path('/proc/sys/kernel/printk').read_text().split()[0]},indent=2))
print('QUICK_FIELD_DEPENDENCIES_READY')
