from pathlib import Path
import argparse,json,os,subprocess,sys,tarfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from quick_common import BASE,REMOTE,ADB,VERSION,read,sha,quiet,verify_local,log_path,logged,shell
def deploy():
    verify_local();quiet()
    exists=subprocess.run(ADB+['shell','test -d '+REMOTE],capture_output=True)
    if exists.returncode==0:
        local_payload=sha(BASE/'rk/payload-sha256.json')
        remote_payload=shell(['sha256sum',REMOTE+'/payload-sha256.json'],True).stdout.decode().split()[0]
        if remote_payload!=local_payload:
            # A known intact prior package is upgraded under the capture lock.
            # Unknown or modified installations are retained and reported.
            archive=BASE/'dist/quick-field-runtime.tar.gz'
            stamp=__import__('datetime').datetime.now().strftime('%Y%m%d%H%M%S')
            stage=REMOTE+'.final-update-'+stamp;remote_archive=stage+'.tar.gz';path=log_path('update')
            logged(ADB+['push',str(archive),remote_archive],path)
            expected=sha(archive)
            command=f"test ! -e {stage} && test \"$(sha256sum {remote_archive} | cut -d' ' -f1)\" = {expected} && mkdir {stage} && tar -xzf {remote_archive} -C {stage} && python3 -B {stage}/update_runtime.py {REMOTE}"
            logged(ADB+['shell',command],path)
            print('最终版计时脚本已更新；模型和算法保持原哈希，旧脚本已备份。',flush=True)
        info=shell(['python3','-B',REMOTE+'/preflight.py'],True,60)
        value=json.loads(info.stdout);assert value['version']==VERSION['version']
        print('板端版本和文件校验通过：'+VERSION['version'],flush=True);return value
    archive=BASE/'dist/quick-field-runtime.tar.gz'
    if not archive.is_file():raise FileNotFoundError('缺少离线部署包：'+str(archive))
    stamp=__import__('datetime').datetime.now().strftime('%Y%m%d%H%M%S')
    stage=REMOTE+'.staging-'+stamp;remote_archive=stage+'.tar.gz'
    path=log_path('deploy')
    print('部署已验证程序、640 INT8模型及离线Python依赖……',flush=True)
    logged(ADB+['push',str(archive),remote_archive],path)
    expected=sha(archive)
    command=f"test ! -e {REMOTE} && test ! -e {stage} && test \"$(sha256sum {remote_archive} | cut -d' ' -f1)\" = {expected} && mkdir {stage} && tar -xzf {remote_archive} -C {stage} && python3 -B {stage}/provision.py && mv {stage} {REMOTE}"
    logged(ADB+['shell',command],path)
    info=json.loads(shell(['python3','-B',REMOTE+'/preflight.py'],True,60).stdout)
    (BASE/'evidence').mkdir(exist_ok=True)
    (BASE/'evidence/deployment.json').write_text(json.dumps({'version':VERSION['version'],'archive_sha256':expected,'remote':REMOTE,
        'info':info,'method':'new staging directory; payload checks; exact binary/model reuse; isolated rename'},ensure_ascii=False,indent=2),encoding='utf-8')
    print('快速现场版部署完成。',flush=True);return info
if __name__=='__main__':
    try:deploy()
    except Exception as e:print(str(e),file=sys.stderr);sys.exit(2)
