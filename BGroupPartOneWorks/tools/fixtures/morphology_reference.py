from pathlib import Path
import json
import numpy as np
import cv2

W,H=8,6
src=np.zeros((H,W),np.uint8)
src[1:5,1:5]=1; src[0,7]=1
def morph(a, mode):
    out=np.zeros_like(a)
    for y in range(H):
        for x in range(W):
            yy=np.clip(np.arange(y-1,y+2),0,H-1); xx=np.clip(np.arange(x-1,x+2),0,W-1)
            q=a[np.ix_(yy,xx)]; out[y,x]=q.min() if mode=='erode' else q.max()
    return out
stages=[src]
for mode in ['erode','dilate','dilate','erode']:
    stages.append(morph(stages[-1],mode))
flat=stages[-1].reshape(-1); packed=[sum(int(flat[i+b])<<b for b in range(8)) for i in range(0,W*H,8)]
out=Path(__file__).resolve().parents[2]/'fpga/sim/morphology/golden';out.mkdir(parents=True,exist_ok=True)
for n,a in zip(['input','erode1','dilate1','dilate2','erode2'],stages):cv2.imwrite(str(out/f'{n}.png'),a*255)
(out/'expected.json').write_text(json.dumps({'width':W,'height':H,'bytes':packed,'stages':[a.reshape(-1).tolist() for a in stages]},indent=2),encoding='utf-8')
print(json.dumps({'bytes':packed,'final_pixels':stages[-1].reshape(-1).tolist()}))
