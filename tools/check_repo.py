"""Check the published source tree and reject private/runtime payloads in Git."""
from pathlib import Path
import ast,json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def check():
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0');paths=[p for p in paths if p]
    errors=[];forbidden={'.rknn','.pt','.onnx','.mp4','.avi','.jpg','.jpeg','.png','.dll','.so','.ko','.whl','.zip','.gz','.bundle','.pem','.key'}
    prefixes=('runtime/','logs/','app/rk/models/','app/rk/build/','app/dist/','app/tools/python/','app/tools/adb/','app/tools/rk-wheels/','hardware/project/')
    for name in paths:
        p=ROOT/name
        if name.startswith(prefixes) or p.suffix.lower() in forbidden or (p.suffix.lower()=='.exe' and name!='发球测量系统.exe'):errors.append('Private/runtime file staged: '+name)
        if not p.is_file():errors.append('Tracked file missing: '+name);continue
        if p.suffix=='.py':
            try:ast.parse(p.read_text('utf-8-sig'),name)
            except SyntaxError as e:errors.append(str(e))
        if p.suffix in {'.py','.md','.json','.yml','.tcl','.v','.hpp','.cpp'}:
            text=p.read_text('utf-8-sig')
            if re.search(r'(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})',text):errors.append('Credential pattern: '+name)
    config=json.loads((ROOT/'app/version.json').read_text('utf-8'));s=config['settings']
    assert s['model_input_shape']==[1,3,640,640] and s['hand_stop_on_kinematic_candidate'] and s['ball_model_on_every_eye']
    assert s['fpga_mode']==0 and s['teso_stride']==30
    mapping=json.loads((ROOT/'data/index.json').read_text('utf-8'))['renumbering']
    assert [r['original_case'] for r in mapping]==['serve_03','serve_05','serve_06','serve_07','serve_10','serve_15']
    assert [r['case'] for r in mapping]==[f'serve_{i:02}' for i in range(1,7)]
    if errors:raise RuntimeError('\n'.join(errors))
    print('SOURCE_TREE_OK',len(paths),'files')
if __name__=='__main__':check()
