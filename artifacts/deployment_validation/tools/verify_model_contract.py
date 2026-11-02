#!/usr/bin/env python3
"""Static contract check: production RKNN session vs the delivered DFL model."""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
SESSION = ROOT / "source/native/rk_runtime/c_rknn/runtime_session.cpp"


def main() -> int:
    meta_path = pathlib.Path(sys.argv[1])
    meta = json.loads(meta_path.read_text("utf-8"))
    outputs = meta["outputs"]
    source = SESSION.read_text("utf-8")
    accepted = "count.n_output != 1 && count.n_output != 6" in source
    print(f"model={meta_path}")
    print(f"model_outputs={meta['num_outputs']}")
    for out in outputs:
        print(f"  {out['name']}: shape={out['shape']} quant_dtype={out['quant_dtype']} qtype={out['qtype']}")
    print(f"runtime_accepts={accepted} (explicitly 1 or 6 outputs)")
    compatible = accepted and meta["num_outputs"] in (1, 6)
    print(f"MODEL_RUNTIME_CONTRACT={'PASS' if compatible else 'FAIL'}")
    if not compatible:
        print("reason: runtime_session.cpp rejects this output count before any inference")
    return 0 if compatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
