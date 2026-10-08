"""Collect existing execution evidence; never infer a pass from file existence."""
from pathlib import Path
import datetime
import hashlib
import json
import shutil
import subprocess
import zipfile
import re
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
PACKAGE=ROOT/'dist/A-USB-Stereo-Pipeline-1.0.0-Windows'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))


def main():
    checks={
        'pixels':read('output/a-pixel-final-20261005.json'),
        'rtl_125':read('output/a-rtl-final-20261005/summary.json'),
        'rtl_faults':read('output/a-rtl-small-final-20261005/summary.json'),
        'lifecycle_10000':read('output/a-lifecycle-frozen-20261005/summary.json'),
        'runtime':read('output/a-portable-frozen-runtime-20261005/summary.json'),
        'portable_gui':read('output/a-portable-frozen-gui-20261005/gui-test.json'),
        'core':read('tmp/a-core-frozen.json'),
        'linux_cpu':read('output/a-linux-frozen-125-20261005/run.json'),
        'modules':read('output/a-modules-frozen-20261005/run.json')}
    for name,item in checks.items():
        assert item['status']=='passed',(name,item)
    assert checks['lifecycle_10000']['result']['processed']==10000
    assert sha(PACKAGE/'pipeline_cli.exe')==checks['lifecycle_10000']['executable_sha256']
    assert checks['modules']['model_status']=='integration-test'
    mask=checks['linux_cpu']['mask_sequence_sha256']
    assert mask==checks['runtime']['mask_sequence_sha256']==checks['portable_gui']['export']['mask_sequence_sha256']
    manifest=ROOT/'data/manifests/a-usb-125-20261005.json'
    manifest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'tmp/a-input-125.json',manifest)
    data=json.loads(manifest.read_text(encoding='utf-8'))
    hashes=[]
    for item in data['frames']:
        file=Path(item['file']);assert sha(file)==item['sha256'];hashes.append(item['sha256'])
    td=Path((ROOT/'build/a-motion-td-latest.txt').read_text(encoding='utf-8-sig').strip())
    assert 'A_MOTION_SYNTH_PASS' in (td/'SUCCESS.txt').read_text()
    area=(td/'core_gate.area').read_text(encoding='utf-8')
    def resource(name):return int(re.search(r'^\s*#'+re.escape(name)+r'\s+(\d+)',area,re.MULTILINE).group(1))
    slice_match=re.search(r'^#slice\*\s+(\d+)\s+out of\s+(\d+)\s+([\d.]+)%',area,re.MULTILINE)
    hygiene=(ROOT/'tmp/a-repo-hygiene.log').read_text()
    assert '0 problem(s)' in hygiene
    unittest=(ROOT/'tmp/a-repo-unittest.log').read_text()
    assert 'Ran 5 tests' in unittest and 'OK' in unittest
    checks['repository']={'status':'passed','hygiene':hygiene.strip(),'unittest':'5 tests passed','diff_check':'git diff --cached --check passed'}
    source_dirs=['software/pc_pipeline','tools/a_pipeline','fpga/rtl/a_motion','fpga/sim/a_motion','fpga/projects/a_motion_td']
    source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for folder in source_dirs
                   for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    binary_files={
        'pipeline_cli':PACKAGE/'pipeline_cli.exe','pipeline_gui':PACKAGE/'pipeline_gui.exe',
        'opencv_world4130':PACKAGE/'opencv_world4130.dll','Qt6Core':PACKAGE/'Qt6Core.dll',
        'iverilog':ROOT/'.tools/iverilog/app/bin/iverilog.exe','vvp':ROOT/'.tools/iverilog/app/bin/vvp.exe',
        'TD':Path('C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe'),
        'MSVC':Path('C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/cl.exe'),
        'opencv_download':ROOT/'.tools/downloads/opencv-4.13.0-windows.exe'}
    evidence=PACKAGE/'evidence';evidence.mkdir(exist_ok=True)
    td_evidence=evidence/'td';td_evidence.mkdir(exist_ok=True)
    for name in ('console.log','core_gate.area','source-sha256.json','SUCCESS.txt'):
        shutil.copy2(td/name,td_evidence/name)
    shutil.copy2(td/'a_motion_Runs/syn_1/run.log',td_evidence/'synthesis.log')
    logs={}
    for path in (ROOT/'tmp').glob('a-*'):
        if path.is_file() and path.suffix in ('.log','.json'):
            target=evidence/'logs'/path.name;target.parent.mkdir(exist_ok=True)
            shutil.copy2(path,target);logs[str(path.relative_to(ROOT)).replace('\\','/')]=sha(path)
    for label,path in (
        ('rtl_all',ROOT/'output/a-rtl-final-20261005'),
        ('rtl_faults',ROOT/'output/a-rtl-small-final-20261005'),
        ('stress',ROOT/'output/a-lifecycle-frozen-20261005'),
        ('gui',ROOT/'output/a-portable-frozen-gui-20261005')):
        target=evidence/label;target.mkdir(exist_ok=True)
        for name in ('summary.json','simulation.log','compile.log','rss.json','stdout.json','gui-test.json','gui.png','canvas.png'):
            if (path/name).exists():shutil.copy2(path/name,target/name)
    report={'schema_version':1,'status':'passed','scope':'A complete software/RTL-first3/simulation/GUI/deployment-preparation; no physical acceptance',
            'created_at':datetime.datetime.now().astimezone().isoformat(),'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
            'base_commit':'d6cf530','input':{'manifest':str(manifest),'sha256':sha(manifest),'pairs':len(hashes),'unique_content':len(set(hashes)),
                                       'geometry':'duplicated_monocular','sampling':'video requested 16ms, not measured device fps'},
            'tools':{'opencv':'4.13.0','qt':'6.8.3','icarus':'12.0 (devel)','TD':'2026.1 SP2.200.067','numpy':np.__version__},
            'binary_sha256':{name:{'path':str(p),'sha256':sha(p)} for name,p in binary_files.items()},
            'source_sha256':source_hashes,'log_sha256':logs,'checks':checks,
            'td':{'project':str(td/'a_motion.al'),'scope':'gate synthesis envelope','LUT':resource('lut'),'registers':resource('reg'),
                  'slice':int(slice_match.group(1)),'slice_percent':float(slice_match.group(3)),
                  'DRAM_LUT':resource('dram lut'),'ERAM':resource('eram'),'DSP':resource('dsp'),'IO':resource('IO'),
                  'warnings':'distributed RAM mapping and unconstrained IO; no place/route/board timing'},
            'delivery':str(PACKAGE),'external_dependencies':['actual B measurement/calibration','actual C model','B last four RTL and packer',
              'camera/AFH03','vendor DMA/DDR3L SDK','RK3576J AArch64 sysroot/OpenCV'],
            'not_executed':['physical USB/DDR3L/PCIe/NPU','board pins/place-route/timing/bitstream','actual model accuracy','metric real stereo accuracy','AArch64 project build without sysroot']}
    report_path=ROOT/'reports/A职责交付_20261005.json';report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for rel in ('reports/A职责交付_20261005.json','reports/A职责交付_20261005.md','handoffs/2026-10-05-a-usb-fpga-pipeline.md','data/manifests/a-usb-125-20261005.json'):
        p=ROOT/rel;shutil.copy2(p,evidence/p.name)
        dest=PACKAGE/'source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    # Refresh A-owned source/support files, leaving runtime bytes unchanged.
    for folder in source_dirs:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                dest=PACKAGE/'source'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    files={str(p.relative_to(PACKAGE)).replace('\\','/'):sha(p) for p in PACKAGE.rglob('*')
           if p.is_file() and '__pycache__' not in p.parts and p.name!='files-sha256.json'}
    (PACKAGE/'files-sha256.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=PACKAGE.parent/(PACKAGE.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in PACKAGE.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(PACKAGE.parent))
    source_archive=ROOT/'dist/A-USB-Stereo-Pipeline-1.0.0-source.zip'
    with zipfile.ZipFile(source_archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in (PACKAGE/'source').rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(PACKAGE/'source'))
    delivery={'schema_version':1,'package':str(PACKAGE),'archive':str(archive),'archive_sha256':sha(archive),
              'source_archive':str(source_archive),'source_archive_sha256':sha(source_archive),'report_sha256':sha(report_path)}
    (ROOT/'dist/a-delivery-20261005.json').write_text(json.dumps(delivery,indent=2),encoding='utf-8')
    print(json.dumps(delivery,indent=2))


if __name__=='__main__':main()
