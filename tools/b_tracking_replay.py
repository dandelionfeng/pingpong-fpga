#!/usr/bin/env python3
"""B automatic stereo measurement and short-term tracking replay.

Consumes the existing frame manifest and C detection JSONL as candidate hints.
The C box is never treated as a metric truth: candidates are paired by frame
identity, checked in rectified stereo geometry, then filtered by a bounded
constant-velocity tracker. Outputs one record for every input pair.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, statistics, sys
from pathlib import Path
from typing import Any
import cv2
import numpy as np

VERSION = "b-auto-measure-track-v0.1"
MAX_GAP_S = 0.25
MAX_EPIPOLAR_PX = 3.0
MIN_DISPARITY_PX = 0.5
MIN_DEPTH_M, MAX_DEPTH_M = 0.1, 15.0

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def arr(x, shape=None):
    a=np.asarray(x,dtype=np.float64)
    if shape and a.shape!=shape: raise ValueError(f"calibration shape {a.shape} != {shape}")
    return a

def load_calibration(path: Path):
    j=json.loads(path.read_text(encoding='utf-8'))
    if j.get('schema') != 'b-calibration-v1-draft': raise ValueError('unsupported calibration schema')
    if j.get('image_size_px') != [1280,720]: raise ValueError('calibration image size must be 1280x720')
    if j.get('left_right_order') != 'stitched_left=physical_left_camera, stitched_right=physical_right_camera': raise ValueError('left/right order mismatch')
    if float(j.get('square_size_m',0))<=0: raise ValueError('metric calibration required')
    c={
      'K1':arr(j['K_left'],(3,3)), 'D1':arr(j['D_left']).reshape(-1,1),
      'K2':arr(j['K_right'],(3,3)), 'D2':arr(j['D_right']).reshape(-1,1),
      'R':arr(j['R_left_to_right'],(3,3)), 'T':arr(j['T_m']).reshape(3,1),
      'R1':arr(j['R1'],(3,3)), 'R2':arr(j['R2'],(3,3)),
      'P1':arr(j['P1'],(3,4)), 'P2':arr(j['P2'],(3,4)),
      'version':'ov9281-20261014', 'sha256':sha256(path), 'unit':'m',
      'metadata':j,
    }
    baseline=float(np.linalg.norm(c['T']))
    if baseline < .001 or baseline > 1: raise ValueError('invalid baseline')
    c['baseline_m']=baseline
    return c

def load_detections(path: Path):
    by={}
    if not path: return by
    for line_no,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
        if not line.strip(): continue
        try: d=json.loads(line)
        except Exception as e: raise ValueError(f'detection JSONL line {line_no}: {e}')
        eye=d.get('eye'); pair=int(d.get('pair_id',0))
        if eye not in ('left','right') or pair<=0: continue
        candidates=[]
        for b in d.get('boxes',[]):
            cls=b.get('class',b.get('label'))
            if cls!='ball': continue
            box=b.get('bbox')
            center=b.get('center')
            if center is None and isinstance(box,list) and len(box)==4: center=[float(box[0])+float(box[2])/2,float(box[1])+float(box[3])/2]
            if not isinstance(center,list) or len(center)!=2: continue
            x,y=float(center[0]),float(center[1]); score=float(b.get('confidence',b.get('score',0)))
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(score)): continue
            if not (0<=x<1280 and 0<=y<720 and 0<=score<=1): continue
            candidates.append({'xy':[x,y],'score':score,'semantics':b.get('bbox_semantics','unknown'),'source':'c_replay_candidate'})
        by.setdefault(pair,{}).setdefault(eye,[]).extend(candidates)
    return by

def point_rectified(c, eye, xy):
    K,D,R,P=(c['K1'],c['D1'],c['R1'],c['P1']) if eye=='left' else (c['K2'],c['D2'],c['R2'],c['P2'])
    p=np.asarray([[xy]],dtype=np.float64)
    q=cv2.undistortPoints(p,K,D,R=R,P=P).reshape(2)
    return q

def triangulate(c,left,right):
    l=point_rectified(c,'left',left); r=point_rectified(c,'right',right)
    epi=abs(float(l[1]-r[1])); disp=float(l[0]-r[0])
    if epi>MAX_EPIPOLAR_PX: return None,'epipolar_mismatch',epi,disp
    if disp<MIN_DISPARITY_PX: return None,'nonpositive_or_tiny_disparity',epi,disp
    h=cv2.triangulatePoints(c['P1'],c['P2'],l.reshape(2,1),r.reshape(2,1)).reshape(4)
    if abs(float(h[3]))<1e-12: return None,'point_at_infinity',epi,disp
    xr=h[:3]/h[3]; cam=c['R1'].T@xr
    rc=c['R']@cam+c['T'].reshape(3)
    if not np.all(np.isfinite(cam)) or cam[2]<MIN_DEPTH_M or cam[2]>MAX_DEPTH_M or rc[2]<MIN_DEPTH_M: return None,'invalid_depth',epi,disp
    # Reprojection check in the original pixel domain.
    def reproj(eye,xyz):
        K,D=(c['K1'],c['D1']) if eye=='left' else (c['K2'],c['D2'])
        xyz2=xyz if eye=='left' else c['R']@xyz+c['T'].reshape(3)
        q,_=cv2.projectPoints(xyz2.reshape(1,1,3),np.zeros(3),np.zeros(3),K,D)
        return q.reshape(2)
    el=float(np.linalg.norm(reproj('left',cam)-left)); er=float(np.linalg.norm(reproj('right',cam)-right)); rep=max(el,er)
    if rep>5: return None,'reprojection_mismatch',epi,disp
    return {'camera_xyz_m':cam.tolist(),'epipolar_error_px':epi,'disparity_px':disp,'reprojection_error_px':rep},'ok',epi,disp

CAL=None
def choose_pair(left,right,pred=None):
    choices=[]
    for i,l in enumerate(left):
      for j,r in enumerate(right):
        w,reason,_,_=triangulate(CAL,l['xy'],r['xy'])
        if w is None: continue
        cost=w['epipolar_error_px']/MAX_EPIPOLAR_PX+w['reprojection_error_px']/5
        if pred is not None:
            cost += float(np.linalg.norm(np.asarray(w['camera_xyz_m'])-pred))/max(float(pred[2]),.2)
        cost -= .15*(l['score']+r['score'])/2
        choices.append((cost,i,j,w))
    if not choices: return None,'no_valid_stereo_pair'
    choices.sort(key=lambda x:x[0])
    if len(choices)>1 and choices[1][0]-choices[0][0]<0.05 and np.linalg.norm(np.asarray(choices[1][3]['camera_xyz_m'])-np.asarray(choices[0][3]['camera_xyz_m']))>.01:
        return None,'ambiguous_stereo_pairs'
    return choices[0][3] | {'left_xy':left[choices[0][1]]['xy'],'right_xy':right[choices[0][2]]['xy'],'candidate_score':float((left[choices[0][1]]['score']+right[choices[0][2]]['score'])/2)},'observed'

class Tracker:
    def __init__(self): self.pos=None; self.vel=np.zeros(3); self.t=None; self.last_obs_t=None; self.track_id=0
    def reset(self): self.pos=None; self.vel=np.zeros(3); self.t=None; self.last_obs_t=None
    def update(self,t,obs):
        out={'track_state':'invalid','track_id':self.track_id or None,'filtered_xyz_m':None,'predicted_xyz_m':None,'velocity_m_s':None,'track_reason':''}
        if self.t is not None and t<=self.t: self.reset(); out['track_reason']='nonmonotonic_sample_reset'
        dt=0 if self.t is None else (t-self.t)*1e-9
        if self.pos is not None and dt>MAX_GAP_S: self.reset(); dt=0; out['track_reason']='gap_reset'
        if self.pos is not None and dt>0:
            pred=self.pos+self.vel*dt; out['predicted_xyz_m']=pred.tolist()
        else: pred=None
        if obs is not None:
            z=np.asarray(obs,dtype=float)
            if self.pos is None:
                self.track_id+=1; self.pos=z; self.vel[:]=0; out['track_reason']='initialized'
            else:
                if dt>0:
                    innovation=z-pred
                    # Bounded alpha-beta update; preserves sample-time dt.
                    alpha=.65; beta=.18
                    self.pos=pred+alpha*innovation; self.vel=self.vel+beta*innovation/dt
                else: self.pos=z
                out['track_reason']='updated'
            self.last_obs_t=t; out['track_state']='observed'; out['filtered_xyz_m']=self.pos.tolist()
        elif self.pos is not None and self.last_obs_t is not None and (t-self.last_obs_t)*1e-9<=MAX_GAP_S:
            self.pos=pred if pred is not None else self.pos; out['track_state']='predicted'; out['filtered_xyz_m']=self.pos.tolist(); out['track_reason']=out['track_reason'] or 'short_occlusion_prediction'
        else:
            self.reset(); out['track_reason']=out['track_reason'] or 'no_observation'
        if self.t is not None and dt>0: out['velocity_m_s']=self.vel.tolist()
        out['track_id']=self.track_id or None; self.t=t; return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input','--input-manifest',dest='input',required=True)
    ap.add_argument('--calibration',required=True)
    ap.add_argument('--detections-jsonl',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args(); root=Path(args.input).resolve().parent; out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    cal=load_calibration(Path(args.calibration)); globals()['CAL']=cal
    det=load_detections(Path(args.detections_jsonl)); manifest=json.loads(Path(args.input).read_text(encoding='utf-8'))
    frames=manifest.get('frames',manifest.get('cases',[])); tracker=Tracker(); records=[]; counts={k:0 for k in ['total','observed_2d_pair','observed_3d','predicted','invalid','ambiguous','no_candidate']}
    for f in frames:
        pair=int(f['pair_id']); t=int(f.get('timestamp_ns',f.get('sample_time_ns',0))); mode=f.get('config_version','a-int-v1'); left=det.get(pair,{}).get('left',[]); right=det.get(pair,{}).get('right',[])
        pred=None
        if tracker.pos is not None and tracker.t is not None and t>tracker.t: pred=(tracker.pos+tracker.vel*((t-tracker.t)*1e-9)).tolist()
        stereo,reason=choose_pair(left,right,pred)
        if stereo is not None: counts['observed_2d_pair']+=1; counts['observed_3d']+=1
        elif left or right: counts['ambiguous' if reason=='ambiguous_stereo_pairs' else 'invalid']+=1
        else: counts['no_candidate']+=1
        tr=tracker.update(t, stereo['camera_xyz_m'] if stereo else None)
        if tr['track_state']=='predicted': counts['predicted']+=1
        rec={'schema':'b-auto-measure-track-v0.1','pair_id':pair,'sample_time_ns':t,'eye_timestamp_ns':f.get('eye_timestamp_ns',[t,t]),'camera_frame_id':f.get('camera_frame_id',[pair-1,pair-1]),'mode_id':mode,'config_version':mode,'calibration_version':cal['version'],'calibration_sha256':cal['sha256'],'coordinate_frame':'left_camera','unit':'m','model_source':'actual_model_record_replay','model_version':'from_detection_cache','left':{'candidates':len(left),'center_px':stereo['left_xy'] if stereo else None},'right':{'candidates':len(right),'center_px':stereo['right_xy'] if stereo else None},'stereo':stereo if stereo else {'valid':False,'reason':reason},'track':tr}
        records.append(rec); counts['total']+=1
    with (out/'results.jsonl').open('w',encoding='utf-8') as g:
        for r in records: g.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    with (out/'results.csv').open('w',newline='',encoding='utf-8') as g:
        w=csv.writer(g); w.writerow(['pair_id','sample_time_ns','status','reason','x_m','y_m','z_m','track_state','track_id'])
        for r in records:
            s=r['stereo']; xyz=s.get('camera_xyz_m') if s.get('valid',True) else None
            if isinstance(s,dict) and 'camera_xyz_m' in s: xyz=s['camera_xyz_m']; status='observed'; reason='ok'
            else: status=r['track']['track_state']; reason=s.get('reason','')
            w.writerow([r['pair_id'],r['sample_time_ns'],status,reason,*(xyz or ['','','']),r['track']['track_state'],r['track']['track_id']])
    summary={'schema':'b-auto-measure-track-summary-v0.1','algorithm_version':VERSION,'input_manifest':str(Path(args.input)),'input_frame_count':len(frames),'calibration_version':cal['version'],'calibration_sha256':cal['sha256'],'coordinate_frame':'left_camera','unit':'m','counts':counts,'limitations':['C detection cache is candidate input, not truth','no motion-mask files were present in the handoff package','world/table transform and event judgement are out of scope','sensor synchronization was not independently measured']}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':
    main()
