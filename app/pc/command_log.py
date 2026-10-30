"""Keep detailed subprocess output in a local log instead of repainting CMD."""
from pathlib import Path
from datetime import datetime
import json
import subprocess


def run_logged(command, log_path, **kwargs):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('ab') as log:
        log.write(('\n' + json.dumps({'time': datetime.now().isoformat(timespec='seconds'),
                                    'command': [str(x) for x in command]}, ensure_ascii=False) + '\n').encode('utf-8'))
        log.flush()
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, **kwargs)
    if result.returncode:
        with log_path.open('rb') as log:
            log.seek(max(0, log_path.stat().st_size - 4096))
            tail = log.read().decode('utf-8', 'replace').splitlines()[-12:]
        print('\nSTEP FAILED. Detailed log:', log_path, flush=True)
        for line in tail:
            print(line[:240], flush=True)
        raise subprocess.CalledProcessError(result.returncode, command)
    return result
