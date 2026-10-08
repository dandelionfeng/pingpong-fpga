"""Actual CLI gates, live replacement evidence, expiry, and archive identities."""
from pathlib import Path
import argparse
import json
import subprocess


def main():
    p=argparse.ArgumentParser();p.add_argument('--executable',required=True);p.add_argument('--manifest',required=True)
    p.add_argument('--replay',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=True)
    entries=json.loads(Path(a.manifest).read_text(encoding='utf-8'))['frames'];by_id={x['pair_id']:x for x in entries}
    report={'status':'running','checks':[]}
    def run(name,options,expected=0):
        cmd=[a.executable,'--input',a.manifest,'--output',str(root/name),'--no-images']+options
        r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8')
        (root/(name+'.txt')).write_text(r.stdout,encoding='utf-8')
        report['checks'].append({'name':name,'command':cmd,'exit_code':r.returncode})
        assert r.returncode==expected,(name,r.stdout)
        return json.loads(r.stdout)
    try:
        cpu=run('cpu',[])
        mock=run('mock',['--motion','mock-dma'])
        assert cpu['processed']==mock['processed']==len(entries)
        assert cpu['mask_sequence_sha256']==mock['mask_sequence_sha256']
        real=run('realtime',['--motion','mock-dma','--mock-delay-ms','80','--realtime',
                             '--detector','replay','--replay',a.replay,'--detector-delay-ms','160'])
        assert real['input_replaced']>0 and real['input_queue_peak']<=8
        stats=real['detector_statistics'];assert stats['pending_peak']<=2 and stats['completion_peak']<=8
        errors=[json.loads(x) for x in (root/'realtime/errors.jsonl').read_text().splitlines()]
        assert all(x['pair_id'] in by_id for x in errors)
        frames=[json.loads(x) for x in (root/'realtime/frames.jsonl').read_text().splitlines()]
        previous=0
        for f in frames:
            assert f['timestamp_ns']==by_id[f['pair_id']]['timestamp_ns']
            assert f['eyes'][0]['reference_id']==previous
            previous=f['pair_id']
        detections=[json.loads(x) for x in (root/'realtime/detections.jsonl').read_text().splitlines()]
        assert detections
        for d in detections:
            assert d['source_pair_id'] in by_id and d['timestamp_ns']==by_id[d['source_pair_id']]['timestamp_ns']
            if d['status']!='ok':assert not d['boxes']
        for name,options,needle in (
            ('missing-pcie',['--motion','pcie'],'PCIe unavailable'),
            ('missing-model',['--detector','model'],'actual model unavailable'),
            ('missing-full',['--full'],'full system unavailable')):
            failed=run(name,options,1);assert needle in failed['error']
        report.update(status='passed',realtime_processed=real['processed'],replaced=real['input_replaced'],
                      detector_statistics=stats,archived_detections=len(detections),mask_sequence_sha256=cpu['mask_sequence_sha256'])
    except Exception as e:report.update(status='failed',error=str(e))
    (root/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
    if report['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
