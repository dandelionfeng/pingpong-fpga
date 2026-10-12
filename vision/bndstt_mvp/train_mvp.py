"""Single formal YOLOv8n MVP training run for the BNDSTT C-side detector.

PROTOTYPE / MVP only: 29 curated grayscale frames (23 train / 6 val). The run is
deliberately fixed — no hyper-parameter search, no second seed.

  python vision/bndstt_mvp/train_mvp.py

Uses the CUDA venv interpreter only:
  .venv\\c-detector\\Scripts\\python.exe
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "artifacts/files/datasets/BNDSTT_YOLO_MVP_V1/dataset.yaml"
DEFAULT_WEIGHTS = ROOT / "artifacts/files/models/ultralytics/yolov8n.pt"
DEFAULT_PROJECT = ROOT / "artifacts/runs"
RUN_NAME = "bndstt_yolov8n_mvp_v1"

FIXED = dict(
    epochs=25,
    imgsz=640,
    batch=8,
    workers=4,
    amp=True,
    seed=42,
    deterministic=True,
    pretrained=True,
    patience=25,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    ap.add_argument("--name", default=RUN_NAME)
    ap.add_argument("--batch", type=int, default=FIXED["batch"])
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    import torch
    import ultralytics
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available; refusing to train on CPU for the formal run")

    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": bool(torch.cuda.is_available()),
        "gpu": torch.cuda.get_device_name(0),
        "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1),
        "ultralytics": ultralytics.__version__,
    }
    try:
        import torchvision

        env["torchvision"] = torchvision.__version__
    except Exception:  # pragma: no cover
        env["torchvision"] = None
    print(json.dumps(env, indent=1), flush=True)

    if not args.data.exists():
        raise SystemExit(f"dataset yaml missing: {args.data}")
    if not args.weights.exists():
        raise SystemExit(f"pretrained weights missing: {args.weights}")

    model = YOLO(str(args.weights))
    results = model.train(
        data=str(args.data),
        epochs=FIXED["epochs"],
        imgsz=FIXED["imgsz"],
        batch=args.batch,
        device=args.device,
        workers=FIXED["workers"],
        amp=FIXED["amp"],
        seed=FIXED["seed"],
        deterministic=FIXED["deterministic"],
        pretrained=FIXED["pretrained"],
        patience=FIXED["patience"],
        project=str(args.project),
        name=args.name,
        exist_ok=True,
        verbose=True,
        val=True,
        plots=True,
    )

    save_dir = Path(getattr(results, "save_dir", args.project / args.name))
    (save_dir / "environment.json").write_text(json.dumps(env, indent=1), encoding="utf-8")
    print(f"save_dir={save_dir}", flush=True)
    print(f"best={save_dir / 'weights/best.pt'} exists={(save_dir / 'weights/best.pt').exists()}", flush=True)
    print(f"last={save_dir / 'weights/last.pt'} exists={(save_dir / 'weights/last.pt').exists()}", flush=True)
    print(f"results_csv={save_dir / 'results.csv'} exists={(save_dir / 'results.csv').exists()}", flush=True)


if __name__ == "__main__":
    main()
