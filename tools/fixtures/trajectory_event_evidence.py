"""Export evidence from C++ outputs and source inputs; never reads truth."""
import argparse
import csv
import hashlib
import html
import json
import shutil
from pathlib import Path
import cv2
import numpy as np


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def roi(image,p,size):
    x=int(np.floor(p[0]-size/2));y=int(np.floor(p[1]-size/2));x0=max(0,x);y0=max(0,y);x1=min(image.shape[1],x+size);y1=min(image.shape[0],y+size)
    crop=image[y0:y1,x0:x1];crop=cv2.copyMakeBorder(crop,y0-y,y+size-y1,x0-x,x+size-x1,cv2.BORDER_REPLICATE)
    return crop,dict(origin=[x,y],valid_range=[x0-x,y0-y,x1-x0,y1-y0],padding='replicate; only original pixels are evidence')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);args=ap.parse_args();root=Path(args.root);manifest=read(root/'inputs/manifest_v2.json');cards=[];total=0
    for case in manifest['cases']:
        name=case['name'];result=read(root/'results'/f'{name}.json');frames={f['pair_id']:f for f in result['frames']};nodes={f['pair_id']:f for f in case['frames']}
        for u in result['online_updates']:
            if not u['finalized']:continue
            folder=root/'evidence'/name/('event_'+u['event_id']);folder.mkdir(parents=True,exist_ok=True);ids=set(u['source_pair_ids']);segments=[f for f in result['frames']if f['pair_id']in ids]
            with (folder/'trajectory.csv').open('w',newline='',encoding='utf-8') as f:
                writer=csv.writer(f);writer.writerow(['pair_id','sample_time_ns','geometry_reason','track_reason','observed_xyz_m','filtered_xyz_m','predicted_xyz_m'])
                for fr in segments:writer.writerow([fr['pair_id'],fr['sample_time_ns'],fr['geometry_reason'],fr['track_reason'],*[json.dumps(fr.get(k)) for k in ['observed_world_m','filtered_world_m','predicted_world_m']]])
            selected=set()
            for key in ['release','apex','contact']:
                if key not in u:continue
                t=u[key];a=int(t['begin_ns']);b=int(t['end_ns']);ordered=[f for f in segments if a-16666668<=int(f['sample_time_ns'])<=b+16666668];selected.update(f['pair_id']for f in ordered)
            if not selected:selected.update(f['pair_id']for f in segments[:2])
            media=[]
            for pid in sorted(selected,key=int):
                node=nodes.get(pid,{});fr=frames[pid]
                if 'images'not in node:continue
                for eye in ['left','right']:
                    source=root/'inputs'/node['images'][eye];raw=folder/f'{pid}_{eye}_original.png';shutil.copy2(source,raw);gray=cv2.imread(str(raw),0);overlay=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR);center=fr.get(eye+'_pixel');pred=fr.get(eye+'_prediction_pixel')
                    if pred:cv2.drawMarker(overlay,tuple(np.round(pred).astype(int)),(255,160,0),cv2.MARKER_CROSS,12,1)
                    if center:cv2.drawMarker(overlay,tuple(np.round(center).astype(int)),(0,200,0),cv2.MARKER_CROSS,12,1)
                    boxes=[]
                    for d in case['detections']:
                        arrival=int(d.get('arrival_time_ns',d['completed_time_ns']))
                        if d['pair_id']==pid and d['eye']==eye and d['visible'] and arrival<=int(u['published_time_ns']) and arrival-int(d['sample_time_ns'])<=250000000:
                            x,y,w,h=np.round(d['box']).astype(int);cv2.rectangle(overlay,(x,y),(x+w,y+h),(0,0,230),1);cv2.putText(overlay,d['label'],(x,max(12,y-3)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,230),1);boxes.append(d)
                    path=folder/f'{pid}_{eye}_overlay.png';cv2.imwrite(str(path),overlay);item=dict(pair_id=pid,eye=eye,sample_time_ns=fr['sample_time_ns'],original=raw.name,overlay=path.name,source_sha256=digest(source),boxes=boxes)
                    if center:
                        for size in [256,64]:patch,metadata=roi(gray,center,size);target=folder/f'{pid}_{eye}_roi{size}.png';cv2.imwrite(str(target),patch);item[f'roi{size}']=dict(file=target.name,**metadata)
                    media.append(item)
            cal=root/'inputs'/case.get('calibration',manifest['calibration']);dump(folder/'manifest.json',dict(schema='b-event-evidence-v2-draft',name=name,event=u,calibration_source=cal.name,calibration_sha256=digest(cal),media=media,source_mode=case['mode'],semantic_source='explicit synthetic detection replay; no actual C inference',image_status='source images attached'if media else 'pixel replay has no original image; no image fabricated'))
            relative=folder.relative_to(root).as_posix();images=''.join(f'<a href="{relative}/{m["original"]}"><img src="{relative}/{m["overlay"]}" width="420"></a>'for m in media[:4]);cards.append(f'<article><h2>{html.escape(name)} · event {u["event_id"]}</h2><p>{html.escape(u["status"]+" / "+u["reason"])}</p><a href="{relative}/manifest.json">事件与来源清单</a> · <a href="{relative}/trajectory.csv">三维轨迹片段</a><div>{images}</div></article>');total+=1
    page='<!doctype html><meta charset="utf-8"><title>第三部分事件证据</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:auto;padding:24px;background:#f3f6fa}article{padding:20px;background:white;margin:18px 0;border:1px solid #ccd6e2}img{max-width:100%;margin:8px}a{color:#145e9b}</style><h1>事件证据与来源</h1><p>原图、手拍框、局部区域和实际观测轨迹。检测框为显式回放；像素回放场景没有原图。预测、滤波、观测分别保存。</p>'+''.join(cards)
    (root/'events.html').write_text(page,encoding='utf-8');print('EVENT_EVIDENCE_COMPLETE events='+str(total))


if __name__=='__main__':main()
