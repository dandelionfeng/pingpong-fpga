"""Fixed seed test images and explicit box replay, never real stereo/model truth."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    p.add_argument('--pairs',type=int,default=8)
    a=p.parse_args()
    if not 1<=a.pairs<=10000: raise SystemExit('pairs must be 1..10000')
    root=Path(a.output).resolve()
    if (root/'manifest.json').exists(): raise SystemExit('choose a fresh fixture output')
    root.mkdir(parents=True,exist_ok=True)
    h,w=720,1280
    y,x=np.indices((h,w))
    frames=[];detections=[]
    for i in range(a.pairs):
        images=[]
        for e in range(2):
            image=((x//7+y//5+e*35)%190+20).astype(np.uint8)
            cx=200+(9*i%900)-e*22;cy=300-(4*i%240)
            image[(x-cx)**2+(y-cy)**2<=18**2]=240
            images.append(image)
            detections.append({'source_pair_id':i+1,'eye':'right' if e else 'left',
                               'model_version':'synthetic-box-replay-v1',
                               'boxes':[{'class':'ball','confidence':1.,'bbox':[cx-18,cy-18,37,37]}]})
        entry={'pair_id':i+1,'timestamp_ns':(i+1)*16000000,
               'eye_timestamp_ns':[(i+1)*16000000]*2,'camera_frame_id':[i+1]*2,
               'config_version':'a-int-v1','calibration_version':'unavailable',
               'model_version':'unavailable','time_source':'synthetic_16ms_fixture',
               'source':'synthetic_fixture'}
        if i==0:
            stride=5140
            raw=np.full((h,stride),0xA5,np.uint8)
            raw[:,:5120:2]=np.concatenate(images,axis=1)
            raw[:,1:5120:2]=128
            name='拼接_有行填充.yuy2';payload=raw.tobytes();(root/name).write_bytes(payload)
            entry.update(format='YUY2',width=2560,height=h,stride=stride,file=name,sha256=hashlib.sha256(payload).hexdigest())
        else:
            entry.update(format='GRAY8',width=w,height=h,stride=w+16)
            for e,eye in enumerate(('left','right')):
                raw=np.full((h,w+16),0xA5,np.uint8);raw[:,:w]=images[e]
                name=f'{i+1:04d}_{eye}_灰度.raw';payload=raw.tobytes();(root/name).write_bytes(payload)
                entry[eye+'_file']=name;entry[eye+'_sha256']=hashlib.sha256(payload).hexdigest()
        frames.append(entry)
    manifest={'schema_version':1,'mode':'file','geometry_status':'synthetic_not_metric_stereo',
              'generator_version':'a-fixture-v1','frames':frames}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'replay.json').write_text(json.dumps({'schema_version':1,'provenance':'synthetic_fixture_not_model',
                                             'detections':detections},indent=2),encoding='utf-8')
    print(json.dumps({'status':'generated','pairs':a.pairs,'manifest':str(root/'manifest.json')},ensure_ascii=False))


if __name__=='__main__':main()
