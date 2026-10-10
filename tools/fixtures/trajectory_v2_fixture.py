"""Expanded B regression: independent projection/raster, explicit replay semantics.

No true world coordinates or event times are written to algorithm input.
Masks are declared synthetic hints, not A/FPGA seven-stage outputs.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import cv2
import numpy as np
from trajectory_fixture import cameras, project_point, stamp, detection, dump


def save_camera(path, c, version):
    f=cv2.FileStorage(str(path),cv2.FILE_STORAGE_WRITE|cv2.FILE_STORAGE_FORMAT_JSON)
    for key,value in dict(schema='b-calibration-v1-draft',version=version,unit='m',provenance='project-generated stereo projection; not real camera',width=1280,height=720,world_valid=1).items():f.write(key,value)
    for key,value in c.items():f.write(key,value)
    f.release()


def render(center, radius=10, blur=0, noise=0, rng=None, distractor=None):
    image=np.full((720,1280),25,np.uint8)
    # Supersample only the local patch: fractional centers are not rounded to
    # integer image pixels before rendering and truth keeps the original point.
    def disk(p):
        x0=int(math.floor(p[0]))-20;y0=int(math.floor(p[1]))-20
        xs=x0+(np.arange(40*8)+.5)/8-.5;ys=y0+(np.arange(40*8)+.5)/8-.5
        patch=np.where((xs[None,:]-p[0])**2+(ys[:,None]-p[1])**2<=radius**2,235,25).astype(np.uint8)
        patch=cv2.resize(patch,(40,40),interpolation=cv2.INTER_AREA)
        if 0<=x0<=1240 and 0<=y0<=680:image[y0:y0+40,x0:x0+40]=patch
    disk(center)
    if distractor is not None:disk(distractor)
    if blur:image=cv2.GaussianBlur(image,(0,0),blur,borderType=cv2.BORDER_REPLICATE)
    if noise:
        x,y=np.round(center).astype(int);x0=max(0,x-24);x1=min(1280,x+24);y0=max(0,y-24);y1=min(720,y+24)
        patch=image[y0:y1,x0:x1];image[y0:y1,x0:x1]=np.clip(patch.astype(float)+rng.normal(0,noise,patch.shape),0,255).astype(np.uint8)
    return image


def broad_boards(inputs,c):
    """Cover image field and target depth with a declared metric board.

    This is still a generated practice board, not physical calibration.
    """
    rng=np.random.default_rng(106009);side=.055;pattern=[9,6];pairs=[];heldout=[];folder=inputs/'boards_broad';folder.mkdir(exist_ok=True)
    for i in range(36):
        angle=np.array([rng.uniform(-.4,.4),rng.uniform(-.4,.4),rng.uniform(-.2,.2)])
        rot=cv2.Rodrigues(angle)[0];depth=[1.,1.4,2.,2.6,3.4,3.8][i%6]
        trans=np.array([rng.uniform(-.5,.3),rng.uniform(-.4,.2),depth]);names=[]
        for eye in range(2):
            im=np.full((720,1280),170,np.uint8)
            for y in range(-1,6):
                for x in range(-1,9):
                    pts=np.array([[x*side,y*side,0],[(x+1)*side,y*side,0],[(x+1)*side,(y+1)*side,0],[x*side,(y+1)*side,0]])@rot.T+trans
                    if eye:pts=pts@c['R'].T+c['T'].ravel()
                    pixels=cv2.projectPoints(pts,np.zeros(3),np.zeros(3),c['K2' if eye else 'K1'],c['D2' if eye else 'D1'])[0].reshape(-1,2)
                    cv2.fillConvexPoly(im,np.round(pixels*256).astype(np.int32),30 if (x+y)%2 else 235,lineType=cv2.LINE_AA,shift=8)
            name=f'board_{i}_{eye}.png';cv2.imwrite(str(folder/name),im);names.append('boards_broad/'+name)
        (pairs if i<30 else heldout).append(dict(left=names[0],right=names[1]))
    old=json.loads((inputs/'board_manifest.json').read_text());meta=dict(corners=pattern,square_size=side,unit='m',version='synthetic-board-broad-estimate',pairs=pairs,world_landmarks=old['world_landmarks']);dump(inputs/'board_broad_manifest.json',meta);dump(inputs/'board_broad_heldout.json',dict(corners=pattern,square_size=side,unit='m',pairs=heldout))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);args=ap.parse_args();root=Path(args.output)
    subprocess.run([sys.executable,str(Path(__file__).with_name('trajectory_fixture.py')),'--output',str(root)],check=True)
    inputs=root/'inputs';truth_dir=root/'truth';manifest=json.loads((inputs/'manifest.json').read_text());truth=json.loads((truth_dir/'expected.json').read_text());base=cameras();rng=np.random.default_rng(106008);g=9.80665
    def scenario(name,kind='normal',image=False,vz=2.5,vx=.2,z0=.8,delay=.02,noise=0,baseline=.18,distance=3.,blur=0,occlusion=0):
        c={k:v.copy() for k,v in base.items()};c['T'][0,0]=-baseline;c['tcw'][2,0]=distance
        c['R1'],c['R2'],c['P1'],c['P2'],*_ = cv2.stereoRectify(c['K1'],c['D1'],c['K2'],c['D2'],(1280,720),c['R'],c['T'],flags=cv2.CALIB_ZERO_DISPARITY,alpha=0)
        version='synthetic-'+name;config='calibration_'+name+'.json';save_camera(inputs/config,c,version)
        frames=[];expected=[];sem=[];release=.1;contact=.7;held=kind=='cancelled';recatch=.67
        for i in range(56):
            t=i/60;dt=max(0,t-release);w=np.array([.1+vx*dt,.4+.1*dt,z0+vz*dt-.5*g*dt*dt]) if t>release and not held else np.array([.1,.4,z0])
            if t>contact and kind not in ['no_racket','no_contact','cancelled','recatch','no_apex']:
                d=contact-release;at=np.array([.1+vx*d,.4+.1*d,z0+vz*d-.5*g*d*d]);w=at+np.array([1.6,1.,2.])*(t-contact)
            if kind=='recatch' and t>=recatch:
                d=recatch-release;w=np.array([.1+vx*d,.4+.1*d,z0+vz*d-.5*g*d*d])
            s=stamp(i,t);s['calibration_version']=version;n=dict(**s,diameter_px=20 if image else 14,sigma_px=.3)
            lp=project_point(w,c,0);rp=project_point(w,c,1)
            dropped=(occlusion>0 and 20<=i<20+occlusion) or (kind=='missing_release' and 6<=i<=8) or (kind=='severe_occlusion' and 5<=i<=38) or (kind=='no_apex' and 14<=i<=40)
            if image:
                imgs={};n['reference_valid']=int(i>0)
                if i:n['reference_id']=str(i+99)
                for eye,p in enumerate([lp,rp]):
                    extra=p+np.array([90.,60.]) if (kind=='multi_image' or (kind=='multi_image_geometry' and eye==0)) and i>=12 else None
                    im=render(p,10,blur,noise,rng,extra);mask=np.zeros((360,640),np.uint8)
                    if dropped:im[:]=25
                    if i and not dropped and not(18<=i<=22):cv2.circle(mask,tuple(np.round((p-.5)/2).astype(int)),6,255,-1)
                    if extra is not None:cv2.circle(mask,tuple(np.round((extra-.5)/2).astype(int)),6,255,-1)
                    eye_name='right' if eye else 'left';gn=f'{name}_{i}_{eye_name}.png';mn=f'{name}_{i}_{eye_name}_mask.png';cv2.imwrite(str(inputs/gn),im);cv2.imwrite(str(inputs/mn),mask);imgs[eye_name]=gn;imgs[eye_name+'_mask']=mn
                n['images']=imgs
            elif not dropped:
                n['left_pixel']=(lp+rng.normal(0,noise,2)).tolist();n['right_pixel']=(rp+rng.normal(0,noise,2)).tolist()
                if kind in ['multi_prediction','multi_ambiguous','multi_semantic'] and ((12<=i<=36) or kind in ['multi_ambiguous','multi_semantic']):
                    other=w+np.array([.32,0,.22]);n['left_candidates']=[project_point(other,c,0).tolist()];n['right_candidates']=[project_point(other,c,1).tolist()]
            if kind=='slow_processing':n['processing_time_ns']=str(int(s['sample_time_ns'])+160000000)
            frames.append(n);expected.append(dict(pair_id=s['pair_id'],sample_time_ns=s['sample_time_ns'],world_m=w.tolist(),geometry_expected=not dropped and kind!='multi_ambiguous'))
            if kind!='no_hand':
                d=detection(s,'hand',lp,near=held or t<=release or (kind=='recatch' and t>=recatch),delay=delay)
                if kind=='invisible_hand':d['visible']=0
                if kind=='wrong_model':d['model_version']=''
                if kind=='wrong_source':d['pair_id']=str(int(s['pair_id'])+1000)
                if kind=='out_of_order':d['completed_time_ns']=str(int(s['sample_time_ns'])+[160000000,20000000,80000000][i%3])
                if kind=='arrival_expired':d['arrival_time_ns']=str(int(s['sample_time_ns'])+300000000)
                sem.append(d)
            if kind not in ['no_racket','no_contact','cancelled','recatch'] and 40<=i<=46:sem.append(detection(s,'racket',lp,True,delay))
            if kind in ['multi_semantic','multi_image']:
                for eye,p in enumerate([lp,rp]):d=detection(s,'ball',p,True,0);d['eye']='right' if eye else 'left';sem.append(d)
        case=dict(name=name,mode='image_measurement_semantic_replay' if image else 'pixel_observation_semantic_replay',calibration=config,frames=frames,detections=sem)
        if kind=='budget':case['geometry_config']=dict(calibration_position_sigma_m=.003,world_translation_sigma_m=.002,world_rotation_sigma_rad=.001,sync_sigma_s=.0002,sync_speed_bound_m_s=5.)
        manifest['cases'].append(case)
        status='cancelled' if kind in ['cancelled','recatch'] else 'unknown' if kind in ['no_hand','no_racket','no_contact','missing_release','severe_occlusion','no_apex','invisible_hand','wrong_model','wrong_source','multi_ambiguous','arrival_expired'] else 'complete'
        truth['cases'].append(dict(name=name,kind=kind,status=status,frames=expected,release_ns=str(round((1+release)*1e9)),contact_ns=str(round((1+contact)*1e9)),apex_ns=str(round((1+release+vz/g)*1e9)),height_m=vz*vz/(2*g),image=image,noise=noise,occlusion_frames=occlusion))
    for i in range(30):scenario(f'varied_serve_{i:02}',vz=2.1+.022*i,vx=.08+.009*i,z0=.65+.006*i,baseline=.15+.0015*i,distance=2.5+.025*i)
    for kind in ['no_hand','no_racket','cancelled','recatch','missing_release','severe_occlusion','no_apex','invisible_hand','wrong_model','wrong_source']:scenario('missing_'+kind,kind)
    for name,delay,kind in [('delay20',.02,'normal'),('delay80',.08,'normal'),('delay160',.16,'normal'),('out_of_order',.02,'out_of_order'),('slow160',.02,'slow_processing')]:scenario('async_'+name,kind,delay=delay)
    for count in [1,3,5]:scenario(f'occlusion_{count}',occlusion=count)
    for stride in [2,3]:
        scenario(f'sparse_semantics_{60//stride}hz',delay=.08)
        manifest['cases'][-1]['detections']=[d for d in manifest['cases'][-1]['detections']if (int(d['pair_id'])-100)%stride==0]
    for kind in ['multi_prediction','multi_semantic','multi_ambiguous','budget','arrival_expired']:scenario(kind,kind)
    for name,kind,blur,noise,baseline,distance in [('image_subpixel','normal',0,0,.18,3.),('image_blur','normal',.7,0,.18,3.),('image_noise','normal',.7,1.,.18,3.),('image_multi','multi_image',0,0,.18,3.),('image_multi_geometry','multi_image_geometry',0,0,.18,3.),('image_baseline150','normal',0,0,.15,2.5),('image_baseline200','normal',0,0,.2,3.5)]:scenario(name,kind,image=True,blur=blur,noise=noise,baseline=baseline,distance=distance)
    # Use the estimated chessboard configuration for a separate end-to-end
    # image run. run_validation_v2 copies the real C++ calibration before CLI.
    scenario('image_estimated_calibration',image=True)
    case=manifest['cases'][-1];case['calibration']='estimated_calibration.json';case['geometry_config']=dict(epipolar_px=2,reprojection_px=2)
    for f in case['frames']:f['calibration_version']='synthetic-board-broad-estimate'
    for d in case['detections']:d['calibration_version']='synthetic-board-broad-estimate'
    truth['cases'][-1]['estimated_calibration']=True
    # Two attempts are continuous and receive monotonically increasing IDs;
    # no input reset marker or truth phase is supplied to the online engine.
    a=copy.deepcopy(manifest['cases'][20]);b=copy.deepcopy(a);multi=copy.deepcopy(a);multi['name']='continuous_two_serves';multi['frames']=[];multi['detections']=[]
    for j,src in enumerate([a,b]):
        for f in src['frames']:
            f['pair_id']=str(int(f['pair_id'])+j*100);f['sample_time_ns']=str(int(f['sample_time_ns'])+j*1000000000);multi['frames'].append(f)
        for d in src['detections']:d['pair_id']=str(int(d['pair_id'])+j*100);d['sample_time_ns']=str(int(d['sample_time_ns'])+j*1000000000);d['completed_time_ns']=str(int(d['completed_time_ns'])+j*1000000000);multi['detections'].append(d)
    manifest['cases'].append(multi)
    broad_boards(inputs,base)
    dump(inputs/'manifest_v2.json',manifest);dump(truth_dir/'expected_v2.json',truth)
    dump(root/'SCENARIO_MATRIX.json',dict(varied_serves=30,missing_or_cancelled=10,async_sequences=5,occlusion_frames=[1,3,5],continuous_two_serves=1,image_cases=9,total_cases=len(manifest['cases']),C_frozen=False,source='B development/regression cases, not independent C acceptance'))
    print('V2_FIXTURE_CREATED cases='+str(len(manifest['cases'])))


if __name__=='__main__':main()
