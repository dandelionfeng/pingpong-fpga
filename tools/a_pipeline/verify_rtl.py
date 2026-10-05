"""Independent NumPy convolution oracle -> actual Icarus valid/ready/DDR tests."""
from pathlib import Path
import argparse, json, hashlib, subprocess, time
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
def gaussian(image):
    padded=np.pad(image.astype(np.uint16),1,mode='edge')
    h,w=image.shape
    weights=((1,2,1),(2,4,2),(1,2,1))
    total=np.zeros((h,w),np.uint16)
    for dy in range(3):
        for dx in range(3): total+=weights[dy][dx]*padded[dy:dy+h,dx:dx+w]
    return ((total+8)//16).astype(np.uint8)
def morphology(image,dilate):
    p=np.pad(image!=0,1,mode='edge');h,w=image.shape
    windows=[p[y:y+h,x:x+w] for y in range(3) for x in range(3)]
    return (np.logical_or.reduce(windows) if dilate else np.logical_and.reduce(windows)).astype(np.uint8)*255
def make_cases(folder,manifest=None):
    folder.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(98123);width,height=(640,360) if manifest else (16,12)
    previous=[None,None];reference=[0,0];config=1;lines=[];hashes=[]
    def add(eye,pid,image,commit=1,limit=None,version=1,reset=0):
        nonlocal previous,reference,config
        if reset or version!=config:previous=[None,None];reference=[0,0]
        config=version;g=gaussian(image);valid=previous[eye] is not None
        d=np.abs(g.astype(np.int16)-previous[eye].astype(np.int16)).astype(np.uint8) if valid else np.zeros_like(g)
        t=(d>12).astype(np.uint8)*255
        vec=np.stack([image,g,d,t],axis=-1).tobytes();name=f'case-{len(lines):04d}.bin';(folder/name).write_bytes(vec)
        lines.append(f'{eye} {pid} {int(valid)} {reference[eye]} {commit} {width*height if limit is None else limit} {version} {reset} {name}\n')
        hashes.append(hashlib.sha256(vec).hexdigest())
        if commit and (limit is None or limit==width*height):previous[eye]=g;reference[eye]=pid
    if manifest:
        data=json.loads(Path(manifest).read_text(encoding='utf-8'))
        for entry in data['frames']:
            raw=np.frombuffer(Path(entry['file']).read_bytes(),np.uint8).reshape(720,entry['stride'])[:,:5120:2]
            for eye in range(2):
                im=raw[:,eye*1280:(eye+1)*1280].astype(np.uint16)
                search=((im[::2,::2]+im[::2,1::2]+im[1::2,::2]+im[1::2,1::2]+2)//4).astype(np.uint8)
                add(eye,entry['pair_id'],search)
    else:
        for pid in range(1,8):
            for eye in range(2):add(eye,pid,rng.integers(0,256,(height,width),dtype=np.uint8))
        add(0,8,np.full((height,width),11,np.uint8),commit=0)
        add(1,8,np.full((height,width),12,np.uint8))
        add(0,9,np.full((height,width),13,np.uint8))
        add(0,10,np.full((height,width),255,np.uint8),commit=0,limit=width+7)
        add(0,11,np.full((height,width),26,np.uint8))
        add(1,9,np.zeros((height,width),np.uint8),version=2)
        add(0,12,np.full((height,width),255,np.uint8),version=2)
        add(0,13,np.full((height,width),244,np.uint8),version=2)
        add(0,14,np.full((height,width),232,np.uint8),version=2)
        add(0,15,np.full((height,width),219,np.uint8),version=2)
        add(1,10,np.full((height,width),255,np.uint8),version=2,reset=1)
    (folder/'cases.txt').write_text(''.join(lines),encoding='ascii')
    return width,height,hashes
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest');parser.add_argument('--output',required=True);parser.add_argument('--waves',action='store_true');args=parser.parse_args()
    out=Path(args.output).resolve();w,h,hashes=make_cases(out,args.manifest)
    iv=ROOT/'.tools/iverilog/app/bin/iverilog.exe';vvp=iv.with_name('vvp.exe')
    command=[str(iv),'-g2012','-s','tb_motion_front3',f'-Ptb_motion_front3.W={w}',f'-Ptb_motion_front3.H={h}','-o',str(out/'test.vvp'),str(ROOT/'fpga/rtl/a_motion/gaussian_stream.v'),str(ROOT/'fpga/rtl/a_motion/motion_front3.v'),str(ROOT/'fpga/sim/a_motion/tb_motion_front3.sv')]
    subprocess.run(command,check=True,stdout=(out/'compile.log').open('w'),stderr=subprocess.STDOUT)
    run=[str(vvp),str(out/'test.vvp'),f'+ROOT={out.as_posix()}']
    if args.waves:run.append(f'+WAVE={(out/"small.vcd").as_posix()}')
    start=time.time()
    with (out/'simulation.log').open('w') as log:result=subprocess.run(run,stdout=log,stderr=subprocess.STDOUT)
    text=(out/'simulation.log').read_text();passed=result.returncode==0 and 'PASS cases=' in text
    report={'status':'passed' if passed else 'failed','cases':len(hashes),'width':w,'height':h,'case_sha256':hashes,'command':command,'run_command':run,'elapsed_seconds':time.time()-start,'simulation_result':text[-2000:],'source_sha256':{str(Path(p).relative_to(ROOT)):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in command[-3:]},'hardware':'not_executed'}
    (out/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('case_sha256','source_sha256','command','run_command')},indent=2))
    if not passed:raise SystemExit(1)
if __name__=='__main__':main()
