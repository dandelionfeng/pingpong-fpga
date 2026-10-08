"""Map Windows absolute input references to WSL mounts without changing data."""
from pathlib import Path
import argparse
import json
import re


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();data=json.loads(Path(a.input).read_text(encoding='utf-8'))
    for frame in data['frames']:
        for key in ('file','left_file','right_file'):
            if key not in frame: continue
            text=frame[key].replace('\\','/')
            if re.match(r'^[a-zA-Z]:/',text):
                frame[key]='/mnt/'+text[0].lower()+text[2:]
    data['path_mapping']={'version':1,'source_manifest':str(Path(a.input).resolve()),'target':'wsl-drive-mounts','content_hashes':'unchanged'}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
