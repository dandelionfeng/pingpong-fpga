from pathlib import Path
from datetime import datetime,timezone
import argparse,subprocess,tarfile
BASE=Path(__file__).resolve().parents[1];ADB=BASE/'tools/adb/adb.exe';SERIAL='2342f1aa3c720c76';REMOTE='/userdata/pingpong-field-test'
def main():
    p=argparse.ArgumentParser();p.add_argument('--package-only',action='store_true');a=p.parse_args()
    if not a.package_only:subprocess.run([str(ADB),'-s',SERIAL,'get-state'],check=True)
    bundle=BASE/'rk/field-test.tar.gz'
    with tarfile.open(bundle,'w:gz') as z:
        for p in (BASE/'rk').iterdir():
            if p.name=='bundle':
                for child in p.iterdir():z.add(child,arcname=child.name)
            elif p.name not in ('field-test.tar.gz',):z.add(p,arcname=p.name)
        for p in (BASE/'models').glob('*.rknn'):z.add(p,arcname='models/'+p.name)
        for p in (BASE/'models/int8-experiment-20261027').glob('*.rknn'):
            z.add(p,arcname='models/int8-experiment-20261027/'+p.name)
        for folder,patterns in [('pc',('*.py','player.html')),('algorithms',('*.py',))]:
            for pattern in patterns:
                for p in (BASE/folder).glob(pattern):z.add(p,arcname=folder+'/'+p.name)
        for p in (BASE/'tools/rk-wheels').glob('*.whl'):z.add(p,arcname='rk-wheels/'+p.name)
    if a.package_only:print('PACKAGE',bundle);return
    cmd=[str(ADB),'-s',SERIAL]
    subprocess.run(cmd+['shell','mkdir -p '+REMOTE],check=True)
    subprocess.run(cmd+['push',str(bundle),REMOTE+'/field-test.tar.gz'],check=True)
    board_time=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    subprocess.run(cmd+['shell',"date -u -s '"+board_time+"'"],check=True)
    subprocess.run(cmd+['shell',f'cd {REMOTE} && tar -xzmf field-test.tar.gz && python3 install_python_runtime.py && sh build_board.sh {REMOTE}'],check=True)
    print('Deployed sources. Board build output is under',REMOTE+'/build')
if __name__=='__main__':main()
