"""Read-only installation and recording checks. No hardware inference is launched."""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from quick_common import BASE,ROOT,CASE_ROOT,verify_local,read,sha
import cv2,numpy,serial
from field_actions import validate_case
def main():
    assert BASE==ROOT/'app' and CASE_ROOT==ROOT/'data'
    assert Path(cv2.__file__).resolve().is_relative_to(ROOT/'runtime/python')
    assert Path(numpy.__file__).resolve().is_relative_to(ROOT/'runtime/python')
    assert Path(serial.__file__).resolve().is_relative_to(ROOT/'app/tools/python')
    count=verify_local();mapping=read(CASE_ROOT/'index.json')['renumbering'];assert len(mapping)==6
    expected={r['case'] for r in mapping};actual={p.name for p in CASE_ROOT.iterdir() if p.is_dir() and (p/'measurement-complete.json').is_file()};assert expected.issubset(actual)
    frames=0
    for row in mapping:
        case=CASE_ROOT/row['case'];validate_case(case)
        for name,digest in row['raw_sha256'].items():assert sha(case/name)==digest,(row['case'],name)
        frames+=read(case/'summary.json')['pairs']
        assert (case/'replay/回放.html').is_file() and (case/'replay/recording.mp4').is_file()
    print(json.dumps({'program_files':count,'recordings':6,'reference_case_names':sorted(expected),'total_recordings':len(actual),'pairs':frames,'cv2':cv2.__version__,'numpy':numpy.__version__,'serial':serial.__version__,'raw_results_unchanged':True}))
if __name__=='__main__':main()
