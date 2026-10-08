"""Score C++ outputs against separately held truth; never called by the algorithm."""
import argparse
import json
import math
from pathlib import Path
import numpy as np


def score(truth_path: Path, results: Path, output: Path):
    expected = json.loads(truth_path.read_text(encoding='utf-8'))['cases']
    rows, clear_errors, failures = [], [], []
    for item in expected:
        name = item['name']
        problems = []
        try:
            r = json.loads((results / f'{name}.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            rows.append(dict(name=name, passed=False, errors=[str(exc)]))
            failures.append(name)
            continue
        if r['source'] != item['expected_source']:
            problems.append(f'source {r["source"]} != {item["expected_source"]}')
        if item.get('reason') and r['reason'] != item['reason']:
            problems.append(f'reason {r["reason"]} != {item["reason"]}')
        error = None
        if item.get('center') is not None:
            observation = r.get('observation')
            if not observation:
                problems.append('missing observation')
            else:
                error = math.dist(observation['image_center'], item['center'])
                if not math.isfinite(error) or error > item['max_error_px']:
                    problems.append(f'center_error={error}')
                if item['category'] == 'clear':
                    clear_errors.append(error)
        if item['expected_source'] != 'observed' and 'observation' in r:
            problems.append('invalid/predicted exported as measured observation')
        if item.get('quality') == 'reduced':
            q = r.get('observation', {}).get('quality', {})
            if q.get('level') != 'reduced' or not q.get('possible_occlusion'):
                problems.append('occlusion quality warning missing')
        if item.get('quality') == 'image_boundary':
            if not any(m['quality']['touches_image_boundary'] for m in r.get('attempts', [])):
                problems.append('image boundary evidence missing')
        if name == 'apex_zero_mask_remeasure':
            if r.get('observation', {}).get('search_source') != 'prediction' or 'prediction' not in r:
                problems.append('prediction provenance missing')
        if problems:
            failures.append(name)
        rows.append(dict(name=name, passed=not problems, source=r['source'], reason=r['reason'], center_error_px=error, errors=problems))
    p95 = float(np.percentile(clear_errors, 95)) if clear_errors else None
    report = dict(total=len(rows), passed=len(rows)-len(failures), failed=len(failures), failed_cases=failures,
                  clear_count=len(clear_errors), clear_p95_error_px=p95,
                  scope='synthetic 2D fixtures and interface faults; not hardware/real-image evidence', cases=rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}))
    for row in rows:
        if not row['passed']:
            print('FAIL', row['name'], row['errors'])
    return 0 if not failures and p95 is not None and p95 <= 1.0 else 1

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(score(args.truth, args.results, args.report))
