"""Four additional board poses not used in calibrateCamera/stereoCalibrate."""
from pathlib import Path
import argparse
import json
import cv2
import numpy as np


def read_calibration(p):
    f=cv2.FileStorage(str(p),cv2.FILE_STORAGE_READ)
    c={k:f.getNode(k).mat() for k in ['K1','K2','D1','D2','R','T','Rcw','tcw']};f.release();return c


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--inputs',required=True);ap.add_argument('--calibration',required=True);ap.add_argument('--report',required=True);ap.add_argument('--heldout',default='board_heldout.json');args=ap.parse_args()
    inputs=Path(args.inputs);meta=json.loads((inputs/args.heldout).read_text());c=read_calibration(Path(args.calibration));truth=read_calibration(inputs/'calibration.json')
    pattern=tuple(meta['corners']);side=meta['square_size'];obj=np.array([[x*side,y*side,0.] for y in range(pattern[1]) for x in range(pattern[0])])
    rows=[]
    for pair in meta['pairs']:
        l=cv2.imread(str(inputs/pair['left']),0);r=cv2.imread(str(inputs/pair['right']),0);ok,a=cv2.findChessboardCornersSB(l,pattern);okr,b=cv2.findChessboardCornersSB(r,pattern)
        if not(ok and okr):rows.append(dict(pair=pair,passed=False,reason='corner_detection_failed'));continue
        success,rv,tv=cv2.solvePnP(obj,a,c['K1'],c['D1']);rot=cv2.Rodrigues(rv)[0];rr=c['R']@rot;tr=c['R']@tv+c['T'];rp=cv2.projectPoints(obj,cv2.Rodrigues(rr)[0],tr,c['K2'],c['D2'])[0].reshape(-1,2)
        errors=np.linalg.norm(rp-b.reshape(-1,2),axis=1);rms=float(np.sqrt(np.mean(errors**2)));rows.append(dict(pair=pair,passed=bool(success and rms<1),stereo_reprojection_rms_px=rms,max_error_px=float(errors.max())))
    report=dict(total=len(rows),passed=sum(r['passed'] for r in rows),source='additional generated board poses; same camera family and renderer, not real or C independent',baseline_error_m=float(abs(np.linalg.norm(c['T'])-np.linalg.norm(truth['T']))),world_rotation_error_rad=float(np.linalg.norm(cv2.Rodrigues(c['Rcw']@truth['Rcw'].T)[0])),world_translation_error_m=float(np.linalg.norm(c['tcw']-truth['tcw'])),cases=rows)
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report));raise SystemExit(report['passed']!=report['total'])


if __name__=='__main__':main()
