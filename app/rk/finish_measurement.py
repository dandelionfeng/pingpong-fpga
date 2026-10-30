"""Finish motion-transition release on RK, without video or HTML generation."""
from pathlib import Path
import argparse, json, os, platform, resource, subprocess, sys, time

ROOT = Path(__file__).resolve().parent
OPTIONAL_POSTPROCESS_TIMEOUT_SECONDS = 30
sys.path.insert(0, str(ROOT / 'pc'))
from case_io import normalize_board, read


def finish(case, output=None):
    case = Path(case).resolve()
    output = Path(output).resolve() if output else case
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = time.process_time()
    receipt = normalize_board(case)
    env = os.environ.copy()
    env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    latest = output / 'motion-current' / 'latest-release.json'
    try:
        subprocess.run([sys.executable, str(ROOT / 'pc/latest_release.py'), str(receipt),
                    '--output', str(latest.parent), '--no-plot', '--no-replay', '--recompute'],
                   env=env, check=True, timeout=OPTIONAL_POSTPROCESS_TIMEOUT_SECONDS)
        motion=read(latest)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as error:
        # Optional pixel/refinement failures must not discard saved 3D points.
        sys.path.insert(0,str(ROOT/'algorithms'))
        from best_effort import complete_output
        app=read(receipt)
        records=[json.loads(s) for s in (Path(app['result'])/'frames.jsonl').read_text('utf-8').splitlines() if s.strip()]
        motion=complete_output({},app,records,errors=[str(error)])
        motion['source_receipt']=str(receipt.resolve())
        motion['timing']={'measurement_wall_ms':(time.perf_counter()-started)*1000}
        latest.parent.mkdir(parents=True,exist_ok=True)
        (latest.parent/'motion-attempt.json').write_text(json.dumps({
            'attempted':True,'status':'optional_stage_fallback','error':str(error),
            'output_status':motion.get('output_status'),'source_receipt':str(receipt.resolve())
        },indent=2),encoding='utf-8')
        latest.write_text(json.dumps(motion,indent=2),encoding='utf-8')
    fit_valid=bool(motion.get('fit_valid'))
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    available=motion.get('trajectory_available',fit_valid)
    result = {'schema_version': 1, 'status': 'measured' if fit_valid else ('estimated' if available else 'no_valid_fit'),
              'execution_host': platform.machine(), 'measurement_host': 'RK',
              'fit_valid': fit_valid, 'web_generated': False,
              'release_valid':motion.get('release_valid',fit_valid),
              'trajectory_available':available,'measurement_available':motion.get('measurement_available',fit_valid),
              'measurement_estimated':motion.get('measurement_estimated',False),
              'optional_postprocess_timeout_s':OPTIONAL_POSTPROCESS_TIMEOUT_SECONDS,
              'measurement_wall_ms': (time.perf_counter() - started) * 1000,
              'measurement_cpu_ms': (time.process_time() - cpu + after.ru_utime + after.ru_stime
                                     - before.ru_utime - before.ru_stime) * 1000,
              'result': str(latest.relative_to(output)),
              'scope': 'completed recording; actual stereo fit and motion-release attempt; no MP4 or HTML',
              'motion_status':motion['motion_status'],
              'motion_diagnostic':'motion-current/motion-attempt.json'}
    result['timing'] = motion['timing']
    (output / 'measurement-complete.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('MEASUREMENT_SAVED', json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('case', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    finish(a.case, a.output)
