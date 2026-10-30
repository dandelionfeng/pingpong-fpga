"""Reserve a fresh recording name and check space on its actual filesystem."""
from pathlib import Path
import argparse,fcntl,json,math,os,re,shutil,sys


def allocate(result_root,legacy_root,requested,seconds):
    result_root=Path(result_root).resolve();legacy_root=Path(legacy_root).resolve()
    if not math.isfinite(seconds) or not 0<seconds<=300:raise ValueError('Recording duration must be greater than 0 and at most 300 seconds')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',requested):raise ValueError('Use letters, numbers, _ or - for the recording name')
    result_root.mkdir(parents=True,exist_ok=True)
    free=shutil.disk_usage(result_root).free
    # Reserve room for original MJPEG, both FPGA passes, metadata and headroom.
    required=int(seconds*32*1024**2)+512*1024**2
    if free<required:raise ValueError(f'Insufficient recording space: {free/1024**3:.2f} GiB free, approximately {required/1024**3:.2f} GiB required. Free old test data or shorten this recording.')
    print(f'CAPTURE_STORAGE free={free/1024**3:.2f}GiB required={required/1024**3:.2f}GiB path={result_root}',file=sys.stderr)
    counter=result_root/'.serve-sequence'
    with counter.open('a+') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0)
        text=f.read().strip();last=int(text) if text.isdigit() else 0
        reservations=result_root/'.capture-reservations';reservations.mkdir(exist_ok=True)
        def taken(name):
            return (reservations/name).exists() or any((p/name).exists() or (p/(name+'_input')).exists() for p in {result_root,legacy_root})
        for parent in {result_root,legacy_root}:
            if not parent.is_dir():continue
            for child in parent.iterdir():
                match=re.fullmatch(r'serve_(\d+)(?:_input)?',child.name)
                if match:last=max(last,int(match[1]))
        if requested in ('auto','serve') or (re.fullmatch(r'serve_\d+',requested) and taken(requested)):
            last+=1;name=f'serve_{last:02d}'
            while taken(name):last+=1;name=f'serve_{last:02d}'
        else:
            name=requested;index=2
            while taken(name):name=f'{requested}_{index:02d}';index+=1
            match=re.fullmatch(r'serve_(\d+)',name)
            if match:last=max(last,int(match[1]))
        # Reserve before releasing the lock, including custom recording names.
        (reservations/name).write_text(json.dumps({'name':name,'seconds':seconds,'exposure_default':'auto'}))
        f.seek(0);f.truncate();f.write(str(last)+'\n');f.flush();os.fsync(f.fileno())
    return name


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('result_root',type=Path);p.add_argument('legacy_root',type=Path);p.add_argument('name');p.add_argument('seconds',type=float);a=p.parse_args()
    try:print(allocate(a.result_root,a.legacy_root,a.name,a.seconds))
    except (OSError,ValueError) as error:print('CAPTURE_PREFLIGHT_FAILED:',error,file=sys.stderr);sys.exit(2)
