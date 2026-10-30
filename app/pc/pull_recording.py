"""Retrieve a stopped RK recording over USB and create its local HTML replay."""
from pathlib import Path
import argparse,re,subprocess,sys,os
sys.path.insert(0,str(Path(__file__).resolve().parent))
from case_io import BASE,normalize_board,read
import json
from command_log import run_logged

def prepare_replay(case):
    """Relocate saved RK paths; leave release calculation and results on RK."""
    case=Path(case).resolve()
    completion=read(case/'measurement-complete.json')
    if completion.get('measurement_host')!='RK' or completion.get('execution_host')!='aarch64':
        raise ValueError('Recording has no completed RK motion-release result')
    if completion['status'] not in ('measured','estimated','no_valid_fit'):
        raise ValueError('RK motion-release calculation did not complete')
    receipt=normalize_board(case)
    app=read(receipt)
    app.update(input_manifest=str(case/'input/manifest.json'),result=str(case/'analysis'),
               calibration=str(case/'calibration.json'))
    manifest=read(case/'input/manifest.json')
    app['source_video']=manifest.get('provenance',{}).get('video_path',app.get('source_video',case.name))
    if (app.get('final_event') or {}).get('fit_valid'):
        if completion['status'] not in ('measured','estimated') or not (case/'motion-current/latest-release.json').is_file():
            raise ValueError('RK motion-release result is missing; finish measurement on RK first')
    receipt.write_text(json.dumps(app,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt

def main():
 from field_actions import retrieve
 p=argparse.ArgumentParser();p.add_argument('name');a=p.parse_args();retrieve(a.name)
if __name__=='__main__':main()
