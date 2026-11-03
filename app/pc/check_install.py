"""Read-only installation and recording checks. No hardware inference is launched."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from quick_common import BASE,ROOT,CASE_ROOT,VERSION,verify_local,read,sha
import cv2,numpy,serial
from field_actions import validate_case
def main():
    assert BASE==ROOT/'app' and CASE_ROOT==ROOT/'data'
    assert Path(cv2.__file__).resolve().is_relative_to(ROOT/'runtime/python')
    assert Path(numpy.__file__).resolve().is_relative_to(ROOT/'runtime/python')
    assert Path(serial.__file__).resolve().is_relative_to(ROOT/'app/tools/python')
    count=verify_local();mapping=read(CASE_ROOT/'index.json')['renumbering'];assert isinstance(mapping,list)
    assert len({r['case'] for r in mapping})==len(mapping),'data/index.json 样例编号重复'
    # The submission package carries a subset of the mapped recordings; check those included.
    actual={p.name for p in CASE_ROOT.iterdir() if p.is_dir() and (p/'measurement-complete.json').is_file()}
    included=[r for r in mapping if r['case'] in actual];assert included,'data中没有已映射的样例'
    expected={r['case'] for r in included}
    frames=0;input_frames_checked=0;input_jpegs_checked=0;replay_only_cases=[]
    for row in included:
        case=CASE_ROOT/row['case']
        manifest=read(case/'input/manifest.json');input_root=(case/'input').resolve()
        paths=[(input_root/r['file']).resolve() for r in manifest['frames']]
        assert all(p.is_relative_to(input_root) for p in paths),'样例输入路径越界'
        present=sum(p.is_file() for p in paths)
        if present==len(paths) and paths:
            validate_case(case);input_frames_checked+=1;input_jpegs_checked+=present
        elif present:
            raise ValueError(f"{row['case']} 原始帧不完整：{present}/{len(paths)}")
        else:
            replay_only_cases.append(row['case'])
            assert read(case/'version.json')['version']==VERSION['version'],row['case']
            assert read(case/'summary.json')['status']=='passed' and read(case/'summary.json')['pairs']==len(manifest['frames']),row['case']
        for name,digest in row['raw_sha256'].items():assert sha(case/name)==digest,(row['case'],name)
        frames+=read(case/'summary.json')['pairs']
        assert ((case/'replay/回放.html').is_file() or (case/'replay/index.html').is_file()) and (case/'replay/recording.mp4').is_file()
    print(json.dumps({'program_files':count,'recordings':len(included),'reference_case_names':sorted(expected),'total_recordings':len(actual),'pairs':frames,'input_frames_checked_cases':input_frames_checked,'input_jpegs_checked':input_jpegs_checked,'replay_only_cases':replay_only_cases,'omitted_reference_cases':sorted({r['case'] for r in mapping}-actual),'cv2':cv2.__version__,'numpy':numpy.__version__,'serial':serial.__version__,'raw_results_unchanged':True}))
if __name__=='__main__':main()
