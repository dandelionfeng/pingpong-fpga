from pathlib import Path
import subprocess,sys,os,json
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parent
def main():
    menu='''\nCurrent: INT8 V6 + hand/racket on every pair; FPGA + TESO + measurement on RK\n1 Open field-test manual\n2 RK J3 serial console\n3 Open FPGA BitWriter\n4 Deploy selected RK sources and models over J4 ADB\n5 Process a stereo AVI on RK and build PC replay\n6 Rebuild PC replay from a retrieved RK result\n7 Open results folder\n8 Retrieve completed RK recording and build HTML replay on PC\n9 Open latest HTML replay (0.5x)\n10 Open project archive\n0 Exit\n'''
    while True:
        print(menu);key=input('PC Select [0-10]: ').strip()
        try:
            if key=='0':return
            if key=='1':os.startfile(Path(json.loads((ROOT/'归档索引.json').read_text(encoding='utf-8'))['current_manual']))
            elif key=='2':subprocess.run([sys.executable,str(BASE/'pc/serial_terminal.py')],check=True)
            elif key=='3':
                bit=BASE/'fpga/afh03_sgdma_motion7.bit';print('PROGRAM_SRAM bitstream:',bit);os.startfile(bit.parent)
                tool=Path(r'C:\Anlogic\TD_Release_2026.1_SP2.200.067\bin\bw.exe');subprocess.Popen([str(tool)],cwd=tool.parent)
            elif key=='4':subprocess.run([sys.executable,str(BASE/'pc/deploy.py')],check=True)
            elif key=='5':subprocess.run([sys.executable,str(BASE/'pc/run_board_video.py')],check=True)
            elif key=='6':
                case=input('Completed case directory or app-run-receipt.json: ').strip().strip('"')
                from pull_recording import prepare_replay
                receipt=prepare_replay(Path(case).parent if Path(case).is_file() else Path(case))
                subprocess.run([sys.executable,str(BASE/'pc/replay.py'),str(receipt)],check=True)
            elif key=='7':os.startfile(BASE/'results')
            elif key=='8':
                name=input('RK recording name (for example serve_01): ').strip()
                subprocess.run([sys.executable,str(BASE/'pc/pull_recording.py'),name],check=True)
            elif key=='9':
                pointer=BASE/'results/latest-replay.txt'
                if not pointer.is_file():
                    print('No new replay yet. Use menu 5 or 8; validated replays are in the archive.');continue
                page=Path(pointer.read_text(encoding='utf-8').strip())
                import webbrowser
                webbrowser.open(page.resolve().as_uri())
            elif key=='10':os.startfile(Path(json.loads((ROOT/'归档索引.json').read_text(encoding='utf-8'))['archive_root']))
            else:print('INVALID MENU: enter a number from 0 to 10. To run RK Linux commands, select 2 first and wait for the RK shell prompt. Do not enter shell commands at PC Select.')
        except KeyboardInterrupt:print('\nACTION INTERRUPTED. PC menu is ready.')
        except Exception as e:print('ACTION FAILED:',e)
if __name__=='__main__':main()
