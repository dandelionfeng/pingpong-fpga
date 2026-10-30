from pathlib import Path
import json,os,signal
ROOT=Path(__file__).resolve().parent
version=json.loads((ROOT/'version.json').read_text())
path=Path(version['result_root'])/'active-session.json'
if not path.exists():raise SystemExit('NO_ACTIVE_CAPTURE')
state=json.loads(path.read_text());pid=state.get('capture_pid')
if state.get('stage')!='capture' or not isinstance(pid,int):raise SystemExit('NOT_RECORDING; saved-frame analysis continues normally')
cmd=Path(f'/proc/{pid}/cmdline')
args=cmd.read_bytes().split(b'\0') if cmd.exists() else []
if not args or args[0].decode()!=str(ROOT/'build/motion7_chain_kinematic') or b'@camera' not in args:raise SystemExit('CAPTURE_PROCESS_NOT_ACTIVE')
os.kill(pid,signal.SIGINT)
print('NORMAL_STOP_REQUESTED; analysis and saving follow automatically')
