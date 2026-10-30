"""Upgrade only a known, intact quick runtime; preserve a rollback copy."""
from pathlib import Path
from datetime import datetime
import fcntl,hashlib,json,shutil,sys
STAGE=Path(__file__).resolve().parent
CORE={'build/motion7_chain_kinematic':'f33387986614e0a2b2c6a24e608ab5718087c21500fdb210dbd70421246e7735',
      'models/ball_640_int8.rknn':'3b01b325a9e3db893e12acedba21d1dae1653e93e2ba2d077d893ebd5afa5403',
      'models/unified_640_int8.rknn':'020ac622be55c6ce64816e86bc87e64ae827878906cae03c7ce7bd3ff9b16e69',
      'calibration.json':'3eb86f0c061a71c7f365d8668ab70ebac3c922a291a1ef2e511c7e679fdfdc51'}
ACCEPTED_PRIOR={'d85cae21823240cb7f6feb93a428b3898954bbcafe92418735eaffa767ff09fa'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def target(root,name):
    p=(root/name).resolve()
    if not p.is_relative_to(root.resolve()) or p==root.resolve():raise ValueError('Unsafe payload path: '+name)
    return p
def checked(root):
    data=json.loads((root/'payload-sha256.json').read_text())
    for row in data['files']:
        p=target(root,row['path'])
        if not p.is_file() or p.stat().st_size!=row['bytes'] or sha(p)!=row['sha256']:raise RuntimeError('Payload changed: '+str(p))
    for name,digest in CORE.items():
        if sha(target(root,name))!=digest:raise RuntimeError('Core configuration differs: '+name)
    return data
def update(root,stage=STAGE):
    root=Path(root).resolve();stage=Path(stage).resolve()
    new=checked(stage);old=checked(root)
    if old['version']!=new['version']:raise RuntimeError('Runtime profile differs; keep the existing version.')
    old_hash=sha(root/'payload-sha256.json');new_hash=sha(stage/'payload-sha256.json')
    if old_hash==new_hash:return {'updated':False,'payload_sha256':new_hash}
    if old_hash not in ACCEPTED_PRIOR:raise RuntimeError('Unknown prior payload. Existing files retained; use a separate new runtime.')
    backup=root/'maintenance'/('final-ui-timing-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True,exist_ok=False);changed=[]
    try:
        names=[r['path'] for r in new['files']]+['payload-sha256.json']
        for name in names:
            source=target(stage,name);dest=target(root,name)
            if dest.is_file() and sha(dest)==sha(source):continue
            existed=dest.exists()
            if existed:
                saved=target(backup,name);saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved)
            changed.append((name,existed));dest.parent.mkdir(parents=True,exist_ok=True)
            temp=dest.with_name(dest.name+'.final-update-tmp');shutil.copy2(source,temp);temp.replace(dest)
        checked(root)
        receipt={'updated':True,'prior_payload_sha256':old_hash,'payload_sha256':new_hash,'backup':str(backup),'changed':[n for n,_ in changed]}
        (backup/'update-receipt.json').write_text(json.dumps(receipt,indent=2));return receipt
    except BaseException:
        for name,existed in reversed(changed):
            dest=target(root,name)
            if existed:shutil.copy2(target(backup,name),dest)
            elif dest.is_file():dest.unlink()
        raise
if __name__=='__main__':
    with Path('/run/lock/pingpong-quick-field-3092.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(json.dumps(update(Path(sys.argv[1]))),flush=True)
