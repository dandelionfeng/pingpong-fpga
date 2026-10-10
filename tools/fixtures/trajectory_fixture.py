"""Independent two-camera projection fixtures. Truth is never a CLI input."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import cv2
import numpy as np


def dump(p, value):
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def cameras():
    k1 = np.array([[900.,0,640],[0,910,360],[0,0,1]])
    k2 = np.array([[895.,0,635],[0,902,363],[0,0,1]])
    d1 = np.array([-.04,.008,.001,-.001,0.])
    d2 = np.array([-.03,.005,-.001,.001,0.])
    r = cv2.Rodrigues(np.array([.01,-.02,.006]))[0]
    t = np.array([-.18,.002,.001])
    base = np.array([[1.,0,0],[0,0,-1],[0,1,0]])
    rcw = cv2.Rodrigues(np.array([.06,.03,-.02]))[0] @ base
    tcw = np.array([0.,.3,3.])
    r1,r2,p1,p2,*_ = cv2.stereoRectify(k1,d1,k2,d2,(1280,720),r,t,flags=cv2.CALIB_ZERO_DISPARITY,alpha=0)
    return dict(K1=k1,D1=d1,K2=k2,D2=d2,R=r,T=t.reshape(3,1),R1=r1,R2=r2,P1=p1,P2=p2,Rcw=rcw,tcw=tcw.reshape(3,1))


def project_point(w,c,eye):
    cam=c['Rcw']@np.array(w)+c['tcw'].ravel()
    if eye: cam=c['R']@cam+c['T'].ravel()
    return cv2.projectPoints(cam.reshape(1,3),np.zeros(3),np.zeros(3),c['K2' if eye else 'K1'],c['D2' if eye else 'D1'])[0].reshape(2)


def stamp(i,t):
    return dict(pair_id=str(i+100),sample_time_ns=str(round((1+t)*1e9)),mode_id='gray1280-search640',config_version='b-measure-v2-draft',calibration_version='synthetic-part3-v1')


def detection(s,label,center,near=True,delay=.02):
    x,y=center
    if not near: x-=110
    return dict(**s,eye='left',completed_time_ns=str(int(s['sample_time_ns'])+round(delay*1e9)),label=label,model_version='synthetic-semantic-replay-v1',box=[float(x-12),float(y-12),24.,24.],score=.95,visible=1)


def boards(inputs,c):
    folder=inputs/'boards';folder.mkdir(exist_ok=True)
    pairs=[];heldout=[];s=.025
    for i in range(16):
        rotation=cv2.Rodrigues(np.array([-.25+.043*i,.18*math.sin(i),.04*math.cos(i)]))[0]
        trans=np.array([-.14+.016*(i%5),-.075+.014*(i%4),.66+.045*(i%6)])
        images=[]
        for eye in range(2):
            img=np.full((720,1280),170,np.uint8)
            for y in range(-1,6):
                for x in range(-1,9):
                    pts=np.array([[x*s,y*s,0],[(x+1)*s,y*s,0],[(x+1)*s,(y+1)*s,0],[x*s,(y+1)*s,0]])
                    cam=pts@rotation.T+trans
                    if eye:cam=cam@c['R'].T+c['T'].ravel()
                    pixels=cv2.projectPoints(cam,np.zeros(3),np.zeros(3),c['K2' if eye else 'K1'],c['D2' if eye else 'D1'])[0].reshape(-1,2)
                    cv2.fillConvexPoly(img,np.round(pixels*16).astype(np.int32),30 if (x+y)%2 else 235,lineType=cv2.LINE_AA,shift=4)
            name=f'board_{i}_{eye}.png';cv2.imwrite(str(folder/name),img);images.append('boards/'+name)
        (pairs if i<12 else heldout).append(dict(left=images[0],right=images[1]))
    landmarks=[]
    for x in [-.3,0,.3]:
        for y in [.1,.5]:
            for z in [.2,.7]:
                w=[x,y,z];landmarks.append(dict(world_m=w,left_pixel=project_point(w,c,0).tolist()))
    dump(inputs/'board_manifest.json',dict(corners=[9,6],square_size=.025,unit='m',version='synthetic-board-estimate',pairs=pairs,world_landmarks=landmarks))
    dump(inputs/'board_heldout.json',dict(corners=[9,6],square_size=.025,unit='m',pairs=heldout))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args()
    root=Path(args.output);inputs=root/'inputs';truth=root/'truth';inputs.mkdir(parents=True,exist_ok=True);truth.mkdir(exist_ok=True)
    rng=np.random.default_rng(106007);c=cameras()
    f=cv2.FileStorage(str(inputs/'calibration.json'),cv2.FILE_STORAGE_WRITE|cv2.FILE_STORAGE_FORMAT_JSON)
    for key,value in dict(schema='b-calibration-v1-draft',version='synthetic-part3-v1',unit='m',provenance='project-generated nonzero pose/distortion; not real camera',width=1280,height=720,world_valid=1).items():f.write(key,value)
    for key,value in c.items():f.write(key,value)
    f.release()
    cases=[];truth_cases=[];g=9.80665
    def scenario(name,kind='normal',noise=0.,image=False,vz=2.5,vx=.2,z0=.8):
        frames=[];detections=[];expected=[];release=.1;contact=.70;held=kind=='cancelled'
        for i in range(56):
            t=i/60;dt=max(0,t-release)
            w=np.array([.1+vx*dt,.4+.1*dt,z0+vz*dt-.5*g*dt*dt]) if t>release and not held else np.array([.1,.4,z0])
            if t>contact and kind not in ['no_racket','no_contact','cancelled']:
                d=contact-release;at=np.array([.1+vx*d,.4+.1*d,z0+vz*d-.5*g*d*d]);w=at+np.array([1.6,1.,2.])* (t-contact)
            s=stamp(i,t);n=dict(**s,diameter_px=14.,sigma_px=.3)
            lp=project_point(w,c,0);rp=project_point(w,c,1)
            dropped=(kind=='occlusion' and 20<=i<=24) or (kind=='missing_release' and i in [6,7,8])
            if image:
                n['reference_valid']=int(i>0)
                if i>0:n['reference_id']=str(i+99)
                imgs={}
                for eye,p in enumerate([lp,rp]):
                    im=np.full((720,1280),25,np.uint8);cv2.circle(im,tuple(np.round(p).astype(int)),7,235,-1)
                    mask=np.zeros((360,640),np.uint8)
                    if i>0 and not (18<=i<=22):cv2.circle(mask,tuple(np.round((p-.5)/2).astype(int)),4,255,-1)
                    en='right' if eye else 'left';gn=f'{name}_{i}_{en}.png';mn=f'{name}_{i}_{en}_mask.png';cv2.imwrite(str(inputs/gn),im);cv2.imwrite(str(inputs/mn),mask);imgs[en]=gn;imgs[en+'_mask']=mn
                n['images']=imgs
            elif not dropped:
                n['left_pixel']=(lp+rng.normal(0,noise,2)).tolist();n['right_pixel']=(rp+rng.normal(0,noise,2)).tolist()
            if kind=='outlier' and i==15 and not image:n['left_pixel'][0]+=12;n['right_pixel'][0]+=12
            if kind=='epipolar' and i==15:n['right_pixel'][1]+=30
            if kind=='wrong_pair' and i==15:n['right_pair_id']='999'
            if kind=='wrong_version' and i==15:n['right_calibration_version']='stale'
            if kind=='time_jump' and i>=25:n['sample_time_ns']=str(int(n['sample_time_ns'])+1000000000)
            frames.append(n);expected.append(dict(pair_id=s['pair_id'],sample_time_ns=n['sample_time_ns'],world_m=w.tolist(),geometry_expected=not dropped and not (kind in ['epipolar','wrong_pair','wrong_version'] and i==15)))
            if kind!='no_hand':detections.append(detection(s,'hand',lp,near=held or t<=release,delay=.16 if kind=='delayed' else .02))
            if kind not in ['no_racket','no_contact','cancelled'] and 40<=i<=46:detections.append(detection(s,'racket',lp,True))
        if kind=='delayed':detections=detections[::-1]
        if kind=='expired_boxes':
            for d in detections:d['completed_time_ns']=str(int(d['source_sample_time_ns'])+1000000000) if 'source_sample_time_ns' in d else str(int(d['sample_time_ns'])+1000000000)
        cases.append(dict(name=name,mode='image_measurement_semantic_replay' if image else 'pixel_observation_semantic_replay',frames=frames,detections=detections))
        status='complete' if kind in ['normal','noisy','delayed','outlier','occlusion','epipolar','wrong_pair','wrong_version'] else 'cancelled' if held else 'unknown'
        truth_cases.append(dict(name=name,kind=kind,status=status,frames=expected,release_ns=str(round((1+release)*1e9)),contact_ns=str(round((1+contact)*1e9)),apex_ns=str(round((1+release+vz/g)*1e9)),height_m=vz*vz/(2*g),image=image,noise=noise))
    for i in range(5):scenario(f'clean_serve_{i}',vz=2.1+.16*i,vx=.12+.05*i,z0=.75+.03*i)
    for kind in ['no_hand','no_racket','no_contact','cancelled','missing_release','occlusion','outlier','epipolar','wrong_pair','wrong_version','time_jump','delayed','expired_boxes']:scenario(kind,kind)
    scenario('noisy_serve','noisy',noise=.08)
    scenario('image_apex_zero_mask',image=True)
    dump(inputs/'manifest.json',dict(schema='b-trajectory-input-v1-draft',calibration='calibration.json',cases=cases))
    dump(truth/'expected.json',dict(source='independent analytical world trajectories and two-camera projection; semantic boxes explicitly replay',seed=106007,cases=truth_cases))
    boards(inputs,c)
    files=[dict(path=p.relative_to(root).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for folder in [inputs,truth] for p in sorted(folder.rglob('*')) if p.is_file()]
    dump(root/'INPUT_SHA256.json',dict(source='project generated; no external videos/models',seed=106007,files=files))
    print(f'FIXTURE_CREATED cases={len(cases)} board_pairs=12')


if __name__=='__main__':main()
