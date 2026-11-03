"""Build the windowed one-file EXE entry. Run with the build Python environment."""
from pathlib import Path
import argparse,subprocess,sys,tempfile
def main():
    root=Path(__file__).resolve().parents[1];parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path);a=parser.parse_args()
    work=a.work or Path(tempfile.gettempdir())/'stereo-serve-build';work.mkdir(parents=True,exist_ok=True)
    from PIL import Image,ImageDraw
    icon=Image.new('RGBA',(256,256),'#edf2ff');d=ImageDraw.Draw(icon)
    d.ellipse((45,45,211,211),outline='#2862e8',width=12);d.arc((55,12,174,243),-80,80,fill='#2862e8',width=8);d.arc((8,80,243,203),190,345,fill='#2862e8',width=8)
    ico=root/'app/ui/application.ico';icon.save(ico,sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
        '--name','发球测量系统','--icon',str(ico),'--distpath',str(root),'--workpath',str(work/'objects'),
        '--specpath',str(work),str(root/'tools/launcher.py')],check=True)
if __name__=='__main__':main()
