from pathlib import Path
import argparse,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from field_actions import video
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('video',nargs='?');a=p.parse_args();video(a.video or input('Stereo AVI: ').strip().strip(chr(34)))
