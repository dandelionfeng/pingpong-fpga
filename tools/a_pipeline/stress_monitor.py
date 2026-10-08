"""Observe process RSS during an actual 10,000-pair CPU stress run."""
from pathlib import Path
import argparse
import json
import subprocess
import time
import psutil
import hashlib


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--executable', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--pairs', type=int, default=10000)
    p.add_argument('--manifest')
    p.add_argument('--replay')
    a = p.parse_args()
    root = Path(a.output)
    root.mkdir(parents=True, exist_ok=True)
    executable_sha256=hashlib.sha256(Path(a.executable).read_bytes()).hexdigest()
    command=[a.executable, '--stress', str(a.pairs)]
    scope='640x360 seven stages, both eyes, ownership/cache; scheduler bounds separately tested'
    if a.manifest:
        pairs=len(json.loads(Path(a.manifest).read_text(encoding='utf-8'))['frames'])
        if a.pairs % pairs: raise SystemExit('stress pairs must divide manifest length')
        command=[a.executable,'--input',a.manifest,'--output',str(root/'run'),'--repeat',str(a.pairs//pairs),
                 '--no-images','--detector','replay','--replay',a.replay,
                 '--detector-rate','1000','--detector-delay-ms','20']
        scope='actual 125-file replay repeated to 10000 pairs; raw decode/SHA, both eyes, input queue/cache, async owned detector contexts, completion archive'
    with (root/'stdout.json').open('w') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        process = psutil.Process(child.pid)
        start = time.monotonic()
        samples = []
        while child.poll() is None:
            try:
                samples.append({'elapsed_s': time.monotonic()-start, 'rss_bytes': process.memory_info().rss})
            except psutil.NoSuchProcess:
                break
            time.sleep(.25)
        code = child.wait()
    result = json.loads((root/'stdout.json').read_text())
    # Exclude DLL/allocator warmup. Report end-window growth, not just endpoint RSS.
    warm = samples[len(samples)//4:]
    split = max(1, len(warm)//4)
    early = max(s['rss_bytes'] for s in warm[:split]) if warm else 0
    late = max(s['rss_bytes'] for s in warm[-split:]) if warm else 0
    growth = late-early
    report = {'status': 'passed' if code == 0 and result['status'] == 'passed' and growth < 32*1024*1024 else 'failed',
              'command': command, 'result': result,
              'samples': len(samples), 'peak_rss_bytes': max((s['rss_bytes'] for s in samples), default=0),
              'warmup_excluded_fraction': .25, 'end_window_growth_bytes': growth,
              'growth_limit_bytes': 32*1024*1024, 'scope': scope}
    report['executable_sha256']=executable_sha256
    if a.manifest: report['input_manifest_sha256']=hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest()
    if a.manifest:
        stats=result['detector_statistics']
        if result['processed']!=a.pairs or result['input_queue_peak']>8 or result['frame_cache_size']>8 or stats['pending_peak']>2 or stats['completion_peak']>8:
            report['status']='failed'
    (root/'rss.json').write_text(json.dumps(samples, indent=2))
    (root/'summary.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
