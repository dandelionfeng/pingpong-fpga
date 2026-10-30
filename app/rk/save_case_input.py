"""Keep recorded input with a completed case for USB retrieval and PC replay."""
from pathlib import Path
import argparse,hashlib,json,os,shutil

def save(case,manifest_path):
    case=Path(case).resolve();manifest_path=Path(manifest_path).resolve()
    manifest=json.loads(manifest_path.read_text());target=case/'input';target.mkdir(exist_ok=False)
    copied={}
    for row in manifest['frames']:
        source=(manifest_path.parent/row['file']).resolve()
        if source not in copied:
            destination=target/'images'/f'{len(copied):06d}{source.suffix}'
            destination.parent.mkdir(exist_ok=True)
            if row.get('sha256') and hashlib.sha256(source.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('Input hash mismatch: '+str(source))
            try:os.link(source,destination)
            except OSError:shutil.copyfile(source,destination)
            copied[source]=destination.relative_to(target).as_posix()
        row['file']=copied[source]
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    summary=json.loads((case/'summary.json').read_text())
    receipt={'schema_version':1,'input_source':'recorded_video','input_manifest':'input/manifest.json',
        'run_status':summary['status'],'recorded_pairs':len(manifest['frames']),'processed_pairs':summary['pairs'],
        'final_event':summary.get('final_event'),'replay_generation_host':'PC',
        'source_manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    (case/'capture-complete.json').write_text(json.dumps(receipt,indent=2))
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('manifest',type=Path);a=p.parse_args()
    print(json.dumps(save(a.case,a.manifest)))
