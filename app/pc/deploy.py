from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from deploy_quick_field import deploy
if __name__=='__main__':deploy()
