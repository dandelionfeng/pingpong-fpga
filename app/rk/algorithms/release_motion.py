from pathlib import Path
import json,math,cv2,numpy as np
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))

def blob(gray,pred,radius=9,handboxes=None):
    x0=max(0,int(pred[0])-48);y0=max(0,int(pred[1])-48);patch=gray[y0:min(gray.shape[0],y0+96),x0:min(gray.shape[1],x0+96)]
    if patch.size<100:return None
    bg=float(np.median(patch));choices=[]
    for threshold in [bg+6,bg+10,bg+14]:
        n,labels,stats,centers=cv2.connectedComponentsWithStats((patch>threshold).astype(np.uint8),8)
        for k in range(1,n):
            x,y,w,h,a=stats[k];c=centers[k]+[x0,y0];distance=np.linalg.norm(c-pred)
            if a<8 or a>math.pi*(radius*2.3)**2 or max(w,h)>radius*5 or distance>40 or x==0 or y==0 or x+w==patch.shape[1] or y+h==patch.shape[0]:continue
            if handboxes is not None and not any(b[0]-20<=c[0]<=b[0]+b[2]+20 and b[1]-20<=c[1]<=b[1]+b[3]+20 for b in handboxes):continue
            signal=float(patch[labels==k].mean())-bg
            score=distance/(radius*2)+.4*abs(math.log(a/(math.pi*radius*radius)))-signal/12
            choices.append((score,c,float(a),float(signal)))
    return min(choices,key=lambda q:q[0]) if choices else None

def triangulate(points,cal):
    K=[np.array(cal[k],float) for k in ['K_left','K_right']];D=[np.array(cal[k],float) for k in ['D_left','D_right']]
    n=[cv2.undistortPoints(np.array(p,float).reshape(1,1,2),K[e],D[e]).reshape(2,1) for e,p in enumerate(points)]
    R=np.array(cal['R_left_to_right'],float);T=np.array(cal['T_m'],float).reshape(3,1);q=cv2.triangulatePoints(np.c_[np.eye(3),np.zeros(3)],np.c_[R,T],*n).reshape(4);cam=q[:3]/q[3]
    world=np.array(cal['diagnostic_world_pose']['Rcw']).T@(cam-np.array(cal['diagnostic_world_pose']['tcw']))
    rectified=[cv2.undistortPoints(np.array(p,float).reshape(1,1,2),K[e],D[e],R=np.array(cal['R2' if e else 'R1']),P=np.array(cal['P2' if e else 'P1'])).reshape(2) for e,p in enumerate(points)]
    return world,cam[2],abs(rectified[0][1]-rectified[1][1])

def robust_fit(A,b):
    weights=np.ones(len(A));c=np.linalg.lstsq(A,b,rcond=None)[0]
    for _ in range(10):
        residual=np.linalg.norm(A@c-b,axis=1);scale=max(.002,1.4826*np.median(abs(residual-np.median(residual))));weights=np.minimum(1,1.5*scale/np.maximum(residual,1e-9));c=np.linalg.lstsq(A*np.sqrt(weights)[:,None],b*np.sqrt(weights)[:,None],rcond=None)[0]
    return c,float(np.sum(weights*np.linalg.norm(A@c-b,axis=1)**2)/np.sum(weights))

def track_pixels(path,calibration,output,seed_evidence=None,end_pair_id=None):
    OUT=Path(output);OUT.mkdir(parents=True,exist_ok=True)
    app=read(path);event=app['final_event'];manifest=Path(app.get('input_manifest',Path(path).parent/'input/manifest.json'));inp=read(manifest);rr=[json.loads(s) for s in (Path(app['result'])/'frames.jsonl').read_text('utf-8').splitlines()]
    cal=read(calibration);ev=seed_evidence or event['release_pixel_evidence'];seed_ids=ev['seed_pair_ids'];seed=[next(s for s in ev['samples'] if s['pair_id']==i) for i in seed_ids]
    source_index={row['pair_id']:i for i,row in enumerate(inp['frames'])}
    seed_i=source_index[seed_ids[0]];seed_next=source_index[seed_ids[1]]
    detections={(r['pair_id'],r['eye']):r['boxes'] for r in [json.loads(s) for s in (Path(app['result'])/'detections.jsonl').read_text('utf-8').splitlines()]}
    begin=max(1,seed_i-36);end=source_index[end_pair_id if end_pair_id is not None else event['used_pair_ids'][-1]];images={}
    def hands_for(j,eye):
        boxes=detections.get((inp['frames'][j]['pair_id'],'right' if eye else 'left'))
        # An uninvoked hand graph is unknown, not a negative hand observation.
        return [b['bbox'] for b in boxes if b['class']=='hand'] if boxes is not None else None
    def gray(j,eye):
        if j not in images:images[j]=cv2.imread(str(manifest.parent/inp['frames'][j]['file']),0)
        return images[j][:,eye*1280:(eye+1)*1280]
    tracks=[{},{}]
    for eye in range(2):
        c0=np.array(seed[0]['eyes'][eye]['ball_center_px']);c1=np.array(seed[1]['eyes'][eye]['ball_center_px']);v=(c1-c0)/(seed_next-seed_i)
        tracks[eye][seed_i]=(c0,0.);tracks[eye][seed_next]=(c1,0.)
        for direction,indices,last,velocity in [(-1,range(seed_i-1,begin-1,-1),c0.copy(),-v.copy()),(1,range(seed_next+1,end+1),c1.copy(),v.copy())]:
            missing=0
            for j in indices:
                pred=last+velocity*(missing+1)
                hands=hands_for(j,eye) if direction<0 else None
                found=blob(gray(j,eye),pred,handboxes=hands)
                if found is None:missing+=1;continue
                _,center,area,signal=found
                measured=(center-last)/(missing+1);velocity=.5*velocity+.5*measured;last=center;missing=0;tracks[eye][j]=(center,signal)
    # Stereo correspondence must not independently drift from the ball to a
    # bright wristwatch. Seed disparity only locates a search ROI; right-eye
    # coordinates are measured from its own image, never copied into geometry.
    displacement=np.array(seed[0]['eyes'][0]['ball_center_px'])-np.array(seed[0]['eyes'][1]['ball_center_px'])
    tracks[1]={}
    for j,(left,_) in tracks[0].items():
        pred=left-displacement;hands=hands_for(j,1) if j<seed_i else None
        found=blob(gray(j,1),pred,handboxes=hands)
        if found is not None:
            _,center,area,signal=found
            if abs((left[0]-center[0])-displacement[0])<max(10.,abs(displacement[0])*.25):tracks[1][j]=(center,signal)
    observed=[];rejected=[]
    for j in sorted(set(tracks[0])&set(tracks[1])):
        points=[tracks[e][j][0] for e in range(2)];world,depth,epipolar=triangulate(points,cal)
        if not np.all(np.isfinite(world)) or not .1<depth<15:continue
        item={'pair_id':inp['frames'][j]['pair_id'],'frame0':j,'timestamp_ns':rr[j]['timestamp_ns'],'pixels':[p.tolist() for p in points],'world_m':world.tolist(),'source':'observed_bright_blob_roi','independent_identity_validated':False,'rectified_y_difference_px':float(epipolar)}
        # Research-only correspondence audit; this does not restore any gate
        # in the deployed, quality-relaxed V6 program.
        if epipolar>4:rejected.append(item);continue
        observed.append(item)
    return sorted(observed+rejected,key=lambda p:p["pair_id"])

def profile(points,g=-9.80665,drop=None):
    points=sorted(points,key=lambda p:p['timestamp_ns']);t=np.array([p['timestamp_ns'] for p in points],float)*1e-9
    xyz=np.array([p['world_m'] for p in points]);indices=np.array([i for i in range(len(points)) if i!=drop]);candidates=[]
    for k in range(4,len(points)-6):
        # Drop the candidate too: the search grid must not include a removed observation.
        if k==drop:continue
        u=t[indices]-t[k];before=np.minimum(u,0);A=np.c_[np.ones(len(u)),u,before**2,before**3]
        known=np.c_[np.zeros(len(u)),np.zeros(len(u)),.5*g*u*u];c,loss=robust_fit(A,xyz[indices]-known)
        # One-sided contact force from the palm can only add upward acceleration.
        pre_accel=g+2*c[2,2];vz=c[1,2]
        if pre_accel<g or vz<=0:continue
        candidates.append({'pair_id':points[k]['pair_id'],'frame0':points[k]['frame0'],'timestamp_ns':points[k]['timestamp_ns'],
            'weighted_rms_m':math.sqrt(loss),'vertical_velocity_m_s':float(vz),'before_vertical_acceleration_m_s2':float(pre_accel)})
    if not candidates:raise ValueError('insufficient valid kinematic evidence')
    return sorted(candidates,key=lambda item:item['weighted_rms_m'])
