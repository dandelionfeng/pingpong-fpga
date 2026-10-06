"""Package executed B v2 results and check every delivered byte/link.

Package file inspection is not a staged/full repository check.
"""
import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[2]


def sha(data):return hashlib.sha256(data).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def log(p):
    data=p.read_bytes();return data.decode('utf-16'if data.startswith((b'\xff\xfe',b'\xfe\xff'))else'utf-8-sig')


class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        for k,v in attrs:
            if k in ('href','src')and v and not v.startswith(('#','https://','http://','data:')):self.links.append(unquote(v))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);args=ap.parse_args();val=Path(args.root).resolve();out=ROOT/'_deliveries';module=ROOT/'software/pc_pipeline/trajectory';build=module/'build-ninja-release'
    score=read(val/'score-v2.json');assert score['total']==score['passed']==84 and score['failed']==0
    tests=log(build/'test.log');counts=re.findall(r'TRAJECTORY_TESTS passed=(\d+) failed=(\d+) group=(\w+)',tests);assert sorted(counts)==sorted([('21','0','geometry'),('13','0','tracking'),('11','0','events'),('5','0','calibration'),('12','0','online')])
    assert '100% tests passed, 0 tests failed out of 8'in tests
    assert not re.search(r'warning [A-Z]\d+|error [A-Z]\d+|警告 [A-Z]\d+|错误 [A-Z]\d+',log(build/'build.log'),re.I)
    for name,count in [('board',4),('board_broad',6)]:s=read(val/(name+'-score.json'));assert s['total']==s['passed']==count
    paths=[p.relative_to(ROOT)for p in sorted(module.rglob('*'))if p.is_file()and not any(x.startswith('build')for x in p.relative_to(module).parts[:-1])]
    paths+=[p.relative_to(ROOT)for p in sorted((ROOT/'tools/fixtures').glob('trajectory*'))if p.is_file()]
    paths+=[Path('reports/第三部分_三维轨迹事件_v2验证_2026-10-06.md'),Path('handoffs/2026-10-06-b-trajectory-v2.md')]
    paths+=[Path(p)for p in ['reports/第三部分_三维轨迹事件_初版验证_2026-10-06.md','handoffs/2026-10-06-b-trajectory-v1.md','reports/第二部分_球心测量_v2验证_2026-10-06.md','handoffs/2026-10-06-b-ball-measurement-v2.md']]
    paths+=[p.relative_to(ROOT)for p in sorted((ROOT/'reports/ball_measurement_v2/2026-10-06').glob('*'))if p.is_file()]
    part2=read(out/'part2_v2_validation/SOURCE_SHA256.json');dependencies=[]
    for e in part2['files']:
        if e['path'].startswith('software/pc_pipeline/ball_measurement/'):
            p=Path(e['path']);assert sha((ROOT/p).read_bytes())==e['sha256'];dependencies.append(p)
    paths=sorted(set(paths+dependencies));dump(val/'SOURCE_SHA256.json',dict(schema='b-trajectory-v2-draft',git_commit=None,part2_unchanged=True,files=[dict(path=p.as_posix(),sha256=sha((ROOT/p).read_bytes()))for p in paths]))
    dump(val/'INPUT_SHA256.json',dict(source='B generated stereo practice; no external video/model; truth isolated',files=[dict(path=p.relative_to(val).as_posix(),sha256=sha(p.read_bytes()))for folder in [val/'inputs',val/'truth']for p in sorted(folder.rglob('*'))if p.is_file()]))
    logs=val/'logs';logs.mkdir(exist_ok=True)
    for name in ['configure.log','build.log','test.log']:shutil.copy2(build/name,logs/name)
    (val/'ctest-output.txt').write_text(tests,encoding='utf-8');(val/'tool-versions.txt').write_text(log(build/'tool-versions.txt')+f'\nPython={sys.version}\nOpenCV C++=4.10.0\n'+''.join(f'{k}={importlib.metadata.version(k)}\n'for k in ['numpy','opencv-python','matplotlib']),encoding='utf-8')
    shutil.copy2(ROOT/'reports/第三部分_三维轨迹事件_v2验证_2026-10-06.md',val/'验证报告.md')
    dump(val/'CONFIG_DEFAULTS.json',dict(schema='b-trajectory-v2-draft',geometry=dict(epipolar_px=2,reprojection_px=2,min_disparity_px=.5,min_depth_m=.1,max_depth_m=15,max_diameter_ratio=2,calibration_position_sigma_m=0,world_translation_sigma_m=0,world_rotation_sigma_rad=0,sync_sigma_s=0,sync_speed_bound_m_s=15),tracking=dict(gravity=9.80665,max_gap_s=.25,gate_squared=16.27,acceleration_noise=4,initial_velocity_variance=25),events=dict(min_score=.25,near_px=18,rise_m_s=.25,contact_velocity_change=1.2,max_observation_gap_s=.08,max_detection_latency_s=.25),online=dict(max_frames=256,max_detections=2048,max_pending_detections=32,max_event_s=4,settle_s=.3,restart_holding_frames=3,max_updates=64),fit=dict(min_points=6,min_span_s=.08,huber_iterations=8,max_residual_m=.03,release_noise_constraint='within actual time interval, root deviation <=interval width and declared uncertainty'),status='PC draft, not frozen common interfaces/rules'))
    command="& '.\\software\\pc_pipeline\\trajectory\\run_validation_v2.ps1' -OutputDirectory '_deliveries/part3_v2_final_validation'"
    dump(val/'RUN_MANIFEST.json',dict(date='2026-10-06',command=command,git_commit=None,cpp_checks=62,part2_regression_checks=42,ctest_groups=8,file_cases=84,board_fit_pairs=[12,30],board_heldout_pairs=[4,6],source_manifest_sha256=sha((val/'SOURCE_SHA256.json').read_bytes()),config_sha256=sha((val/'CONFIG_DEFAULTS.json').read_bytes()),C_independent_review=False,network_download='not executed: sandbox network restriction; escalation auto-review service failed get_channel_failed, model unsupported',not_executed=['OpenCV public chessboard practice','Linux/ARM (WSL not installed)','A system integration','C actual model and independent frozen truth/review','physical camera/sync/accuracy','hardware/target performance','root staged/full repository checks'],scope='B Windows PC code and synthetic regression'))
    (val/'README_先读.md').write_text('双击index.html查看总览，events.html查看事件原图、局部区域、框与三维片段。输入、隔离真值、JSON/CSV、估计标定参数、日志、配置与哈希齐全。源码另在第三部分_深化版源码测试说明.zip。所有数据为B开发合成与显式检测回放；C未独立复核，真实相机及硬件尚未验收。\n',encoding='utf-8')
    upload='''# 第三部分深化版提交说明

建议分支codex/b-trajectory-events-v2。本包以仓库根目录组织，可独立编译，另带第二部分v2未改源码。

第三部分初版已合入时，更新software/pc_pipeline/trajectory/及tools/fixtures/trajectory*，新增本轮v2 reports/handoffs，保留仓库既有v1历史报告/交接。在handoffs/README.md登记v2入口即可。第二部分已合入时不重复上传依赖。若依赖尚未合入，在PR写清真实依赖PR、基准提交和目标分支，不能覆盖团队更晚改动。

核心接口b-trajectory-v2-draft，标定保持v1；图像输入需要真实reference_valid/reference_id。先按README运行run_validation_v2.ps1，再在真实仓库执行要求的check_repo --staged/unittest及任务验证。这里没有Git元数据，未完成仓库提交检查，没有推送或合并。最终仍由FengFengKang审批。

62项第三部分＋42项第二部分回归、84文件场景、4＋6棋盘留出通过。原图证据与运行结果另在第三部分_深化版验收结果.zip。公开棋盘、Linux、A/C真实联调和实物验收尚未执行，详见报告。
'''
    source=out/'第三部分_深化版源码测试说明.zip'
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED,compresslevel=9)as z:
        for p in paths:z.write(ROOT/p,p.as_posix())
        z.writestr('SOURCE_SHA256.json',(val/'SOURCE_SHA256.json').read_bytes());z.writestr('第三部分_深化版上传说明.md',upload.encode('utf-8'))
    # Keep reproducible evidence and inputs; omit duplicated noisy compiler
    # console and matplotlib cache. Full build/test logs stay in logs/.
    evidence=[p for p in sorted(val.rglob('*'))if p.is_file()and p.name not in ['EVIDENCE_SHA256.json','build-console.txt']and 'plot-cache'not in p.relative_to(val).parts]
    dump(val/'EVIDENCE_SHA256.json',dict(files=[dict(path=p.relative_to(val).as_posix(),sha256=sha(p.read_bytes()))for p in evidence]));evidence.append(val/'EVIDENCE_SHA256.json')
    result=out/'第三部分_深化版验收结果.zip'
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED,compresslevel=9)as z:
        for p in evidence:z.write(p,p.relative_to(val).as_posix())
    for archive,manifest in [(source,'SOURCE_SHA256.json'),(result,'EVIDENCE_SHA256.json')]:
        with zipfile.ZipFile(archive)as z:
            assert z.testzip()is None
            for e in json.loads(z.read(manifest))['files']:assert sha(z.read(e['path']))==e['sha256']
            assert not any(n.endswith(('.exe','.dll','.lib','.obj','.pyc','.db','.al','.pth','.pt','.onnx','.rknn'))for n in z.namelist())
    with zipfile.ZipFile(result)as z:
        for page in ['index.html','events.html']:
            links=Links();links.feed(z.read(page).decode('utf-8'));assert all(v in z.namelist()for v in links.links),page
        for p in [n for n in z.namelist()if n.startswith('evidence/')and n.endswith('manifest.json')]:
            m=json.loads(z.read(p));parent=Path(p).parent
            for media in m['media']:
                assert sha(z.read((parent/media['original']).as_posix()))==media['source_sha256']
                for key in ['roi64','roi256']:
                    if key in media:assert (parent/media[key]['file']).as_posix()in z.namelist()
    # Reuse checker logic solely for package file hygiene; never claim root
    # repository/staged checks from this source archive.
    reference=Path('C:/Users/27504/Downloads/pingpong-fpga-main.zip')
    if reference.exists():
        with zipfile.ZipFile(reference)as z:code=z.read('pingpong-fpga-main/tools/check_repo.py').decode('utf-8-sig')
        checker={'__name__':'package_inspector'};exec(compile(code,'attachment/check_repo.py','exec'),checker)
        issues=[(p.as_posix(),s)for p in paths for s in checker['inspect_file'](p.as_posix(),(ROOT/p).read_bytes())];assert not issues,issues
    for p in [source,result]:print(f'{p.name} bytes={p.stat().st_size:,} sha256={sha(p.read_bytes())}')
    print('PART3_V2_PACKAGE_PASS: tests, dependency hashes, CRC, all evidence/source hashes and HTML/media links; no GitHub writes')


if __name__=='__main__':main()
